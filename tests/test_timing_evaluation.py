import json
from pathlib import Path
import unittest

from evaluation.run_timing_experiments import evaluate, json_text, labeled_probes, report
from fixtures import dataset


class TimingEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact,cls.baselines=evaluate(dataset())

    def test_all_samples_have_diagnostics(self):
        self.assertEqual({r.request_id for r in dataset().sample_requests},
                         {r['request_id'] for r in self.baselines})
        self.assertEqual(sum(not r['complete_for_supplied_structured_inputs'] for r in self.baselines),2)

    def test_supplied_probes_preserve_label_amounts_dates(self):
        request=dataset().sample_requests[1]
        probes=labeled_probes(request)
        text='|'.join(f'{p.date}:{p.amount}' for p in probes['supplied_plan'])
        self.assertEqual(text,request.payment_plan)
        self.assertEqual(probes['supplied_full_payment_date'][0].date,request.earliest_date_for_full_payment)
        self.assertEqual(probes['supplied_full_payment_date'][0].amount,request.requested_amount)

    def test_same_day_closings_equal_and_safety_differences_disclosed(self):
        same=self.artifact['same_day']
        sensitive={c['request_id'] for c in same['cases'] if c['difference']['safety_differs']}
        self.assertEqual(len(sensitive),same['conditional_safety_flip_count'])
        self.assertEqual(sensitive,set(same['conditional_safety_flip_request_ids']))
        self.assertTrue(all(c['difference']['max_daily_closing_balance_difference']==0 for c in same['cases']))
        self.assertEqual(same['conditionally_supporting_request_ids'],
                         ['request_04','request_18','request_22','request_23'])

    def test_event_timing_does_not_claim_label_winner(self):
        event=self.artifact['event_date']
        self.assertEqual(event['visible_future_events_with_different_dates'],12)
        self.assertEqual(event['numerically_sensitive_count'],9)
        self.assertEqual(event['conditional_label_probe_safety_flip_count'],0)
        self.assertIn('not disambiguated',event['strength_of_evidence'])

    def test_fx_coverage_measured_from_supplied_rows(self):
        fx=self.artifact['fx']
        self.assertEqual(sum(p['row_count'] for p in fx['date_coverage']),len(dataset().exchange_rates))
        self.assertEqual(fx['sample_users_requiring_future_fx'],['request_25'])
        self.assertEqual(fx['missing_exact_sample_rates'],0)

    def test_artifacts_reproducible(self):
        root=Path(__file__).resolve().parents[1]/'evaluation'
        saved=json.loads((root/'phase3_timing_experiments.json').read_text())
        saved.pop('input_sha256')
        self.assertEqual(json_text(self.artifact),json_text(saved))
        self.assertEqual(json_text(self.baselines),(root/'phase3_simulation_diagnostics.json').read_text())
        self.assertEqual(report(self.artifact,self.baselines),(root/'phase3_timing_report.md').read_text())
