"""The shipped word bank loads, and bad edits are rejected with a message naming the entry."""

import copy
import json
import re
from pathlib import Path

from django.test import SimpleTestCase

from aac import wordbank

SYMBOLS_TS = Path(__file__).resolve().parents[3] / 'frontend' / 'src' / 'data' / 'symbols.ts'


def shipped():
    return json.loads(wordbank.BANK_PATH.read_text(encoding='utf-8'))


class ShippedBankTests(SimpleTestCase):
    def test_loads(self):
        bank = wordbank.load()
        self.assertIn('math', bank['topics'])
        self.assertEqual(len(bank['fallback']), wordbank.PHRASE_COUNT)

    def test_example_question_topics_exist(self):
        bank = wordbank.load()
        for topic in ('math', 'classes', 'after_school'):
            self.assertIn(topic, bank['topics'])

    def test_every_topic_has_enough_phrases(self):
        bank = wordbank.load()
        for topic_id in bank['topics']:
            self.assertGreaterEqual(len(wordbank.topic_phrases(bank, topic_id)), wordbank.MIN_TOPIC_PHRASES, topic_id)

    def test_symbols_exist_on_the_board(self):
        known = set(re.findall(r"word\('([a-z0-9-]+)'", SYMBOLS_TS.read_text(encoding='utf-8')))
        self.assertTrue(known, 'symbols.ts format changed; update this test.')
        for phrase in wordbank.load()['phrases'].values():
            if phrase['symbol'] is not None:
                self.assertIn(phrase['symbol'], known, phrase['id'])


class ValidationTests(SimpleTestCase):
    def assertRejected(self, change, message):
        data = copy.deepcopy(shipped())
        change(data)
        with self.assertRaisesRegex(wordbank.InvalidWordBank, message):
            wordbank.validate(data)

    def test_duplicate_phrase_id(self):
        self.assertRejected(lambda d: d['phrases'].append(dict(d['phrases'][0], text='Another')), "'yes' is defined twice")

    def test_duplicate_text_ignores_case(self):
        self.assertRejected(lambda d: d['phrases'].append(dict(d['phrases'][0], id='yes-again', text='YES')), 'repeats the text')

    def test_unknown_topic_reference(self):
        self.assertRejected(lambda d: d['phrases'][6]['topics'].append('weather'), 'unknown or repeated topic')

    def test_bad_intent_and_role(self):
        self.assertRejected(lambda d: d['phrases'][0].update(intent='demand'), 'intent must be')
        self.assertRejected(lambda d: d['phrases'][0].update(role='adverb'), 'role must be')

    def test_text_limits(self):
        self.assertRejected(lambda d: d['phrases'][0].update(text='x' * 61), 'at most 60')
        self.assertRejected(lambda d: d['phrases'][0].update(text='Two\nlines'), 'printable')
        self.assertRejected(lambda d: d['phrases'][0].update(text=' Yes'), 'trimmed')

    def test_profile_key(self):
        self.assertRejected(lambda d: d['topics'][0].update(profile_key='favorites.toys'), 'profile_key')
        self.assertRejected(lambda d: d['topics'][0].update(profile_key='name'), 'profile_key')

    def test_template_needs_one_slot(self):
        self.assertRejected(lambda d: d['topics'][0].update(template='I want it'), 'one {}')

    def test_topic_needs_examples_and_phrases(self):
        self.assertRejected(lambda d: d['topics'][0].update(examples=['Are you thirsty?']), 'at least 2 examples')
        self.assertRejected(
            lambda d: d['topics'].append({'id': 'weather', 'label': 'Weather', 'profile_key': None,
                                          'template': '{}', 'examples': ['Is it raining?', 'Is it sunny?']}),
            "'weather' needs at least 4 phrases",
        )

    def test_fallback(self):
        self.assertRejected(lambda d: d['fallback'].pop(), 'fallback must list 6')
        self.assertRejected(lambda d: d['fallback'].__setitem__(0, 'missing'), 'fallback must list 6')

    def test_extra_field(self):
        self.assertRejected(lambda d: d['phrases'][0].update(patient='someone'), 'exactly the fields')
