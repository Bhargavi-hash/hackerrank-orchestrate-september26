import unittest
from dataclasses import replace
from src.models.event import is_cash_event
from src.planning.spending_changes import can_reduce, can_stop
from tests.fixtures import dataset


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.event = replace(dataset().events[0], category='dining')
        self.profile = replace(dataset().profiles[0], expense_categories_to_protect=frozenset(),
                               expense_categories_user_is_willing_to_stop=frozenset({'dining'}),
                               expense_categories_user_is_willing_to_reduce=frozenset({'dining'}))

    def test_non_cash_exclusion(self):
        for status in ['settled', 'pending', 'scheduled', 'unrealized', 'failed', 'cancelled']:
            for event_type in ['investment_valuation', 'income']:
                self.assertFalse(is_cash_event(replace(self.event, direction='non_cash', status=status, event_type=event_type)))
        for event in dataset().events:
            if event.direction == 'non_cash':
                self.assertFalse(is_cash_event(event))
        self.assertTrue(is_cash_event(replace(self.event, direction='debit')))
        self.assertTrue(is_cash_event(replace(self.event, direction='credit')))
        with self.assertRaises(ValueError):
            is_cash_event(replace(self.event, direction='unknown'))

    def test_protected_category_precedence(self):
        profile = replace(self.profile, expense_categories_to_protect=frozenset({'dining'}))
        event = replace(self.event, flexibility='reducible_or_stoppable')
        self.assertFalse(can_stop(event, profile))
        self.assertFalse(can_reduce(event, profile))

    def test_can_stop(self):
        for flexibility in ['fixed', 'reducible', 'stoppable', 'reducible_or_stoppable']:
            self.assertEqual(can_stop(replace(self.event, flexibility=flexibility), self.profile), flexibility in {'stoppable', 'reducible_or_stoppable'})
        self.assertFalse(can_stop(replace(self.event, category='rent', flexibility='stoppable'), self.profile))

    def test_can_reduce(self):
        for flexibility in ['fixed', 'reducible', 'stoppable', 'reducible_or_stoppable']:
            self.assertEqual(can_reduce(replace(self.event, flexibility=flexibility), self.profile), flexibility in {'reducible', 'reducible_or_stoppable'})
        self.assertFalse(can_reduce(replace(self.event, category='rent', flexibility='reducible'), self.profile))

    def test_priorities_context_only(self):
        event = replace(self.event, flexibility='reducible_or_stoppable')
        other = replace(self.profile, financial_priorities=('different_priority',))
        self.assertEqual(can_stop(event, self.profile), can_stop(event, other))
        self.assertEqual(can_reduce(event, self.profile), can_reduce(event, other))

    def test_user_mismatch_rejected(self):
        event = replace(self.event, user_id='other', flexibility='reducible_or_stoppable')
        self.assertFalse(can_stop(event, self.profile))
        self.assertFalse(can_reduce(event, self.profile))
