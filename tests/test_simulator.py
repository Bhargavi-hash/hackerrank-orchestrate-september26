import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

from src.data.currency import CurrencyConverter, MissingExchangeRateError
from src.data.indexes import build_indexes, build_linked_adjacency
from src.forecast.preparation import prepare_forecast, reconcile_projected_and_explicit_occurrences
from src.forecast.simulation_models import (CandidatePayment, CashFlowOccurrence,
    FutureEventDateSource, SameDayOrder, SpendingChangeEffect, TimingPolicy)
from src.forecast.simulator import check_safety, simulate, trace_json
from src.forecast.timeline import horizon_dates
from src.models.currency import ExchangeRate
from src.models.event import FinancialEvent
from src.models.profile import FinancialProfile
from fixtures import dataset

D = Decimal
START = date(2025, 7, 1)
PROFILE = FinancialProfile('u', 'USD', D('100'), D('20'), (), frozenset({'rent'}),
    frozenset({'subscription'}), frozenset({'subscription'}), frozenset(), None)


def flow(**changes):
    return replace(CashFlowOccurrence('s', 'u', START, D('30'), 'USD', 'debit',
        'subscription', 'recurrence_projection', 'projected', confidence='high',
        series_id='s', source_event_ids=('old',), flexibility='reducible_or_stoppable'), **changes)


def event(**changes):
    return replace(FinancialEvent('e', 'u', 'expense', 'Rent', 'rent', 'debit', D('30'),
        'USD', START, START + timedelta(days=2), 'scheduled', None, 'fixed', None), **changes)


def indexes(events):
    rows = {e.event_id: e for e in events}
    return SimpleNamespace(profile_by_user_id={'u': PROFILE}, events_by_user_id={'u': tuple(events)},
                           events_by_event_id=rows, linked_event_adjacency=build_linked_adjacency(rows))


class SimulatorTests(unittest.TestCase):
    def test_90_day_horizon_inclusive(self):
        dates = horizon_dates(START)
        self.assertEqual(len(dates), 91)
        self.assertEqual(dates[-1], START + timedelta(days=90))
        result = simulate(PROFILE, START, (flow(date=dates[-1]), flow(source_id='outside', date=dates[-1]+timedelta(days=1))))
        self.assertEqual(result.entries[-1].closing_balance, D('70'))

    def test_starting_balance_not_replayed_history(self):
        rows = [event(event_date=START-timedelta(days=1), settlement_date=START-timedelta(days=1), status='settled')]
        self.assertFalse(prepare_forecast(indexes(rows), 'u', START).explicit_occurrences)
        result = simulate(PROFILE, START, explicit_occurrences=(flow(status='settled'),))
        self.assertEqual(result.entries[-1].closing_balance, D('100'))

    def test_non_cash_never_enters_simulator(self):
        self.assertEqual(simulate(PROFILE, START, (flow(direction='non_cash'),)).minimum_projected_balance, D('100'))
        self.assertFalse(prepare_forecast(indexes([event(direction='non_cash')]), 'u', START).explicit_occurrences)

    def test_pending_credit_ignored(self):
        self.assertEqual(simulate(PROFILE, START, (flow(status='pending', direction='credit'),)).minimum_projected_balance, D('100'))
        prepared = prepare_forecast(indexes([event(direction='credit', status='pending')]), 'u', START)
        self.assertEqual(prepared.ignored_pending_credit_count, 1)
        self.assertFalse(prepared.explicit_occurrences)

    def test_pending_debit_reserved(self):
        prepared = prepare_forecast(indexes([event(status='pending', event_date=START-timedelta(days=2), settlement_date=None)]), 'u', START)
        self.assertEqual(prepared.explicit_occurrences[0].date, START)
        self.assertEqual(prepared.explicit_occurrences[0].provenance, 'pending_debit')
        self.assertEqual(simulate(PROFILE, START, explicit_occurrences=prepared.explicit_occurrences).minimum_projected_balance, D('70'))

    def test_direct_overdue_pending_flow_is_reserved(self):
        overdue=flow(date=START-timedelta(days=2),status='pending',provenance='pending_debit')
        self.assertEqual(simulate(PROFILE,START,explicit_occurrences=(overdue,)).entries[0].closing_balance,D('70'))

    def test_cancelled_ignored(self):
        self.assertEqual(simulate(PROFILE, START, (flow(status='cancelled'),)).minimum_projected_balance, D('100'))

    def test_failed_ignored(self):
        self.assertFalse(prepare_forecast(indexes([event(status='failed')]), 'u', START).explicit_occurrences)
        self.assertEqual(simulate(PROFILE, START, (flow(status='failed'),)).minimum_projected_balance, D('100'))

    def test_unrealized_ignored(self):
        self.assertEqual(simulate(PROFILE, START, (flow(status='unrealized'),)).minimum_projected_balance, D('100'))

    def test_recurrence_occurrence_applied(self):
        self.assertEqual(simulate(PROFILE, START, (flow(),)).entries[0].closing_balance, D('70'))

    def test_explicit_future_event_applied(self):
        prepared = prepare_forecast(indexes([event()]), 'u', START)
        result = simulate(PROFILE, START, explicit_occurrences=prepared.explicit_occurrences)
        self.assertEqual(result.entries[2].closing_balance, D('70'))
        self.assertEqual(result.entries[0].closing_balance, D('100'))

    def test_explicit_occurrence_overrides_matching_projection(self):
        explicit = flow(source_id='known', amount=D('40'), status='scheduled', provenance='scheduled_event')
        result = simulate(PROFILE, START, (flow(),), (explicit,))
        self.assertEqual(result.entries[0].closing_balance, D('60'))
        self.assertEqual(result.entries[0].debits[0].occurrence.source_id, 'known')

    def test_no_double_counting_projection_and_scheduled_event(self):
        history = [event(event_id=f'e{m}', event_date=date(2025,m,15), settlement_date=date(2025,m,15), status='settled') for m in range(1,7)]
        known = event(event_date=date(2025,7,15), settlement_date=date(2025,7,15), amount=D('35'))
        prepared = prepare_forecast(indexes([*history, known]), 'u', START)
        result = simulate(PROFILE, START, prepared.recurring_occurrences, prepared.explicit_occurrences)
        self.assertEqual(len(result.entries[14].debits), 1)
        self.assertEqual(result.entries[14].debits[0].home_amount, D('35'))

    def test_same_day_cashflows_before_candidate(self):
        result = simulate(PROFILE, START, (flow(direction='credit', amount=D('100')),), candidate_payments=(CandidatePayment(START,D('150'),'probe'),))
        self.assertTrue(result.safe)
        self.assertEqual(result.minimum_projected_balance, D('50'))

    def test_same_day_candidate_before_cashflows(self):
        result = simulate(PROFILE, START, (flow(direction='credit', amount=D('100')),), candidate_payments=(CandidatePayment(START,D('150'),'probe'),), timing_policy=TimingPolicy(same_day_order=SameDayOrder.CANDIDATE_BEFORE_CASHFLOWS))
        self.assertFalse(result.safe)
        self.assertEqual(result.minimum_projected_balance, D('-50'))
        self.assertEqual(result.entries[0].closing_balance, D('50'))

    def test_source_row_order_does_not_change_result(self):
        flows = (flow(), flow(source_id='salary', direction='credit', amount=D('20')))
        self.assertEqual(simulate(PROFILE, START, flows), simulate(PROFILE, START, flows[::-1]))

    def test_minimum_balance_equal_is_safe(self):
        result = simulate(PROFILE, START, (flow(amount=D('80')),))
        self.assertTrue(result.safe)
        self.assertTrue(check_safety(result,D('20')))

    def test_minimum_balance_below_cent_is_unsafe(self):
        result = simulate(PROFILE, START, (flow(amount=D('80.01')),))
        self.assertFalse(result.safe)
        self.assertFalse(check_safety(result,D('20')))
        self.assertEqual(result.first_violation_date, START)

    def test_minimum_projected_balance_earliest_tie(self):
        self.assertEqual(simulate(PROFILE, START).minimum_projected_balance_date, START)

    def test_candidate_payment_interface(self):
        result = simulate(PROFILE, START, candidate_payments=(CandidatePayment(START,D('10'),'test_candidate'),))
        self.assertEqual(result.entries[0].closing_balance,D('90'))
        self.assertEqual(result.entries[0].candidate_payments[0].source,'test_candidate')

    def test_spending_change_interface(self):
        for change, expected in [(SpendingChangeEffect('s', START,'stop'),D('100')),
                                 (SpendingChangeEffect('old', START,'reduce_to',D('10')),D('90'))]:
            result = simulate(PROFILE, START, (flow(),), spending_changes=(change,))
            self.assertEqual(result.entries[0].closing_balance,expected)
            self.assertEqual(result.entries[0].spending_change_effects[0].provenance, 'spending_change')

    def test_protected_expense_included_but_modification_rejected(self):
        protected = flow(category='rent')
        self.assertEqual(simulate(PROFILE,START,(protected,)).minimum_projected_balance,D('70'))
        with self.assertRaisesRegex(ValueError,'protected'):
            simulate(PROFILE,START,(protected,),spending_changes=(SpendingChangeEffect('s',START,'stop'),))

    def test_invalid_spending_changes_rejected(self):
        for changes in [(SpendingChangeEffect('unknown',START,'stop'),),
                        (SpendingChangeEffect('s',START,'reduce_to',D('31')),),
                        (SpendingChangeEffect('s',START,'stop'),SpendingChangeEffect('s',START,'stop'))]:
            with self.assertRaises(ValueError):
                simulate(PROFILE, START, (flow(),), spending_changes=changes)
        with self.assertRaisesRegex(ValueError,'minimum_allowed_amount'):
            simulate(PROFILE,START,(flow(minimum_allowed_amount=D('15')),),spending_changes=(SpendingChangeEffect('s',START,'reduce_to',D('14')),))

    def test_simulation_deterministic(self):
        expected = simulate(PROFILE,START,(flow(amount=D('30.123456789')),))
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(simulate(PROFILE,START,(flow(amount=D('30.123456789')),)),expected)

    def test_trace_provenance(self):
        trace = json.loads(trace_json(simulate(PROFILE,START,(flow(),))))
        item = trace['entries'][0]['debits'][0]
        self.assertEqual(item['occurrence']['source_event_ids'],['old'])
        self.assertEqual(item['occurrence']['provenance'],'recurrence_projection')
        self.assertEqual(item['home_amount'],'30')

    def test_missing_amount_is_incomplete_not_zero(self):
        prepared = prepare_forecast(indexes([event(amount=None)]),'u',START)
        self.assertTrue(prepared.unresolved_sources)
        result = simulate(PROFILE,START,unresolved_sources=prepared.unresolved_sources)
        self.assertFalse(result.complete)
        self.assertFalse(result.safe)
        self.assertIsNone(result.first_violation_date)

    def test_scheduled_income_confirmation_gate(self):
        for desc, expected in [('Next confirmed salary',1),('Expected salary',0),('Possible bonus',0)]:
            prepared = prepare_forecast(indexes([event(direction='credit',event_type='income',category='salary',description=desc)]),'u',START)
            self.assertEqual(len(prepared.explicit_occurrences),expected)
        self.assertEqual(simulate(PROFILE,START,(flow(status='scheduled',direction='credit'),)).minimum_projected_balance,D('100'))

    def test_low_confidence_projection_ignored(self):
        self.assertEqual(simulate(PROFILE,START,(flow(confidence='low'),)).minimum_projected_balance,D('100'))

    def test_event_date_policy(self):
        row = event()
        default = prepare_forecast(indexes([row]),'u',START)
        alternative = prepare_forecast(indexes([row]),'u',START,TimingPolicy(future_event_date_source=FutureEventDateSource.EVENT_DATE))
        self.assertEqual(default.explicit_occurrences[0].date,START+timedelta(days=2))
        self.assertEqual(alternative.explicit_occurrences[0].date,START)
        self.assertEqual(default.explicit_occurrences[0].fx_date,alternative.explicit_occurrences[0].fx_date)

    def test_lifecycle_settlement_suppresses_pending(self):
        pending = event(status='pending', event_id='p')
        failed = event(status='failed',event_id='f',linked_event_id='p')
        settled = event(status='settled',event_id='s',linked_event_id='f')
        prepared = prepare_forecast(indexes([pending,failed,settled]),'u',START)
        self.assertEqual([f.source_id for f in prepared.explicit_occurrences],['s'])

    def test_cancelled_attempt_does_not_cancel_valid_retry(self):
        rows = [event(status='cancelled',event_id='c'),event(event_id='retry',linked_event_id='c')]
        self.assertEqual([f.source_id for f in prepare_forecast(indexes(rows),'u',START).explicit_occurrences],['retry'])

    def test_pending_cancelled_by_linked_later_notice(self):
        pending = event(status='pending',event_date=START-timedelta(days=1))
        cancellation = event(event_id='c',status='cancelled',linked_event_id='e')
        self.assertFalse(prepare_forecast(indexes([pending,cancellation]),'u',START).explicit_occurrences)

    def test_fx_exact_date_and_missing_behavior(self):
        foreign = flow(currency='EUR',fx_date=START+timedelta(days=2))
        converter = CurrencyConverter((ExchangeRate(START+timedelta(days=2),'EUR','USD',D('1.09')),))
        self.assertEqual(simulate(PROFILE,START,(foreign,),currency_converter=converter).minimum_projected_balance,D('67.30'))
        with self.assertRaises(MissingExchangeRateError):
            simulate(PROFILE,START,(replace(foreign,fx_date=None),),currency_converter=converter)

    def test_reconciliation_does_not_merge_unrelated_or_nearby_charges(self):
        explicit = flow(source_id='other',series_id=None,status='scheduled')
        self.assertEqual(len(reconcile_projected_and_explicit_occurrences((flow(),),(explicit,))),2)
        self.assertEqual(len(reconcile_projected_and_explicit_occurrences((flow(),),(replace(explicit,series_id='s',date=START+timedelta(days=1)),))),2)

    def test_invalid_money_and_cross_user_fail(self):
        with self.assertRaises(ValueError):
            CandidatePayment(START,1.0,'bad')
        with self.assertRaises(ValueError):
            flow(amount=D('NaN'))
        with self.assertRaises(ValueError):
            simulate(PROFILE,START,(flow(user_id='other'),))
        with self.assertRaises(ValueError):
            simulate(PROFILE,START,candidate_payments=(CandidatePayment(START+timedelta(days=91),D('1'),'outside'),))
        with self.assertRaises(ValueError):
            simulate(PROFILE,START,(flow(),flow()))

    def test_final_payroll_prevents_continuing_older_salary(self):
        history = [event(event_id=f'e{m}', direction='credit', event_type='income', category='salary',
            description='Employer payroll', event_date=date(2025,m,15),
            settlement_date=date(2025,m,15), status='settled') for m in range(1,6)]
        final = event(event_id='final', direction='credit', event_type='income', category='salary',
            description='Final employer payroll', event_date=date(2025,6,15),
            settlement_date=date(2025,6,15), status='settled')
        before = prepare_forecast(indexes(history),'u',START)
        after = prepare_forecast(indexes([*history,final]),'u',START)
        self.assertTrue(before.recurring_occurrences)
        self.assertFalse(after.recurring_occurrences)
        self.assertTrue(any('final payroll' in d for d in after.diagnostics))

    def test_old_scheduled_credit_is_not_moved_to_today(self):
        old = event(direction='credit',event_type='income',category='salary',description='Next confirmed salary',
                    event_date=START-timedelta(days=3),settlement_date=START-timedelta(days=2))
        self.assertFalse(prepare_forecast(indexes([old]),'u',START).explicit_occurrences)

    def test_multiple_pending_attempts_resolved_by_one_settlement(self):
        rows = [event(event_id='p1',status='pending'), event(event_id='p2',status='pending',linked_event_id='p1'),
                event(event_id='settled',status='settled',linked_event_id='p2')]
        prepared=prepare_forecast(indexes(rows),'u',START)
        self.assertEqual([f.source_id for f in prepared.explicit_occurrences],['settled'])
        self.assertFalse(prepared.unresolved_sources)

    def test_ambiguous_active_lifecycle_is_incomplete(self):
        rows = [event(event_id='a',status='pending'),event(event_id='b',status='pending',linked_event_id='a')]
        prepared=prepare_forecast(indexes(rows),'u',START)
        self.assertTrue(prepared.unresolved_sources)
        self.assertEqual(len(prepared.explicit_occurrences),2)

    def test_change_effective_date_and_currency_are_respected(self):
        later=START+timedelta(days=1)
        flows=(flow(),flow(date=later))
        result=simulate(PROFILE,START,flows,spending_changes=(SpendingChangeEffect('s',later,'stop'),))
        self.assertEqual(result.entries[0].closing_balance,D('70'))
        self.assertEqual(result.entries[1].closing_balance,D('70'))
        self.assertFalse(result.entries[0].spending_change_effects)

    def test_missing_profile_money_fails(self):
        for name in ('current_available_balance','minimum_balance_to_keep'):
            with self.assertRaises(ValueError):
                simulate(replace(PROFILE,**{name:None}),START)

    def test_all_samples_prepared_without_missing_fx(self):
        data=dataset()
        ix=build_indexes(data)
        converter=CurrencyConverter(data.exchange_rates)
        incomplete=[]
        for request in data.sample_requests:
            prepared=prepare_forecast(ix,request.user_id,request.request_date)
            result=simulate(ix.profile_by_user_id[request.user_id],request.request_date,
                prepared.recurring_occurrences,prepared.explicit_occurrences,
                currency_converter=converter,unresolved_sources=prepared.unresolved_sources)
            self.assertEqual(len(result.entries),91)
            if not result.complete:
                incomplete.append(request.request_id)
        self.assertEqual(incomplete,['request_16','request_20'])
