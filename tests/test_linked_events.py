import unittest
from dataclasses import replace
from src.data.indexes import build_indexes
from src.data.loader import DataValidationError
from src.evidence.resolver import resolve_linked_component
from tests.fixtures import dataset


class LinkedEventsTests(unittest.TestCase):
    def indexes(self, links):
        event = dataset().events[0]
        events = tuple(replace(event, event_id=key, linked_event_id=link) for key, link in links)
        return build_indexes(replace(dataset(), events=events, messages=(), images=()))

    def ids(self, key, indexes):
        return [e.event_id for e in resolve_linked_component(key, indexes)]

    def test_linked_event_multihop(self):
        idx = self.indexes([('a', None), ('b', 'a'), ('c', 'b'), ('d', 'c'), ('e', 'b'), ('isolated', None)])
        for key in ['a', 'c', 'e']:
            self.assertEqual(self.ids(key, idx), ['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(self.ids('isolated', idx), ['isolated'])

    def test_linked_event_cycle_guard(self):
        idx = self.indexes([('a', 'c'), ('b', 'a'), ('c', 'b')])
        self.assertEqual(self.ids('b', idx), ['a', 'b', 'c'])

    def test_linked_event_self_link(self):
        self.assertEqual(self.ids('a', self.indexes([('a', 'a')])), ['a'])

    def test_linked_event_deterministic_order(self):
        links = [('z', 'm'), ('a', 'm'), ('m', None)]
        self.assertEqual(self.ids('z', self.indexes(links)), self.ids('a', self.indexes(reversed(links))))

    def test_linked_event_no_recursion_limit(self):
        links = [(f'e{i}', f'e{i-1}' if i else None) for i in range(2000)]
        self.assertEqual(len(resolve_linked_component('e0', self.indexes(links))), 2000)

    def test_unknown_references_and_roots(self):
        with self.assertRaisesRegex(DataValidationError, 'unknown linked_event_id'):
            self.indexes([('a', 'missing')])
        with self.assertRaisesRegex(DataValidationError, 'unknown event_id'):
            self.ids('missing', self.indexes([('a', None)]))

    def test_cross_user_link_rejected(self):
        base = dataset().events[0]
        events = (replace(base, event_id='a', linked_event_id=None),
                  replace(base, event_id='b', linked_event_id='a', user_id=dataset().profiles[1].user_id))
        with self.assertRaisesRegex(DataValidationError, 'another user'):
            build_indexes(replace(dataset(), events=events, messages=(), images=()))
