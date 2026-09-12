import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from unittest.mock import patch

from src.forecast.simulation_models import CashFlowOccurrence, PreparedForecast, CandidatePayment
from src.forecast.simulator import simulate
from src.forecast.timeline import horizon_dates
from src.models.profile import FinancialProfile
from src.models.request import Request
from src.planning.capacity import (calculate_safe_amount, evaluate_capacity,
    find_earliest_full_payment_date, minimum_payment_headroom, prepare_capacity,
    CapacityVerificationError)

D=Decimal
START=date(2025,7,1)
PROFILE=FinancialProfile('u','USD',D('100'),D('20'),(),frozenset({'rent'}),
                         frozenset({'subscription'}),frozenset({'subscription'}),frozenset(),None)


def flow(offset=0,amount='30',direction='debit',source='e',**kwargs):
    return CashFlowOccurrence(source,'u',START+timedelta(days=offset),D(amount),'USD',direction,
                              'rent','structured_test','confirmed',**kwargs)


def context(flows=(),profile=PROFILE,unresolved=()):
    return prepare_capacity(profile,START,PreparedForecast((),tuple(flows),tuple(unresolved),(),0))


class CapacityTests(unittest.TestCase):
    def test_safe_amount_formula(self):
        self.assertEqual(calculate_safe_amount(context((flow(10),)),D('100')),D('50.00'))

    def test_safe_amount_zero_floor(self):
        self.assertEqual(calculate_safe_amount(context((flow(10,'110'),)),D('100')),D('0.00'))

    def test_safe_amount_requested_cap(self):
        self.assertEqual(calculate_safe_amount(context(),D('12.30')),D('12.30'))

    def test_safe_amount_uses_minimum_checkpoint(self):
        # Today's opening is unsafe even though today's closing recovers.
        ctx=context((flow(0,'100','credit'),),replace(PROFILE,current_available_balance=D('10')))
        self.assertTrue(all(e.closing_balance>=D('20') for e in ctx.baseline.entries))
        result=evaluate_capacity(ctx,D('100'))
        self.assertEqual(result.amount_safe_to_pay,0)
        self.assertFalse(result.safe_amount_verified)
        self.assertIsNone(result.earliest_date_for_full_payment)

    def test_payment_affected_checkpoints_allow_today_credit(self):
        result=evaluate_capacity(context((flow(0,'100','credit'),)),D('200'))
        self.assertEqual(result.all_checkpoint_headroom,D('80'))
        self.assertEqual(result.minimum_headroom,D('180'))
        self.assertEqual(result.amount_safe_to_pay,D('180.00'))
        self.assertTrue(result.maximality_verified)

    def test_future_credit_not_available_today(self):
        self.assertEqual(calculate_safe_amount(context((flow(1,'100','credit'),)),D('200')),D('80'))

    def test_safe_amount_exact_minimum_is_safe(self):
        result=evaluate_capacity(context((flow(4,'30'),)),D('100'))
        self.assertTrue(result.safe_amount_probe.safe)
        self.assertEqual(result.safe_amount_probe.minimum_projected_balance,D('20'))

    def test_safe_amount_one_cent_more_is_unsafe(self):
        result=evaluate_capacity(context((flow(4,'30'),)),D('100'))
        self.assertTrue(result.maximality_verified)
        self.assertEqual(result.next_cent_probe.amount,D('50.01'))
        self.assertEqual(result.next_cent_probe.minimum_projected_balance,D('19.99'))

    def test_safe_amount_verification(self):
        ctx=context()
        with patch('src.planning.capacity.simulate',wraps=simulate) as observed:
            self.assertEqual(calculate_safe_amount(ctx,D('100')),D('80'))
            self.assertEqual(observed.call_count,2)
            self.assertEqual(observed.call_args_list[0].kwargs['candidate_payments'][0].amount,D('80'))

    def test_verification_failure_does_not_publish_capacity(self):
        ctx=context()
        with patch('src.planning.capacity.simulate',return_value=replace(ctx.baseline,complete=False)):
            with self.assertRaises(CapacityVerificationError):
                calculate_safe_amount(ctx,D('100'))

    def test_cent_rounding_is_down_not_nearest(self):
        result=evaluate_capacity(context((flow(2,'30.001'),)),D('100'))
        self.assertEqual(result.amount_safe_to_pay,D('49.99'))
        self.assertTrue(result.safe_amount_verified)
        self.assertTrue(result.maximality_verified)

    def test_earliest_full_today(self):
        self.assertEqual(find_earliest_full_payment_date(context(),D('70')),START)

    def test_earliest_full_later(self):
        self.assertEqual(find_earliest_full_payment_date(context((flow(10,'100','credit'),)),D('150')),START+timedelta(days=10))

    def test_earliest_full_after_deadline_is_still_reported(self):
        request=Request('r','u',START,'purchase',D('150'),START+timedelta(days=3),False,'test')
        result=evaluate_capacity(context((flow(10,'100','credit'),)),request.requested_amount)
        self.assertGreater(result.earliest_date_for_full_payment,request.desired_completion_date)
        self.assertEqual(result.earliest_date_for_full_payment,START+timedelta(days=10))

    def test_earliest_full_none(self):
        result=evaluate_capacity(context(),D('100'))
        self.assertIsNone(result.earliest_date_for_full_payment)
        self.assertEqual(len(result.full_payment_probes),91)

    def test_earliest_full_ignores_payment_preferences(self):
        refusing=replace(PROFILE,payment_methods_user_will_consider=frozenset({'installments'}))
        accepts=replace(PROFILE,payment_methods_user_will_consider=frozenset({'full_payment'}))
        self.assertEqual(evaluate_capacity(context(profile=refusing),D('50')),
                         evaluate_capacity(context(profile=accepts),D('50')))
        self.assertEqual(find_earliest_full_payment_date(context(profile=refusing),D('50')),START)

    def test_earliest_full_ignores_spending_changes(self):
        reducible=flow(3,'90',series_id='series',flexibility='stoppable')
        reducible=replace(reducible,category='subscription')
        # The user allows stopping it, but capacity must retain the debit.
        self.assertIsNone(find_earliest_full_payment_date(context((reducible,)),D('20')))
        self.assertEqual(calculate_safe_amount(context((reducible,)),D('20')),D('0'))

    def test_reject_modified_baseline(self):
        ctx=context()
        modified=simulate(PROFILE,START,candidate_payments=(CandidatePayment(START,D('1'),'other'),))
        with self.assertRaisesRegex(ValueError,'unchanged baseline'):
            minimum_payment_headroom(modified,D('20'))

    def test_earliest_full_searches_calendar_days(self):
        result=evaluate_capacity(context((flow(10,'100','credit'),)),D('150'))
        self.assertEqual(tuple(p.date for p in result.full_payment_probes),horizon_dates(START)[:11])

    def test_earliest_full_request_horizon_not_payment_horizon(self):
        flows=(flow(90,'100','credit','salary'),flow(91,'500','debit','outside'))
        result=evaluate_capacity(context(flows),D('150'))
        self.assertEqual(result.earliest_date_for_full_payment,START+timedelta(days=90))
        self.assertEqual(len(result.full_payment_probes),91)

    def test_non_monotonic_safe_then_unsafe_is_impossible_for_fixed_flows(self):
        flows=(flow(5,'150','credit','pay1'),flow(20,'120','debit','rent'),flow(30,'100','credit','pay2'))
        outcomes=[simulate(PROFILE,START,explicit_occurrences=flows,
            candidate_payments=(CandidatePayment(day,D('100'),'probe'),)).safe for day in horizon_dates(START)]
        self.assertIn(False,outcomes)
        self.assertIn(True,outcomes)
        self.assertEqual(outcomes,sorted(outcomes))
        result=evaluate_capacity(context(flows),D('100'))
        self.assertEqual(result.earliest_date_for_full_payment,horizon_dates(START)[outcomes.index(True)])

    def test_incomplete_forecast_safe_amount_zero(self):
        result=evaluate_capacity(context(unresolved=('unknown rent amount',)),D('10'))
        self.assertEqual(result.amount_safe_to_pay,D('0'))
        self.assertIsNone(result.minimum_headroom)
        self.assertFalse(result.safe_amount_verified)
        self.assertIn('unknown rent amount',result.diagnostics)

    def test_incomplete_forecast_earliest_date_none(self):
        result=evaluate_capacity(context(unresolved=('unknown rent amount',)),D('10'))
        self.assertIsNone(result.earliest_date_for_full_payment)
        self.assertEqual(result.full_payment_probes,())

    def test_capacity_deterministic(self):
        ctx=context((flow(20,'30.123456789'),))
        expected=evaluate_capacity(ctx,D('100'))
        with localcontext() as arithmetic:
            arithmetic.prec=2
            self.assertEqual(evaluate_capacity(ctx,D('100')),expected)

    def test_capacity_no_float(self):
        for amount in (1.0,None,D('NaN'),D('Infinity'),D('-1')):
            with self.assertRaises(ValueError):
                evaluate_capacity(context(),amount)
        self.assertIsInstance(evaluate_capacity(context(),D('1')).amount_safe_to_pay,D)

    def test_zero_request_and_subcent_request(self):
        result=evaluate_capacity(context(),D('0'))
        self.assertEqual(result.amount_safe_to_pay,D('0'))
        self.assertEqual(result.earliest_date_for_full_payment,START)
        small=evaluate_capacity(context(),D('0.009'))
        self.assertEqual(small.amount_safe_to_pay,D('0.00'))
        self.assertEqual(small.full_payment_probes[0].amount,D('0.009'))

    def test_baseline_reused_without_recurrence_reconstruction(self):
        ctx=context((flow(10,'100','credit'),))
        with patch('src.forecast.recurrence.infer_recurring_series',side_effect=AssertionError('must not rebuild')):
            evaluate_capacity(ctx,D('150'))
        self.assertEqual(ctx.baseline.entries[0].closing_balance,D('100'))
