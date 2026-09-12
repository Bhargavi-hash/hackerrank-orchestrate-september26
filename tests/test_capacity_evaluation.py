import csv
import json
from pathlib import Path
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from evaluation.evaluate_capacity import (evaluate_samples, summarize, compare_estimators,
    json_text, write_artifacts, COLUMNS)
from tests.fixtures import dataset

D=Decimal


def metric_row(identity='r',currency='USD',error='1',predicted=date(2025,1,2),expected=date(2025,1,1)):
    return {'request_id':identity,'currency':currency,'safe_amount_abs_error':D(error),
        'safe_amount_relative_error':D(error)/D('10'),
        'safe_amount_error_over_requested_amount':D(error)/D('100'),
        'predicted_earliest_date':predicted,'expected_earliest_date':expected,
        'earliest_date_error_days':abs((predicted-expected).days) if predicted and expected else None}


class CapacityEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,cls.details=evaluate_samples(dataset())

    def test_capacity_evaluation_runs_all_25_samples(self):
        expected={r.request_id for r in dataset().sample_requests}
        self.assertEqual({r['request_id'] for r in self.rows},expected)
        for summary in self.details['metrics_by_estimator'].values():
            self.assertEqual(summary['sample_count'],len(expected))
        for detail in self.details['requests'].values():
            result=detail['result']
            if result['amount_safe_to_pay']>0:
                self.assertTrue(result['safe_amount_verified'])
            if result['next_cent_probe'] is not None:
                self.assertFalse(result['next_cent_probe']['safe'])
            probes=result['full_payment_probes']
            self.assertLessEqual(len(probes),91)
            if result['earliest_date_for_full_payment'] is not None:
                self.assertTrue(probes[-1]['safe'])
                self.assertTrue(all(not p['safe'] for p in probes[:-1]))

    def test_capacity_artifact_contains_all_sample_requests(self):
        root=Path(__file__).resolve().parents[1]/'evaluation'
        with (root/'phase4_capacity_results.csv').open() as handle:
            reader=csv.DictReader(handle)
            saved=list(reader)
            self.assertEqual(tuple(reader.fieldnames),COLUMNS)
        self.assertEqual({r['request_id'] for r in saved},{r.request_id for r in dataset().sample_requests})
        for written,row in zip(saved,self.rows):
            self.assertEqual(D(written['predicted_safe_amount']),row['predicted_safe_amount'])
            self.assertEqual(written['predicted_earliest_date'],str(row['predicted_earliest_date'] or ''))

    def test_financial_artifacts_reproduce_excluding_runtime(self):
        root=Path(__file__).resolve().parents[1]/'evaluation'
        saved=json.loads((root/'phase4_capacity_details.json').read_text())
        calculated=json.loads(json_text(self.details))
        saved.pop('input_sha256')
        saved.pop('performance')
        calculated.pop('performance')
        self.assertEqual(saved,calculated)
        with tempfile.TemporaryDirectory() as folder:
            write_artifacts(Path(folder),self.rows,self.details)
            self.assertEqual((Path(folder)/'phase4_capacity_results.csv').read_text(),
                             (root/'phase4_capacity_results.csv').read_text())
            self.assertFalse((Path(folder)/'output.csv').exists())

    def test_prior_baseline_forecasts_preserved(self):
        root=Path(__file__).resolve().parents[1]/'evaluation'
        for row in json.loads((root/'phase3_simulation_diagnostics.json').read_text()):
            self.assertEqual(self.details['requests'][row['request_id']]['baseline_minimum_balance'],
                             D(row['minimum_projected_balance']))

    def test_currency_metrics_never_pool_native_errors(self):
        stats=summarize([metric_row(currency='USD',error='1'),metric_row('other','INR','100')])
        self.assertEqual(stats['safe_amount_error_by_currency']['USD']['mae'],D('1'))
        self.assertEqual(stats['safe_amount_error_by_currency']['INR']['mae'],D('100'))
        self.assertNotIn('safe_amount_mae',stats)

    def test_date_missing_and_tolerance_denominators(self):
        rows=[metric_row(),metric_row('missing',predicted=None),
              metric_row('both',predicted=None,expected=None)]
        stats=summarize(rows)
        self.assertEqual(stats['earliest_date_exact_matches'],1)
        self.assertEqual(stats['earliest_date_both_missing'],1)
        self.assertEqual(stats['earliest_date_present_pair_count'],1)
        self.assertEqual(stats['earliest_date_within_1_day_present_pairs'],1)
        self.assertEqual(stats['earliest_date_missing_present_mismatches'],1)
        self.assertEqual(stats['earliest_date_median_absolute_error_days'],1)
        missing=summarize([metric_row(predicted=None)])
        self.assertIsNone(missing['earliest_date_median_absolute_error_days'])

    def test_zero_label_relative_error_is_not_divided(self):
        row=metric_row()
        row['safe_amount_relative_error']=None
        stats=summarize([row])
        self.assertEqual(stats['relative_error_count'],0)
        self.assertIsNone(stats['safe_amount_median_relative_error'])

    def test_estimator_tradeoffs_are_not_hidden(self):
        old=metric_row(error='1',predicted=date(2025,1,10))
        new=metric_row(error='2',predicted=date(2025,1,1))
        changes=compare_estimators([old],[new])
        self.assertEqual(changes['tradeoff']['count'],1)
        self.assertEqual(changes['safe_worsened']['count'],1)
        self.assertEqual(changes['date_improved']['count'],1)

    def test_every_mismatch_has_evaluation_only_context(self):
        for row in self.rows:
            if row['safe_amount_abs_error'] or row['predicted_earliest_date']!=row['expected_earliest_date']:
                self.assertNotEqual(row['likely_mismatch_cause'],'none')
                self.assertTrue(row['notes'])
        self.assertEqual(self.details['selected_default_unchanged'],'mean_last_5')
