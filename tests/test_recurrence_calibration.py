import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from evaluation.calibrate_recurrence import candidate_policies, compare_projections, flow_signature
from evaluation.recurrence_backtest import backtest_history, summarize_folds
from src.data.currency import CurrencyConverter
from src.forecast.recurrence import project_recurring_series
from tests.test_recurrence import POLICY, monthly, single_series


class CalibrationTests(unittest.TestCase):
    def test_holdout_backtest_no_leakage(self):
        history = monthly(['100', '100', '100', '100', '100', '100'])
        folds, counts = backtest_history(history, date(2025, 6, 16), POLICY)
        changed = (*history[:-1], replace(history[-1], amount=Decimal('99999'), settlement_date=date(2025, 6, 20)))
        other, _ = backtest_history(changed, date(2025, 6, 21), POLICY)
        original, new = folds[-1], other[-1]
        self.assertEqual(original.predicted_amount, new.predicted_amount)
        self.assertEqual(original.predicted_date, new.predicted_date)
        self.assertNotEqual(original.actual_amount, new.actual_amount)
        self.assertNotIn(original.target_event_id, original.training_event_ids)
        self.assertLess(original.as_of, original.actual_date)
        self.assertEqual(counts['eligible_series'], 1)
        self.assertEqual(len(folds), 3)

    def test_backtest_uses_prefix_not_future_lifecycle(self):
        history = monthly()
        future = replace(history[-1], event_id='reversal', event_type='refund', direction='credit',
                         event_date=date(2025, 7, 1), settlement_date=date(2025, 7, 1), linked_event_id=history[0].event_id)
        a, _ = backtest_history(history, date(2025, 8, 1), POLICY)
        b, _ = backtest_history((*history, future), date(2025, 8, 1), POLICY)
        self.assertEqual(a, b)

    def test_backtest_covers_abstentions(self):
        history = monthly()
        history = (*history[:3], replace(history[3], event_date=date(2025, 4, 22), settlement_date=date(2025, 4, 22)), *history[4:])
        folds, _ = backtest_history(history, date(2025, 6, 16), replace(POLICY, thresholds=replace(POLICY.thresholds, maximum_interval_deviation=Decimal('0.10'))))
        summary = summarize_folds(folds)
        self.assertGreater(summary['abstained'], 0)
        self.assertEqual(summary['predicted']+summary['abstained'], summary['folds'])

    def test_candidate_list_is_small_and_one_factor(self):
        policies = candidate_policies()
        self.assertEqual(len(policies), 12)
        self.assertEqual(len({p.policy_id for p in policies}), 12)
        for p in policies[1:]:
            self.assertEqual(sum(getattr(p, key) != getattr(policies[0], key) for key in
                ['identity_method', 'cadence_method', 'amount_method', 'spend_rate_method']), 1)

    def test_missing_fx_is_not_zero_or_fallback_rate(self):
        series = single_series(monthly())
        usd = project_recurring_series(series, date(2025, 7, 1), date(2025, 7, 31))
        eur = tuple(replace(o, currency='EUR') for o in usd)
        result = compare_projections(usd, eur, 'USD', CurrencyConverter([]))
        self.assertTrue(result['missing_fx'])
        self.assertEqual(result['total_difference_home_currency'], Decimal('100'))

    def test_signature_ignores_series_ids_but_preserves_dates(self):
        series = single_series(monthly())
        projected = project_recurring_series(series, date(2025, 7, 1), date(2025, 7, 31))
        renamed = tuple(replace(o, source_series_id='renamed') for o in projected)
        self.assertEqual(flow_signature(projected), flow_signature(renamed))
        moved = tuple(replace(o, date=date(2025, 7, 16)) for o in projected)
        result = compare_projections(projected, moved, 'USD', CurrencyConverter([]))
        self.assertTrue(result['changed'])
        self.assertEqual(result['total_difference_home_currency'], 0)
