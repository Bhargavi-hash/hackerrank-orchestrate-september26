import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

from src.forecast.recurrence import (description_family, estimate_amount,
    infer_recurring_series, is_recurrence_evidence, normalize_description,
    prepare_history, project_recurring_series, recurrence_identity)
from src.forecast.recurrence_models import (ConfidenceThresholds, RecurrenceConfidence,
    RecurrencePolicy)
from src.models.event import FinancialEvent


POLICY = RecurrencePolicy()


def events_on(dates, amounts=None, **changes):
    amounts = amounts or [Decimal('100')] * len(dates)
    return tuple(replace(FinancialEvent(
        f'event_{i}', 'user_test', 'expense', 'Monthly rent', 'rent', 'debit',
        Decimal(str(amount)), 'USD', day, day, 'settled', None, 'fixed', None), **changes)
        for i, (day, amount) in enumerate(zip(dates, amounts)))


def monthly(amounts=None, **changes):
    return events_on([date(2025, month, 15) for month in range(1, 7)], amounts, **changes)


def single_series(events, as_of=date(2025, 6, 16), policy=POLICY):
    return infer_recurring_series(events, as_of, policy).series[0]


class RecurrenceTests(unittest.TestCase):
    def test_fixed_monthly_recurrence(self):
        series = single_series(monthly())
        self.assertTrue(series.is_recurring)
        self.assertEqual(series.cadence.model, 'calendar_month')
        self.assertIsNone(series.cadence.days)
        projected = project_recurring_series(series, date(2025, 6, 16), date(2025, 9, 15))
        self.assertEqual([o.date for o in projected], [date(2025, 7, 15), date(2025, 8, 15), date(2025, 9, 15)])

    def test_calendar_month_end_recurrence(self):
        history = events_on([date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)])
        series = single_series(history, date(2024, 4, 1))
        self.assertTrue(series.cadence.month_end)
        self.assertEqual([o.date for o in project_recurring_series(series, date(2024, 4, 1), date(2024, 6, 30))],
                         [date(2024, 4, 30), date(2024, 5, 31), date(2024, 6, 30)])

    def test_calendar_clamped_day_and_year_boundary(self):
        history = events_on([date(2024, 12, 30), date(2025, 1, 30), date(2025, 2, 28)])
        series = single_series(history, date(2025, 3, 1))
        self.assertFalse(series.cadence.month_end)
        self.assertEqual(project_recurring_series(series, date(2025, 3, 1), date(2025, 4, 30))[0].date, date(2025, 3, 30))

    def test_fixed_day_recurrence(self):
        history = events_on([date(2025, 1, 1) + timedelta(days=7*i) for i in range(6)])
        series = single_series(history, date(2025, 2, 6))
        self.assertEqual(series.cadence.days, 7)
        self.assertEqual(project_recurring_series(series, date(2025, 2, 6), date(2025, 2, 12))[0].date, date(2025, 2, 12))

    def test_variable_amount_latest(self):
        self.assertEqual(estimate_amount(tuple(map(Decimal, ['2', '7', '12'])), 'latest'), Decimal('12.00'))

    def test_variable_amount_mean_last_3(self):
        self.assertEqual(estimate_amount(tuple(map(Decimal, ['999', '1', '2', '7'])), 'mean_last_3'), Decimal('3.33'))

    def test_variable_amount_median_last_3(self):
        self.assertEqual(estimate_amount(tuple(map(Decimal, ['999', '1', '2', '7'])), 'median_last_3'), Decimal('2.00'))

    def test_five_observation_and_conservative_estimators(self):
        amounts = tuple(map(Decimal, ['999', '1', '2', '3', '4', '10']))
        self.assertEqual(estimate_amount(amounts, 'mean_last_5'), Decimal('4.00'))
        self.assertEqual(estimate_amount(amounts, 'median_last_5'), Decimal('3.00'))
        self.assertEqual(estimate_amount(amounts, 'max_last_3'), Decimal('10.00'))

    def test_rounding_and_context_independence(self):
        amounts = (Decimal('123.445'),)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(estimate_amount(amounts, 'latest'), Decimal('123.45'))
            self.assertEqual(single_series(monthly()).confidence, RecurrenceConfidence.HIGH)

    def test_one_off_not_recurring(self):
        series = single_series(events_on([date(2025, 5, 1), date(2025, 5, 31)], category='electronics', description='Laptop purchase'), date(2025, 6, 1))
        self.assertFalse(series.is_recurring)
        self.assertEqual(project_recurring_series(series, date(2025, 6, 1), date(2025, 12, 31)), ())

    def test_non_cash_not_recurrence_evidence(self):
        self.assertFalse(is_recurrence_evidence(replace(monthly()[0], direction='non_cash'), date(2026, 1, 1)))

    def test_cancelled_not_recurrence_evidence(self):
        self.assertFalse(is_recurrence_evidence(replace(monthly()[0], status='cancelled'), date(2026, 1, 1)))

    def test_failed_not_recurrence_evidence(self):
        self.assertFalse(is_recurrence_evidence(replace(monthly()[0], status='failed'), date(2026, 1, 1)))

    def test_pending_scheduled_unrealized_missing_amount_excluded(self):
        for status in ['pending', 'scheduled', 'unrealized']:
            self.assertFalse(is_recurrence_evidence(replace(monthly()[0], status=status), date(2026, 1, 1)))
        result = infer_recurring_series((replace(monthly()[0], amount=None),), date(2026, 1, 1))
        self.assertEqual(result.series, ())
        self.assertEqual(result.history_diagnostics[0].reason, 'missing_amount')

    def test_known_historical_dates_required(self):
        e = monthly()[0]
        self.assertFalse(is_recurrence_evidence(e, e.event_date))
        self.assertFalse(is_recurrence_evidence(replace(e, settlement_date=date(2025, 7, 1)), date(2025, 6, 1)))
        self.assertFalse(is_recurrence_evidence(replace(e, settlement_date=None), date(2025, 6, 1)))

    def test_linked_lifecycle_not_double_counted(self):
        one = monthly()[0]
        failed = replace(one, event_id='failed', status='failed')
        settled = replace(one, event_id='settled', linked_event_id='failed')
        kept, _ = prepare_history((failed, settled), date(2025, 2, 1))
        self.assertEqual([e.event_id for e in kept], ['settled'])
        duplicate = replace(settled, event_id='duplicate', linked_event_id='settled')
        kept, diagnostics = prepare_history((failed, settled, duplicate), date(2025, 2, 1))
        self.assertEqual(kept, ())
        self.assertIn('ambiguous_linked_settlements_excluded', [d.reason for d in diagnostics])

    def test_future_reversal_cannot_change_history_snapshot(self):
        historical = monthly()
        future = replace(historical[-1], event_id='future_reversal', event_type='refund', direction='credit',
                         event_date=date(2025, 7, 1), settlement_date=date(2025, 7, 1), linked_event_id=historical[-1].event_id)
        self.assertEqual(infer_recurring_series(historical, date(2025, 6, 16)).series,
                         infer_recurring_series((*historical, future), date(2025, 6, 16)).series)

    def test_recurrence_confidence_high(self):
        series = single_series(monthly())
        self.assertEqual(series.confidence, RecurrenceConfidence.HIGH)
        self.assertEqual(series.diagnostics.maximum_interval_deviation, Decimal(0))
        self.assertEqual(series.diagnostics.amount_cv, Decimal(0))

    def test_recurrence_confidence_low(self):
        dates = [date(2025, 1, 1) + timedelta(days=d) for d in [0, 2, 31, 35, 90]]
        self.assertEqual(single_series(events_on(dates), date(2025, 4, 2)).confidence, RecurrenceConfidence.LOW)

    def test_stale_history_rejected(self):
        self.assertFalse(single_series(monthly(), date(2026, 1, 1)).is_recurring)

    def test_projection_deterministic(self):
        history = monthly()
        first = single_series(history)
        second = single_series(tuple(reversed(history)))
        self.assertEqual(first, second)
        self.assertEqual(project_recurring_series(first, date(2025, 6, 16), date(2025, 8, 15)),
                         project_recurring_series(second, date(2025, 6, 16), date(2025, 8, 15)))

    def test_projection_window_bounds(self):
        series = single_series(monthly())
        self.assertEqual(len(project_recurring_series(series, date(2025, 7, 15), date(2025, 7, 15))), 1)
        self.assertEqual(project_recurring_series(series, date(2025, 7, 16), date(2025, 8, 14)), ())
        with self.assertRaises(ValueError):
            project_recurring_series(series, date(2025, 1, 1), date(2025, 8, 1))
        with self.assertRaises(ValueError):
            project_recurring_series(series, date(2025, 8, 1), date(2025, 7, 1))
        with self.assertRaises(ValueError):
            project_recurring_series(series, date(2025, 7, 1), date(2025, 8, 1), replace(POLICY, amount_method='latest'))

    def test_description_normalization(self):
        self.assertEqual(normalize_description('  ACME, Store #42!  '), 'acme store 42')
        self.assertNotEqual(normalize_description('Acme 42'), normalize_description('Acme 43'))

    def test_grouping_strategy_difference(self):
        history = tuple(replace(e, category='groceries', description='Supermarket' if i%2 else 'Local market') for i, e in enumerate(monthly()))
        category = infer_recurring_series(history, date(2025, 6, 16), POLICY)
        exact = infer_recurring_series(history, date(2025, 6, 16), replace(POLICY, identity_method='exact'))
        family = infer_recurring_series(history, date(2025, 6, 16), replace(POLICY, identity_method='family'))
        self.assertEqual(len(category.series), 1)
        self.assertEqual(len(exact.series), 2)
        self.assertEqual(len(family.series), 1)
        airfare = replace(history[0], category='transport', description='Airline ticket purchase')
        self.assertEqual(description_family(airfare), 'airline ticket purchase')

    def test_currency_partitions_identity(self):
        a = monthly()[0]
        for method in ['exact', 'category', 'family']:
            self.assertNotEqual(recurrence_identity(a, method), recurrence_identity(replace(a, currency='EUR'), method))

    def test_income_is_source_prediction_only(self):
        history = monthly(event_type='income', category='salary', direction='credit', description='Payroll credit')
        series = single_series(history)
        projected = project_recurring_series(series, date(2025, 7, 1), date(2025, 7, 31))
        self.assertIn('not_confirmation', projected[0].provenance)
        for description in ['Quarterly performance bonus', 'Monthly sales commission', 'Prize proceeds', 'Final employer payroll', 'Prorated first salary']:
            self.assertFalse(is_recurrence_evidence(replace(history[0], description=description), date(2025, 7, 1)))
        self.assertFalse(is_recurrence_evidence(replace(history[0], event_type='refund'), date(2025, 7, 1)))

    def test_same_day_and_mixed_income_identity_abstain(self):
        history = monthly(event_type='income', category='salary', direction='credit', description='Payroll credit')
        mixed = (*history[:-1], replace(history[-1], description='Other employer salary'))
        self.assertFalse(single_series(mixed).is_recurring)
        same_day = (*history, replace(history[-1], event_id='duplicate_day'))
        self.assertFalse(single_series(same_day).is_recurring)

    def test_rolling_spend_rate_and_fallback(self):
        dates = [date(2025, 1, 1)+timedelta(days=7*i) for i in range(6)]
        history = events_on(dates, ['10', '20', '30', '40', '50', '60'], category='groceries')
        series = single_series(history, dates[-1]+timedelta(days=1), replace(POLICY, spend_rate_method='rolling_28'))
        self.assertEqual(series.projected_amount, Decimal('45.00'))
        short = single_series(history[:3], dates[2]+timedelta(days=1), replace(POLICY, spend_rate_method='rolling_28'))
        self.assertIn('rolling_28_insufficient_span_fallback', short.diagnostics.reasons)

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            RecurrencePolicy(amount_method='made_up')
        with self.assertRaises(ValueError):
            ConfidenceThresholds(minimum_observations=2)
