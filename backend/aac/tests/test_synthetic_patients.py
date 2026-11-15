"""End-to-end validation with two synthetic patients (fixtures/synthetic_patients.json).

Runs whole flows through the real WebSocket consumer, HTTP routes and SQLite: the
example questions, paraphrases, unfamiliar topics, missing personal facts, offline
operation, inference failure, switching patients, and that no patient data or
conversation text reaches a hosted service or the logs. Only the microphone
(FakeListener) and hosted providers (spies) are replaced. Paraphrase accuracy of the
real model is RealModelAccuracyTests in test_conversation.py, run where the model is installed.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import re
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from aac import consumers, embeddings, llm
from aac.history import time_bucket
from aac.models import CommunicationEvent, PredictionRecord, Profile
from aac.tests.test_listen import BROWSER, FakeListener
from config.asgi import application

DATA = json.loads((Path(__file__).parent / 'fixtures' / 'synthetic_patients.json').read_text())
NOW = datetime(2026, 11, 15, 17, 15, tzinfo=timezone.utc)
EXAMPLES = ['What is your favorite math symbol?', 'What classes are you taking?', 'What would you like to do after school?']
# Avery's facts that the word bank does not also contain: seeing one for Blake would mean leaked or invented facts.
AVERY_ONLY = ['Drawing', 'Swimming', 'Sam', 'Dinosaur books', 'I want apple juice', 'I want pasta']


def create(name):
    persona = DATA['patients'][name]
    patient = Profile.objects.create(role='patient', display_name=persona['display_name'], language='en',
                                     timezone=persona['timezone'], preferences=persona['preferences'])
    for item in persona['spoken']:
        moment = NOW - timedelta(days=item['days_ago'])
        CommunicationEvent.objects.create(
            id=uuid4(), utterance_id=uuid4(), patient=patient, kind='spoken', text=item['text'], occurred_at=moment,
            activity=item['activity'], time_bucket=time_bucket(moment, patient.timezone), input_source='button')
    return patient


class ProviderSpy:
    """Stands in for every hosted prediction provider: records prompts, never connects."""

    def __init__(self, fail=False):
        self.prompts, self.fail = [], fail

    def __call__(self, system, prompt, model):
        self.prompts.append(prompt)
        if self.fail:
            raise ConnectionError('offline')
        return json.dumps({'phrases': ['Generic one', 'Generic two', 'Generic three', 'Generic four',
                                       'Generic five', 'Generic six']})


@override_settings(EMBED_PROVIDER='', PREDICT_PROVIDER='gemini', PREDICT_MODEL='test-model', PREDICT_TIMEOUT_SECONDS=1)
class SyntheticPatientTests(TransactionTestCase):
    def setUp(self):
        self.avery, self.blake = create('avery'), create('blake')
        FakeListener.instances, FakeListener.fail = [], None
        consumers.ConversationConsumer.owner = None
        for target in (patch.object(consumers, 'Listener', FakeListener),
                       patch('socket.socket.connect', side_effect=AssertionError('tried to use the network'))):
            target.start()
            self.addCleanup(target.stop)
        self.spy = ProviderSpy()
        providers = patch.dict(llm.PROVIDERS, {name: self.spy for name in llm.PROVIDERS})
        providers.start()
        self.addCleanup(providers.stop)

    async def listen(self, patient, **extra):
        ws = WebsocketCommunicator(application, '/ws/conversation/', headers=BROWSER)
        connected, _ = await ws.connect()
        self.assertTrue(connected)
        self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': False})
        await ws.send_json_to({'type': 'start', 'patient_id': str(patient.pk), **extra})
        self.assertEqual(await ws.receive_json_from(timeout=3), {'type': 'state', 'listening': True})
        return ws, FakeListener.instances[-1]

    async def ask(self, ws, listener, text):
        listener.emit(text)
        transcript = await ws.receive_json_from(timeout=3)
        self.assertEqual((transcript['type'], transcript['text']), ('transcript', text))
        result = await ws.receive_json_from(timeout=3)
        self.assertEqual((result['type'], result['seq']), ('suggestions', transcript['seq']))
        if result['phrases']:
            self.assertEqual(len(result['phrases']), 6)
            self.assertEqual(len({phrase.casefold() for phrase in result['phrases']}), 6)
            self.assertEqual(result['phrases'][-1], 'Something else')
        return result

    async def predict(self, patient, recent=()):
        response = await self.async_client.post('/api/aac/predict', {
            'patient_id': str(patient.pk), 'time': NOW.isoformat(), 'activity': 'lunch', 'recent': list(recent),
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['phrases']), 6)
        return data

    async def test_example_questions_use_confirmed_facts_and_never_invent_them(self):
        ws, listener = await self.listen(self.avery)
        math, classes, after = [await self.ask(ws, listener, question) for question in EXAMPLES]
        self.assertEqual(math['topic'], 'Math')
        self.assertIn('Plus', math['phrases'])
        self.assertIn("I don't know", math['phrases'])  # no favorite symbol on file: no invented answer
        self.assertEqual(classes['phrases'][:3], ['Math', 'Art', 'Music'])
        self.assertEqual(after['phrases'][:2], ['Drawing', 'Swimming'])
        await ws.disconnect()

        ws, listener = await self.listen(self.blake)
        for question in EXAMPLES:
            result = await self.ask(ws, listener, question)
            self.assertIn("I don't know", result['phrases'])
            self.assertFalse(set(AVERY_ONLY) & set(result['phrases']), question)
        await ws.disconnect()

    async def test_paraphrases_unfamiliar_topics_and_follow_ups(self):
        ws, listener = await self.listen(self.avery)
        self.assertEqual((await self.ask(ws, listener, 'Which subjects are you taking this year?'))['topic'], 'Classes')
        self.assertEqual((await self.ask(ws, listener, 'Which math symbol do you like best?'))['topic'], 'Math')
        unknown = await self.ask(ws, listener, 'What is the weather like outside?')
        self.assertIsNone(unknown['topic'])
        self.assertEqual(unknown['phrases'][0], 'Say it again')
        self.assertEqual((await self.ask(ws, listener, 'I am going to make a phone call.'))['phrases'], [])
        drink = await self.ask(ws, listener, 'Do you want water, juice, or milk?')
        self.assertEqual(drink['phrases'][:3], ['Water', 'Juice', 'Milk'])
        self.assertEqual((await self.ask(ws, listener, 'What about now?'))['topic'], 'Drinks')
        await ws.disconnect()

    async def test_offline_with_every_hosted_call_failing(self):
        self.spy.fail = True
        with self.assertLogs('aac.llm', 'WARNING'):
            for patient in (self.avery, self.blake):
                data = await self.predict(patient, recent=['I want apple juice'])
                self.assertIn(data['source'], ('history', 'default'))
        ws, listener = await self.listen(self.blake)
        self.assertEqual((await self.ask(ws, listener, 'Are you hungry?'))['topic'], 'Food')
        await ws.disconnect()

    async def test_model_failure_or_slowness_keeps_suggestions_coming(self):
        with override_settings(EMBED_PROVIDER='minilm'), self.assertLogs('aac.conversation', 'WARNING'):
            with patch('aac.embeddings.embed', side_effect=embeddings.EmbeddingUnavailable('missing')):
                ws, listener = await self.listen(self.avery)
                self.assertEqual((await self.ask(ws, listener, 'What classes are you taking?'))['phrases'][:3],
                                 ['Math', 'Art', 'Music'])
                await ws.disconnect()

            def slow(texts):
                time.sleep(1.5)
                raise embeddings.EmbeddingUnavailable('late')
            with patch('aac.embeddings.embed', side_effect=slow), override_settings(PREDICT_TIMEOUT_SECONDS=0.2):
                ws, listener = await self.listen(self.avery)
                started = time.monotonic()
                self.assertEqual((await self.ask(ws, listener, 'Are you thirsty?'))['topic'], 'Drinks')
                self.assertLess(time.monotonic() - started, 1.0)
                await ws.disconnect()
            time.sleep(1.6)  # let the abandoned slow call finish before the next test

    async def test_switching_patients_mid_listen_forgets_the_previous_patient(self):
        ws, listener = await self.listen(self.avery)
        self.assertEqual((await self.ask(ws, listener, 'What classes are you taking?'))['phrases'][:3], ['Math', 'Art', 'Music'])
        await ws.send_json_to({'type': 'start', 'patient_id': str(self.blake.pk)})  # switch without stopping
        self.assertEqual(await ws.receive_json_from(timeout=3), {'type': 'state', 'listening': True})
        follow_up = await self.ask(ws, listener, 'What about now?')
        self.assertIsNone(follow_up['topic'])  # Avery's lines were cleared
        result = await self.ask(ws, listener, 'What would you like to do after school?')
        self.assertFalse(set(AVERY_ONLY) & set(result['phrases']))
        self.assertEqual(len(FakeListener.instances), 1)  # same microphone session
        await ws.send_json_to({'type': 'stop'})
        self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': False})
        await ws.disconnect()

    async def test_no_patient_or_conversation_data_reaches_hosted_services_or_logs(self):
        records = []
        handler = logging.Handler(logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            for patient in (self.avery, self.blake):
                await self.predict(patient, recent=['I want apple juice', 'Read to me'])
            with override_settings(LEGACY_DEMO_PATIENT_ID=self.avery.pk):
                await self.async_client.post('/api/predict', {'time': NOW.isoformat(), 'activity': 'lunch',
                                                              'recent': ['Read to me']}, content_type='application/json')
            ws, listener = await self.listen(self.avery)
            spoken = [*EXAMPLES, 'Do you want to see Sam after swimming?']
            for question in spoken:
                await self.ask(ws, listener, question)
            await ws.disconnect()
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)

        self.assertTrue(self.spy.prompts, 'the hosted model was expected to be asked for generic phrases')
        for prompt in self.spy.prompts:
            self.assertEqual(set(json.loads(prompt)), {'activity', 'time_of_day'})
        private = [*DATA['private_markers'], *spoken, str(self.avery.pk), str(self.blake.pk)]
        for text in [*self.spy.prompts, *records]:
            for marker in private:
                self.assertIsNone(re.search(rf'\b{re.escape(marker)}\b', text), f'{marker!r} appeared in {text!r}')

    async def test_suggestions_never_become_facts_or_events(self):
        before = await database_sync_to_async(self.snapshot)()
        ws, listener = await self.listen(self.avery)
        result = await self.ask(ws, listener, 'What classes are you taking?')
        await ws.disconnect()
        self.assertEqual(await database_sync_to_async(self.snapshot)(), before)  # shown, not stored

        prediction = await self.predict(self.avery)
        chosen = result['phrases'][1]  # the patient selects and speaks a conversation card
        response = await self.async_client.post('/api/aac/events', {
            'event_id': str(uuid4()), 'utterance_id': str(uuid4()), 'patient_id': str(self.avery.pk), 'kind': 'spoken',
            'text': chosen, 'timestamp': NOW.isoformat(), 'input_source': 'button',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        preferences, events, records = await database_sync_to_async(self.snapshot)()
        self.assertEqual(preferences, before[0])  # a selection never edits confirmed facts
        self.assertEqual(events, before[1] + 1)
        self.assertEqual(records, before[2] + 1)
        self.assertTrue(prediction['prediction_id'])

    def snapshot(self):
        self.avery.refresh_from_db()
        return (self.avery.preferences, CommunicationEvent.objects.filter(patient=self.avery).count(),
                PredictionRecord.objects.filter(patient=self.avery).count())
