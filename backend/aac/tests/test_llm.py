"""AI phrase predictions: parsing, deadline, fallback, provider request shapes; no network."""

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, TestCase, override_settings
from jsonschema import Draft202012Validator, FormatChecker

from aac import llm
from aac.models import PredictionRecord
from aac.openapi import SCHEMAS
from aac.tests.test_predictions import NOW, make_patient, speak

AI_PHRASES = ['I want pizza', 'More juice', 'Can I play?', 'All done', 'Help me', 'I love this']


def reply(phrases=AI_PHRASES):
    return json.dumps({'phrases': phrases})


class ParsePhrasesTests(SimpleTestCase):
    def test_valid_output(self):
        self.assertEqual(llm.parse_phrases(reply()), AI_PHRASES)
        self.assertEqual(llm.parse_phrases(f'```json\n{reply()}\n```'), AI_PHRASES)
        padded = reply([f'  {phrase} ' for phrase in AI_PHRASES])
        self.assertEqual(llm.parse_phrases(padded), AI_PHRASES)

    def test_invalid_output_is_rejected_not_repaired(self):
        bad = [
            None, '', 'not json', '[]', json.dumps(AI_PHRASES), '{"phrases": "I want pizza"}',
            reply(AI_PHRASES[:5]), reply(AI_PHRASES + ['Extra']),
            reply(AI_PHRASES[:5] + ['i want PIZZA']),  # case-insensitive duplicate
            reply(AI_PHRASES[:5] + ['   ']), reply(AI_PHRASES[:5] + [7]),
            reply(AI_PHRASES[:5] + ['x' * 101]), reply(AI_PHRASES[:5] + ['two\nlines']),
            'Sure! Here are some phrases: ' + reply(),
        ]
        for text in bad:
            self.assertIsNone(llm.parse_phrases(text), repr(text)[:60])


@override_settings(PREDICT_PROVIDER='openai', PREDICT_MODEL='test-model', PREDICT_TIMEOUT_SECONDS=0.3)
class SuggestPhrasesTests(SimpleTestCase):
    def suggest(self):
        return llm.suggest_phrases('lunch', 'midday')

    def test_disabled_without_provider_or_model(self):
        provider = Mock(return_value=reply())
        with patch.dict(llm.PROVIDERS, {'openai': provider}):
            with override_settings(PREDICT_PROVIDER=''):
                self.assertIsNone(self.suggest())
            with override_settings(PREDICT_MODEL=''):
                self.assertIsNone(self.suggest())  # no default model for openai
        provider.assert_not_called()

    def test_anthropic_defaults_to_haiku(self):
        provider = Mock(return_value=reply())
        with patch.dict(llm.PROVIDERS, {'anthropic': provider}), \
                override_settings(PREDICT_PROVIDER='anthropic', PREDICT_MODEL=''):
            self.assertEqual(self.suggest(), AI_PHRASES)
        self.assertEqual(provider.call_args.args[2], 'claude-haiku-5-5')

    def test_prompt_is_json_data_separate_from_instructions(self):
        provider = Mock(return_value=reply())
        with patch.dict(llm.PROVIDERS, {'openai': provider}):
            self.assertEqual(self.suggest(), AI_PHRASES)
        system, prompt, model = provider.call_args.args
        self.assertEqual(system, llm.SYSTEM)
        self.assertEqual(model, 'test-model')
        self.assertEqual(json.loads(prompt), {'activity': 'lunch', 'time_of_day': 'midday'})  # nothing about the patient

    def test_failures_return_none_without_logging_content(self):
        for provider in (Mock(side_effect=RuntimeError('secret-key-in-message')),
                         Mock(return_value='nonsense secret-key-in-message')):
            with patch.dict(llm.PROVIDERS, {'openai': provider}), self.assertLogs('aac.llm', 'WARNING') as logs:
                self.assertIsNone(self.suggest())
            self.assertNotIn('secret-key-in-message', '\n'.join(logs.output))

    def test_deadline_does_not_wait_for_slow_provider(self):
        release = threading.Event()
        provider = Mock(side_effect=lambda *args: release.wait(5) and reply())
        with patch.dict(llm.PROVIDERS, {'openai': provider}), self.assertLogs('aac.llm', 'WARNING'):
            started = time.monotonic()
            self.assertIsNone(self.suggest())
            self.assertLess(time.monotonic() - started, 1.0)
        release.set()
        # The abandoned call keeps its slot until it finishes, then gives it back
        deadline = time.monotonic() + 2
        while llm.SLOTS._value < llm.MAX_IN_FLIGHT and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(llm.SLOTS._value, llm.MAX_IN_FLIGHT)

    def test_saturated_slots_skip_ai(self):
        provider = Mock(return_value=reply())
        for _ in range(llm.MAX_IN_FLIGHT):
            llm.SLOTS.acquire()
        try:
            with patch.dict(llm.PROVIDERS, {'openai': provider}), self.assertLogs('aac.llm', 'WARNING'):
                self.assertIsNone(self.suggest())
        finally:
            for _ in range(llm.MAX_IN_FLIGHT):
                llm.SLOTS.release()
        provider.assert_not_called()


@override_settings(PREDICT_PROVIDER='openai', PREDICT_MODEL='test-model', PREDICT_TIMEOUT_SECONDS=0.3)
class PredictRouteAITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.patient = make_patient()
        speak(self.patient, 'Pizza please')

    def predict(self, provider, path='/api/aac/predict'):
        body = {'time': NOW.isoformat(), 'activity': 'lunch', 'recent': ['I want']}
        if path == '/api/aac/predict':
            body['patient_id'] = str(self.patient.pk)
        # Fallback warnings are covered above; keep test output quiet here
        with patch.dict(llm.PROVIDERS, {'openai': provider}), patch.object(llm.log, 'warning'):
            return self.client.post(path, body, content_type='application/json')

    def test_generic_ai_phrases_follow_the_patients_own_history(self):
        provider = Mock(return_value=reply())
        response = self.predict(provider)
        data = response.json()
        Draft202012Validator(SCHEMAS['PredictResponse'], format_checker=FormatChecker()).validate(data)
        expected = ['Pizza please', *AI_PHRASES[:5]]
        self.assertEqual((data['phrases'], data['source']), (expected, 'ai'))
        record = PredictionRecord.objects.get(pk=data['prediction_id'])
        self.assertEqual((record.phrases, record.source), (expected, 'ai'))
        # The model saw only the activity and time of day, never this patient's history
        self.assertEqual(json.loads(provider.call_args.args[1]), {'activity': 'lunch', 'time_of_day': 'midday'})

    def test_failure_falls_back_to_history(self):
        data = self.predict(Mock(side_effect=TimeoutError)).json()
        self.assertEqual((data['phrases'][0], data['source']), ('Pizza please', 'history'))

    def test_patient_data_never_reaches_the_hosted_model(self):
        self.patient.preferences = {**self.patient.preferences, 'favorites': {'foods': ['pears'], 'drinks': ['mango juice']},
                                    'about': {'classes': ['Chemistry']}, 'vocabulary': ['dinosaur books']}
        self.patient.save()
        provider = Mock(return_value=reply())
        data = self.predict(provider).json()
        prompt = provider.call_args.args[1]
        for private in ('pears', 'mango', 'Chemistry', 'dinosaur', 'Pizza please', 'I want', str(self.patient.pk),
                        self.patient.display_name):
            self.assertNotIn(private, prompt)
        # Favorites and history are applied here instead, ahead of the generic phrases
        self.assertEqual(data['phrases'][:3], ['I want pears', 'I want mango juice', 'Pizza please'])
        self.assertEqual(len(set(data['phrases'])), 6)
        self.assertEqual(data['source'], 'ai')

    def test_provider_failure_retains_contextual_favorites_without_inventing_events(self):
        self.patient.preferences = {**self.patient.preferences, 'favorites': {'foods': ['pears']}}
        self.patient.save()
        before = self.patient.events.count()
        data = self.predict(Mock(side_effect=TimeoutError)).json()
        self.assertEqual(data['phrases'][0], 'I want pears')
        self.assertEqual(self.patient.events.count(), before)

    def test_legacy_route_keeps_its_shape(self):
        with override_settings(LEGACY_DEMO_PATIENT_ID=self.patient.pk):
            self.assertEqual(self.predict(Mock(return_value=reply()), '/api/predict').json(),
                             {'phrases': ['Pizza please', *AI_PHRASES[:5]]})
            data = self.predict(Mock(return_value='bad'), '/api/predict').json()
        self.assertEqual(set(data), {'phrases'})
        self.assertEqual(data['phrases'][0], 'Pizza please')


class ProviderRequestTests(SimpleTestCase):
    """Each provider's request shape and text extraction, against a mocked SDK client."""

    def test_openai(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply()))])
        with patch.object(llm, 'openai_client', return_value=client):
            self.assertEqual(llm.openai_provider('sys', 'data', 'm'), reply())
        client.chat.completions.create.assert_called_once_with(
            model='m', messages=[{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'data'}],
            max_completion_tokens=llm.MAX_OUTPUT_TOKENS)

    def test_anthropic(self):
        client = Mock()
        client.messages.create.return_value = SimpleNamespace(stop_reason='end_turn', content=[
            SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=reply())])
        with patch.object(llm, 'anthropic_client', return_value=client):
            self.assertEqual(llm.anthropic_provider('sys', 'data', 'm'), reply())
            client.messages.create.return_value = SimpleNamespace(stop_reason='refusal', content=[])
            with self.assertRaises(ValueError):
                llm.anthropic_provider('sys', 'data', 'm')
        kwargs = client.messages.create.call_args.kwargs
        self.assertEqual((kwargs['model'], kwargs['system'], kwargs['messages'], kwargs['output_config']),
                         ('m', 'sys', [{'role': 'user', 'content': 'data'}], {'effort': 'low'}))

    def test_gemini(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text=reply())
        with patch.object(llm, 'gemini_client', return_value=client):
            self.assertEqual(llm.gemini_provider('sys', 'data', 'm'), reply())
        kwargs = client.models.generate_content.call_args.kwargs
        self.assertEqual((kwargs['model'], kwargs['contents']), ('m', 'data'))
        config = kwargs['config']
        self.assertEqual((config.system_instruction, config.response_mime_type, config.max_output_tokens),
                         ('sys', 'application/json', llm.MAX_OUTPUT_TOKENS))
        self.assertEqual(config.response_json_schema, llm.PHRASES_SCHEMA)

    def test_gemini_flash_lite_uses_minimal_thinking(self):
        from google.genai import types
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text=reply())
        with patch.object(llm, 'gemini_client', return_value=client):
            self.assertEqual(llm.gemini_provider('sys', 'data', 'gemini-3.5-flash-lite'), reply())
        config = client.models.generate_content.call_args.kwargs['config']
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.MINIMAL)

    def test_gemini_usb_proxy_keeps_retry_count_bounded(self):
        llm.gemini_client.cache_clear()
        try:
            with patch.dict('os.environ', {'GEMINI_PROXY_URL': 'http://127.0.0.1:8767'}), \
                    patch('google.genai.Client') as constructor:
                llm.gemini_client()
            options = constructor.call_args.kwargs['http_options']
            self.assertEqual(options.client_args, {'proxy': 'http://127.0.0.1:8767'})
            self.assertEqual(options.retry_options.attempts, 1)
        finally:
            llm.gemini_client.cache_clear()

    def test_bedrock(self):
        client = Mock()
        client.converse.return_value = {'output': {'message': {'content': [{'text': reply()[:10]}, {'text': reply()[10:]}]}}}
        with patch.object(llm, 'bedrock_client', return_value=client):
            self.assertEqual(llm.bedrock_provider('sys', 'data', 'm'), reply())
        client.converse.assert_called_once_with(
            modelId='m', system=[{'text': 'sys'}],
            messages=[{'role': 'user', 'content': [{'text': 'data'}]}],
            inferenceConfig={'maxTokens': llm.MAX_OUTPUT_TOKENS})

    def test_clients_disable_retries_and_bound_timeouts(self):
        for factory in (llm.openai_client, llm.anthropic_client, llm.gemini_client, llm.bedrock_client):
            factory.cache_clear()
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test', 'ANTHROPIC_API_KEY': 'test',
                                       'GEMINI_API_KEY': 'test', 'AWS_DEFAULT_REGION': 'us-east-1'}):
            openai_client, anthropic_client = llm.openai_client(), llm.anthropic_client()
            gemini_client, bedrock_client = llm.gemini_client(), llm.bedrock_client()
        self.assertEqual((openai_client.max_retries, openai_client.timeout), (0, llm.SDK_TIMEOUT_SECONDS))
        self.assertEqual((anthropic_client.max_retries, anthropic_client.timeout), (0, llm.SDK_TIMEOUT_SECONDS))
        self.assertIsNotNone(gemini_client)
        self.assertEqual(bedrock_client.meta.config.retries['total_max_attempts'], 1)
        self.assertEqual(bedrock_client.meta.config.read_timeout, llm.SDK_TIMEOUT_SECONDS)
        for factory in (llm.openai_client, llm.anthropic_client, llm.gemini_client, llm.bedrock_client):
            factory.cache_clear()  # never leak test credentials into other tests
