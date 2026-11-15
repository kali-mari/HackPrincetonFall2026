"""Conversation suggestions: six local choices, confirmed facts only, keyword and model paths."""

import ast
from concurrent import futures
import hashlib
import json
import math
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from aac import conversation, embeddings, wordbank

QUESTIONS = json.loads((Path(__file__).parent / 'fixtures' / 'topic_questions.json').read_text())['questions']
EMPTY = {}  # A patient with no favorites, facts or vocabulary.
FULL = {
    'favorites': {'drinks': ['apple juice'], 'foods': ['pasta'], 'activities': ['puzzles']},
    'about': {'classes': ['Math', 'Art', 'Music'], 'interests': ['drawing', 'swimming'], 'people': ['Sam']},
    'vocabulary': ['dinosaur books'],
}


def fake_embed(texts):
    """Deterministic bag-of-words vectors: shared words mean similar vectors."""
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for word in conversation.words(text):
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 64] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        vectors.append([x / norm for x in vector])
    return vectors


def reset_model_state():
    conversation._bank_vectors.clear()
    conversation.vocabulary_vectors.cache_clear()
    if conversation._pending is not None:
        futures.wait([conversation._pending])  # let a slow fake call finish before the next test
        conversation._pending = None


@override_settings(EMBED_PROVIDER='')
class KeywordSuggestionTests(SimpleTestCase):
    def suggest(self, *lines, preferences=EMPTY, recent=()):
        result = conversation.suggest(list(lines), preferences, recent)
        if result is not None:
            phrases = result['phrases']
            self.assertEqual(len(phrases), 6, phrases)
            self.assertEqual(len({p.casefold() for p in phrases}), 6, phrases)
            self.assertEqual(result['source'], 'keywords')
        return result

    def test_favorite_math_symbol_without_facts(self):
        result = self.suggest('What is your favorite math symbol?')
        self.assertEqual(result['topic'], 'math')
        self.assertEqual(result['phrases'][-2:], ["I don't know", 'Something else'])
        self.assertEqual(result['phrases'][:4], ['Plus', 'Minus', 'Equals', 'Times'])  # answer words before sentences

    def test_classes_come_from_confirmed_profile_facts(self):
        result = self.suggest('What classes are you taking?', preferences=FULL)
        self.assertEqual(result['topic'], 'classes')
        self.assertEqual(result['phrases'][:3], ['Math', 'Art', 'Music'])
        self.assertNotIn("I don't know", result['phrases'])
        self.assertEqual(result['phrases'][-1], 'Something else')

    def test_classes_without_facts_stay_generic_and_say_so(self):
        result = self.suggest('What classes are you taking?')
        self.assertIn("I don't know", result['phrases'])
        self.assertTrue(set(result['phrases']) <= {p['text'] for p in wordbank.load()['phrases'].values()})

    def test_after_school_uses_interests(self):
        result = self.suggest('What would you like to do after school?', preferences=FULL)
        self.assertEqual(result['topic'], 'after_school')
        self.assertEqual(result['phrases'][:2], ['Drawing', 'Swimming'])

    def test_options_named_in_the_question_come_first(self):
        self.assertEqual(self.suggest('Do you want water or juice?')['phrases'][:2], ['Water', 'Juice'])
        self.assertEqual(self.suggest('Do you like the plus sign or the minus sign?')['phrases'][:2],
                         ['Plus sign', 'Minus sign'])
        self.assertEqual(self.suggest('Do you have science or art this term?')['phrases'][:2], ['Science', 'Art'])

    def test_options_keep_words_like_away_and_out(self):
        self.assertEqual(conversation.or_options('Is adding or taking away more fun?'), ['Adding', 'Taking away'])
        self.assertEqual(conversation.or_options('Do you want to go out or stay home?'), ['Go out', 'Stay'])

    def test_color_and_animal_questions_stay_apart(self):
        colors = self.suggest('What color is your shirt?')
        self.assertEqual(colors['topic'], 'colors')
        self.assertFalse({'Cats', 'Dogs'} & set(colors['phrases']))
        self.assertEqual(self.suggest('Do you like dogs?')['topic'], 'animals')

    def test_or_not_is_not_an_option(self):
        self.assertEqual(conversation.or_options('Do you want to go or not?'), [])

    def test_yes_no_questions_offer_yes_and_no_first(self):
        result = self.suggest('Are you thirsty?', preferences=FULL)
        self.assertEqual(result['phrases'][:3], ['Yes', 'No', 'I want apple juice'])
        self.assertNotIn("I don't know", result['phrases'])

    def test_unknown_question_gets_general_choices(self):
        result = self.suggest('What is the weather like outside?')
        self.assertIsNone(result['topic'])
        self.assertEqual(result['phrases'], ['Say it again', 'Yes', 'No', "I don't want to say", "I don't know", 'Something else'])

    def test_unrelated_statement_keeps_regular_predictions(self):
        self.assertIsNone(self.suggest('I am going to make a phone call.'))
        self.assertIsNone(self.suggest())

    def test_follow_up_uses_an_earlier_topic(self):
        self.assertEqual(self.suggest('Are you thirsty?', 'What about now?')['topic'], 'drink')

    def test_recent_speech_lifts_a_phrase(self):
        plain = self.suggest('How are you feeling?')['phrases']
        boosted = self.suggest('How are you feeling?', recent=['I feel sad', 'I feel sad'])['phrases']
        self.assertGreater(plain.index('I feel sad'), 0)
        self.assertEqual(boosted[0], 'I feel sad')

    def test_custom_vocabulary_is_offered_when_it_matches(self):
        self.assertIn('Dinosaur books', self.suggest('Which books do you want?', preferences=FULL)['phrases'])

    def test_patients_never_see_each_others_facts(self):
        other = {'about': {'classes': ['Chemistry']}}
        self.assertNotIn('Chemistry', self.suggest('What classes are you taking?', preferences=FULL)['phrases'])
        self.assertIn('Chemistry', self.suggest('What classes are you taking?', preferences=other)['phrases'])

    def test_every_evaluation_question_gives_six_distinct_choices(self):
        for item in QUESTIONS:
            for preferences in (EMPTY, FULL):
                with self.subTest(question=item['question']):
                    self.suggest(item['question'], preferences=preferences)


@override_settings(EMBED_PROVIDER='minilm', PREDICT_TIMEOUT_SECONDS=2)
class ModelSuggestionTests(SimpleTestCase):
    def setUp(self):
        reset_model_state()
        self.addCleanup(reset_model_state)

    def test_model_picks_the_topic(self):
        with patch('aac.embeddings.embed', side_effect=fake_embed):
            result = conversation.suggest(['What classes are you taking?'], FULL)
        self.assertEqual((result['source'], result['topic']), ('model', 'classes'))
        self.assertEqual(result['phrases'][:3], ['Math', 'Art', 'Music'])

    def test_model_ranking_keeps_answer_words_first_for_what_questions(self):
        with patch('aac.embeddings.embed', side_effect=fake_embed):
            result = conversation.suggest(['What is your favorite math symbol?'], EMPTY)
        self.assertEqual(result['source'], 'model')
        self.assertIn('Plus', result['phrases'])
        self.assertNotEqual(result['phrases'][0], 'I like math')

    def test_threshold_controls_how_sure_a_topic_must_be(self):
        with patch('aac.embeddings.embed', side_effect=fake_embed):
            loose = conversation.suggest(['Which class is next?'], EMPTY, threshold=0.25)
            strict = conversation.suggest(['Which class is next?'], EMPTY, threshold=0.75)
        self.assertEqual(loose['topic'], 'classes')
        self.assertIsNone(strict['topic'])  # not sure enough: general choices instead
        self.assertEqual(strict['phrases'][0], 'Say it again')

    def test_model_failure_falls_back_to_keywords(self):
        with patch('aac.embeddings.embed', side_effect=embeddings.EmbeddingUnavailable('missing')):
            result = conversation.suggest(['Are you thirsty?'], EMPTY)
        self.assertEqual((result['source'], result['topic']), ('keywords', 'drink'))

    @override_settings(PREDICT_TIMEOUT_SECONDS=0.05)
    def test_slow_model_falls_back_within_the_deadline(self):
        def slow(texts):
            time.sleep(0.3)
            return fake_embed(texts)
        with patch('aac.embeddings.embed', side_effect=slow):
            started = time.monotonic()
            first = conversation.suggest(['Are you thirsty?'], EMPTY)
            second = conversation.suggest(['Are you hungry?'], EMPTY)  # previous call still busy: skip the model
            elapsed = time.monotonic() - started
        self.assertEqual((first['source'], second['source']), ('keywords', 'keywords'))
        self.assertEqual(second['topic'], 'food')
        self.assertLess(elapsed, 0.25)

    def test_warm_up_never_raises(self):
        with patch('aac.embeddings.embed', side_effect=embeddings.EmbeddingUnavailable('missing')):
            conversation.warm(FULL).result()  # the background job logs and swallows the failure

    @override_settings(EMBED_PROVIDER='')
    def test_warm_up_is_a_no_op_when_embeddings_are_off(self):
        self.assertIsNone(conversation.warm(FULL))

    def test_questions_during_warm_up_use_keywords_then_the_model(self):
        release = threading.Event()

        def slow_first(texts):
            release.wait(2)
            return fake_embed(texts)
        with patch('aac.embeddings.embed', side_effect=slow_first):
            started = time.monotonic()
            warming = conversation.warm(FULL)
            self.assertLess(time.monotonic() - started, 0.1)  # returns at once
            during = conversation.suggest(['Are you thirsty?'], EMPTY)
            release.set()
            warming.result()
            after = conversation.suggest(['Are you thirsty?'], EMPTY)
        self.assertEqual((during['source'], after['source']), ('keywords', 'model'))


class LocalOnlyTests(SimpleTestCase):
    def test_conversation_code_imports_no_hosted_clients(self):
        for module in (conversation, embeddings, wordbank):
            tree = ast.parse(Path(module.__file__).read_text())
            imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            imported |= {node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
            for name in ('llm', 'speech', 'casting', 'requests', 'httpx', 'urllib', 'socket', 'boto3', 'openai', 'anthropic', 'google'):
                self.assertFalse(any(name in part.split('.') for part in imported), f'{module.__name__} imports {name}')

    @override_settings(EMBED_PROVIDER='', PREDICT_PROVIDER='gemini')
    def test_suggestions_never_open_a_connection_or_call_a_provider(self):
        def refuse(*args, **kwargs):
            raise AssertionError('conversation suggestions tried to reach the network')
        with patch('socket.socket.connect', side_effect=refuse), patch('aac.llm.suggest_phrases', side_effect=refuse), \
                patch.dict('aac.llm.PROVIDERS', {name: refuse for name in ('openai', 'anthropic', 'gemini', 'bedrock')}):
            for item in QUESTIONS:
                conversation.suggest([item['question']], FULL, recent=['I feel sad'])


@unittest.skipUnless(os.environ.get('EMBED_EVAL_MODEL_DIR'), 'set EMBED_EVAL_MODEL_DIR to the installed MiniLM folder')
class RealModelAccuracyTests(SimpleTestCase):
    """Run where the model is installed (the UNO Q): topic accuracy on questions not copied from the bank."""

    def test_topic_accuracy(self):
        with override_settings(EMBED_PROVIDER='minilm', EMBED_MODEL_DIR=Path(os.environ['EMBED_EVAL_MODEL_DIR']),
                               PREDICT_TIMEOUT_SECONDS=10):
            reset_model_state()
            conversation.warm().result()
            bank, misses = wordbank.load(), []
            known = [q for q in QUESTIONS if q['topic']]
            for item in QUESTIONS:
                vectors = conversation.model_results(bank, [item['question']], ())
                got = conversation.model_topic(vectors, vectors['lines'][0])
                if got != item['topic']:
                    misses.append((item['question'], item['topic'], got))
        right_known = sum(1 for q in known if (q['question'], q['topic']) not in {(m[0], m[1]) for m in misses})
        rejected = sum(1 for q in QUESTIONS if not q['topic'] and q['question'] not in {m[0] for m in misses})
        print(f'\nknown {right_known}/{len(known)}, unknown rejected {rejected}/{len(QUESTIONS) - len(known)}')
        for miss in misses:
            print('  miss:', miss)
        self.assertGreaterEqual(right_known / len(known), 0.80)
        self.assertGreaterEqual(rejected / (len(QUESTIONS) - len(known)), 0.90)
