import csv
import os
import tempfile
import unittest
from dataclasses import fields, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from src.config import dataset_root
from src.data.audit import build_audit, payment_option_cadence
from src.data.indexes import build_indexes
from src.data.loader import (MODEL_FILES, OUTPUT_COLUMNS, DataValidationError,
                             _load, load_requests, load_output_template)
from src.data.parsers import parse_bool, parse_collection, parse_money
from tests.fixtures import dataset


class DataLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset()

    def test_dataset_files_exist(self):
        for filename in MODEL_FILES:
            self.assertTrue((self.data.root / filename).is_file(), filename)

    def test_expected_columns(self):
        for filename, model in MODEL_FILES.items():
            with (self.data.root / filename).open() as handle:
                header = next(csv.reader(handle))
            self.assertTrue({f.name for f in fields(model)} - {'raw'} <= set(header))
            with self.subTest(file=filename), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, filename).write_text(','.join(header[1:]) + '\n')
                with self.assertRaisesRegex(DataValidationError, 'missing required columns'):
                    _load(tmp, filename, model)

    def test_request_ids_unique(self):
        ids = [r.request_id for r in (*self.data.requests, *self.data.sample_requests)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_output_template_shape(self):
        self.assertEqual(len(self.data.requests), len(self.data.output_template))
        self.assertEqual({r.request_id for r in self.data.requests}, {r.request_id for r in self.data.output_template})
        self.assertTrue(all(all(not v for k, v in row.raw.items() if k != 'request_id') for row in self.data.output_template))
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'output.csv').write_text(','.join(reversed(OUTPUT_COLUMNS)) + '\n')
            with self.assertRaisesRegex(DataValidationError, 'exact order'):
                load_output_template(tmp)

    def test_decimal_money(self):
        self.assertEqual(parse_money('12.30'), Decimal('12.30'))
        groups = [(self.data.requests, ['requested_amount']),
                  (self.data.sample_requests, ['requested_amount', 'amount_safe_to_pay']),
                  (self.data.profiles, ['current_available_balance', 'minimum_balance_to_keep']),
                  (self.data.events, ['amount', 'minimum_allowed_amount']),
                  (self.data.payment_options, ['payment_amount', 'financing_fee', 'total_payable_amount']),
                  (self.data.exchange_rates, ['rate'])]
        for rows, names in groups:
            for row in rows:
                for name in names:
                    self.assertTrue(getattr(row, name) is None or isinstance(getattr(row, name), Decimal))

    def test_blank_money_is_none(self):
        self.assertIsNone(parse_money('  '))
        blank = [e for e in self.data.events if not e.raw['amount']]
        self.assertEqual(len(blank), 16)
        self.assertTrue(all(e.amount is None for e in blank))

    def test_zero_money_is_decimal_zero(self):
        self.assertEqual(parse_money('0'), Decimal('0'))
        self.assertIsInstance(parse_money('0'), Decimal)

    def test_malformed_money_rejected(self):
        for value in ['NaN', 'Infinity', 'abc', '1,234', '1_000', '1e3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_money(value)

    def test_profile_collection_parsing(self):
        self.assertEqual(parse_collection(' rent | education | rent '), ('rent', 'education'))
        self.assertEqual(parse_collection(''), ())
        with self.assertRaises(ValueError):
            parse_collection('rent||education')
        p = self.data.profiles[0]
        self.assertIsInstance(p.financial_priorities, tuple)
        self.assertIsInstance(p.expense_categories_to_protect, frozenset)
        self.assertEqual(p.raw['expense_categories_to_protect'], 'rent|education|groceries|debt_repayment')
        with self.assertRaises(TypeError):
            p.raw['user_id'] = 'changed'

    def test_dates_booleans_and_missing_values(self):
        self.assertIsInstance(self.data.requests[0].request_date, date)
        self.assertIsInstance(self.data.messages[0].sent_at, datetime)
        self.assertTrue(parse_bool('TRUE'))
        self.assertFalse(parse_bool('false'))
        with self.assertRaises(ValueError):
            parse_bool('maybe')
        self.assertIsNone(self.data.messages[0].related_event_id)

    def _write_requests(self, root, rows):
        with Path(root, 'requests.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.data.requests[0].raw))
            writer.writeheader()
            writer.writerows(rows)

    def test_duplicate_and_malformed_rows_fail_clearly(self):
        base = dict(self.data.requests[0].raw)
        variants = [([base, base], 'duplicate key'),
                    ([dict(base, requested_amount='oops')], 'column requested_amount'),
                    ([dict(base, request_id='')], 'column request_id'),
                    ([dict(base, request_id='../escape')], 'column request_id'),
                    ([dict(base, request_date='2026-99-01')], 'column request_date')]
        for rows, error in variants:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                self._write_requests(tmp, rows)
                with self.assertRaisesRegex(DataValidationError, error):
                    load_requests(tmp)

    def test_bad_row_width_and_duplicate_headers(self):
        for header, row, expected in [
            (','.join(self.data.requests[0].raw), 'one,two', 'row width'),
            (','.join(self.data.requests[0].raw) + ',request_id', '', 'duplicate column'),
        ]:
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, 'requests.csv').write_text(header + '\n' + row + '\n')
                with self.assertRaisesRegex(DataValidationError, expected):
                    load_requests(tmp)

    def test_missing_file_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DataValidationError, 'requests.csv'):
                load_requests(tmp)

    def test_configurable_root(self):
        with patch.dict(os.environ, {'DATASET_ROOT': '/tmp/from-env'}):
            self.assertEqual(dataset_root(), Path('/tmp/from-env'))
            self.assertEqual(dataset_root('/tmp/explicit'), Path('/tmp/explicit'))

    def test_indexes_cover_major_lookup_paths(self):
        idx = build_indexes(self.data)
        self.assertEqual(len(idx.requests_by_request_id), 275)
        for r in (*self.data.requests, *self.data.sample_requests):
            self.assertIn(r, idx.requests_by_user_id[r.user_id])
            self.assertIn(r.user_id, idx.profile_by_user_id)
        for e in self.data.events:
            self.assertEqual(idx.events_by_event_id[e.event_id], e)
            self.assertIn(e, idx.events_by_user_id[e.user_id])
        for m in self.data.messages:
            self.assertEqual(idx.messages_by_message_id[m.message_id], m)
            self.assertIn(m, idx.messages_by_user_id[m.user_id])
        for i in self.data.images:
            self.assertEqual(idx.images_by_image_id[i.image_id], i)
            self.assertIn(i, idx.images_by_user_id[i.user_id])
            self.assertIn(i, idx.images_by_related_event_id[i.related_event_id])
        for p in self.data.payment_options:
            self.assertIn(p, idx.payment_options_by_request_id[p.request_id])

    def test_unknown_and_cross_user_references(self):
        bad = [replace(self.data, events=(replace(self.data.events[0], user_id='unknown'),)),
               replace(self.data, payment_options=(replace(self.data.payment_options[0], request_id='unknown'),)),
               replace(self.data, images=(replace(self.data.images[0], related_event_id='unknown'),)),
               replace(self.data, images=(replace(self.data.images[0], user_id=self.data.profiles[0].user_id),))]
        for data in bad:
            with self.assertRaises(DataValidationError):
                build_indexes(data)

    def test_payment_option_cadence_dataset_invariant(self):
        self.assertEqual(payment_option_cadence(self.data), {
            'payment_option_count': 790, 'installment_count': 515,
            'installment_frequencies': [28, 30, 31]})

    def test_audit_reproducible_and_missing_image_reported(self):
        self.assertEqual(build_audit(self.data), build_audit(self.data))
        report = build_audit(replace(self.data, root=Path('/nonexistent-phase1-images')))
        self.assertEqual(report['image_files_present'], 0)
        self.assertEqual(len(report['missing_image_ids']), 16)
