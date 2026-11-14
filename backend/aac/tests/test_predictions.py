"""Deterministic prediction ranking, records and attribution against migrated SQLite."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.db import DatabaseError
from django.test import Client, TestCase
from jsonschema import Draft202012Validator, FormatChecker

from aac.history import time_bucket
from aac.models import CommunicationEvent, PredictionRecord, Profile
from aac.openapi import SCHEMAS
from aac.predictions import DEFAULT_PHRASES, weight

PREFERENCES = {'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'], 'default_activity': 'play'}
NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)  # 12:00 in New York: midday


def make_patient(name='Demo patient', **extra):
    return Profile.objects.create(
        role='patient', display_name=name, timezone='America/New_York', language='en',
        preferences=PREFERENCES, **extra,
    )


def speak(patient, text, *, days_ago=0, activity='lunch', hours_ago=0, kind='spoken'):
    moment = NOW - timedelta(days=days_ago, hours=hours_ago)
    extra = {}
    if kind == 'feedback':
        extra = {'prediction': PredictionRecord.objects.create(
            patient=patient, time_bucket='midday', phrases=[text] + list(DEFAULT_PHRASES[:5]), source='default',
        ), 'candidate_index': 0, 'outcome': 'accepted'}
    return CommunicationEvent.objects.create(
        id=uuid4(), utterance_id=uuid4(), patient=patient, kind=kind, text=text, occurred_at=moment,
        activity=activity, time_bucket=time_bucket(moment, patient.timezone), input_source='button', **extra,
    )


class PredictionTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.patient = make_patient()

    def predict(self, patient=None, **changes):
        payload = {
            'patient_id': str((patient or self.patient).pk), 'time': NOW.isoformat(),
            'activity': 'lunch', 'recent': ['I want'], **changes,
        }
        return self.client.post('/api/aac/predict', payload, content_type='application/json')

    def ok(self, response, schema='PredictResponse'):
        self.assertEqual(response.status_code, 200, response.content)
        Draft202012Validator(
            {'$ref': f'#/components/schemas/{schema}', 'components': {'schemas': SCHEMAS}},
            format_checker=FormatChecker(),
        ).validate(response.json())
        return response.json()

    def test_empty_history_returns_saved_defaults(self):
        result = self.ok(self.predict())
        self.assertEqual(result['phrases'], list(DEFAULT_PHRASES[:6]))
        self.assertEqual((result['source'], result['artifact_version']), ('default', None))
        record = PredictionRecord.objects.get(pk=result['prediction_id'])
        self.assertEqual((record.patient, record.phrases, record.activity, record.time_bucket),
                         (self.patient, result['phrases'], 'lunch', 'midday'))

    def test_newer_speech_outweighs_equally_frequent_older_speech(self):
        speak(self.patient, 'Old phrase', days_ago=10)
        speak(self.patient, 'New phrase', days_ago=1)
        self.assertEqual(self.ok(self.predict())['phrases'][:2], ['New phrase', 'Old phrase'])

    def test_decayed_frequency_and_case_insensitive_merge(self):
        for _ in range(3):
            speak(self.patient, 'i want JUICE', days_ago=14)  # 3 * 0.25 = 0.75
        speak(self.patient, 'I want juice ', days_ago=14, hours_ago=-0.5)  # newest spelling; still midday
        speak(self.patient, 'Fresh', days_ago=0)  # 1.0
        phrases = self.ok(self.predict())['phrases']
        self.assertEqual(phrases[:2], ['I want juice', 'Fresh'])
        self.assertEqual(sum(phrase.casefold() == 'i want juice' for phrase in phrases), 1)

    def test_matching_context_ranks_before_broader_history(self):
        for _ in range(5):
            speak(self.patient, 'Play outside', activity='play', days_ago=1, hours_ago=-6)  # evening
        speak(self.patient, 'Lunch at midday', days_ago=3)
        speak(self.patient, 'Lunch in the evening', days_ago=3, hours_ago=-6)  # 18:00 local
        speak(self.patient, 'Midday other activity', activity='bath', days_ago=3)
        phrases = self.ok(self.predict())['phrases']
        self.assertEqual(phrases[:4], ['Lunch at midday', 'Lunch in the evening', 'Midday other activity', 'Play outside'])
        self.assertEqual(self.ok(self.predict(activity=' LUNCH '))['phrases'][:2], phrases[:2])

    def test_sparse_history_fills_with_unique_defaults(self):
        speak(self.patient, 'help ME')
        result = self.ok(self.predict())
        self.assertEqual(result['source'], 'history')
        self.assertEqual(result['phrases'][0], 'help ME')
        self.assertEqual(len({phrase.casefold() for phrase in result['phrases']}), 6)
        self.assertNotIn('Help me', result['phrases'])

    def test_only_this_patients_confirmed_speech_counts(self):
        other = make_patient('Other')
        speak(other, 'Other patient phrase')
        speak(self.patient, 'Only selected', kind='selection')
        speak(self.patient, 'Only feedback', kind='feedback')
        result = self.ok(self.predict())
        self.assertEqual(result['source'], 'default')
        self.assertEqual(result['phrases'], list(DEFAULT_PHRASES[:6]))

    def test_repeated_requests_are_deterministic_with_stable_ties(self):
        for text in ('Banana', 'apple', 'Cherry'):
            speak(self.patient, text, days_ago=2)  # identical weight and time
        first = self.ok(self.predict())
        second = self.ok(self.predict())
        self.assertEqual(first['phrases'], second['phrases'])
        self.assertEqual(first['phrases'][:3], ['apple', 'Banana', 'Cherry'])
        self.assertNotEqual(first['prediction_id'], second['prediction_id'])

    def test_future_events_are_clamped_and_weight_halves_weekly(self):
        self.assertEqual(weight(NOW + timedelta(days=3), NOW), 1.0)
        self.assertAlmostEqual(weight(NOW - timedelta(days=7), NOW), 0.5)
        self.assertAlmostEqual(weight(NOW - timedelta(days=14), NOW), 0.25)

    def test_returned_prediction_supports_event_attribution(self):
        speak(self.patient, 'I want water', days_ago=1)
        result = self.ok(self.predict())
        event = {
            'event_id': str(uuid4()), 'utterance_id': str(uuid4()), 'patient_id': str(self.patient.pk),
            'kind': 'spoken', 'text': result['phrases'][2], 'timestamp': NOW.isoformat(),
            'input_source': 'keyboard', 'prediction_id': result['prediction_id'], 'candidate_index': 2,
        }
        post = lambda body: self.client.post('/api/aac/events', body, content_type='application/json')
        self.assertEqual(post({**event, 'candidate_index': 1}).status_code, 400)
        self.assertEqual(post(event).status_code, 201)
        other = make_patient('Other')
        self.assertEqual(post({**event, 'event_id': str(uuid4()), 'utterance_id': str(uuid4()),
                               'patient_id': str(other.pk)}).status_code, 404)

    def test_invalid_requests_save_nothing(self):
        cases = [
            {'patient_id': 'bad'}, {'time': '2026-11-14T12:00:00'}, {'time': None}, {'activity': ' '},
            {'activity': 'x' * 101}, {'recent': 'I want'}, {'recent': ['x'] * 21}, {'recent': [1]},
            {'recent': [' ']}, {'unknown': True},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                response = self.predict(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'invalid_request')
        caregiver = Profile.objects.create(role='caregiver', display_name='Caregiver')
        for identifier in (uuid4(), caregiver.pk):
            self.assertEqual(self.predict(patient_id=str(identifier)).status_code, 404)
        self.assertEqual(PredictionRecord.objects.count(), 0)

    def test_unreadable_history_falls_back_but_unsaved_record_is_503(self):
        speak(self.patient, 'Hidden by failure')
        with patch('aac.views.recent_spoken', side_effect=DatabaseError('private')):
            self.assertEqual(self.ok(self.predict())['phrases'], list(DEFAULT_PHRASES[:6]))
        with patch('aac.views.PredictionRecord.objects.create', side_effect=DatabaseError('private')):
            response = self.predict()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'private', response.content)


class LegacyPredictTests(TestCase):
    def predict(self, **changes):
        payload = {'time': NOW.isoformat(), 'activity': 'lunch', 'recent': [], **changes}
        return self.client.post('/api/predict', payload, content_type='application/json')

    def test_legacy_shape_uses_demo_patient_history_without_records(self):
        patient = make_patient(pk=settings.LEGACY_DEMO_PATIENT_ID)
        speak(patient, 'Legacy favourite')
        response = self.predict()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'phrases'})
        Draft202012Validator(
            {'$ref': '#/components/schemas/LegacyPredictResponse', 'components': {'schemas': SCHEMAS}},
        ).validate(response.json())
        self.assertEqual(response.json()['phrases'][0], 'Legacy favourite')
        self.assertEqual(PredictionRecord.objects.count(), 0)

    def test_missing_patient_or_storage_returns_defaults(self):
        self.assertEqual(self.predict().json(), {'phrases': list(DEFAULT_PHRASES[:6])})
        make_patient(pk=settings.LEGACY_DEMO_PATIENT_ID)
        with patch('aac.views.recent_spoken', side_effect=DatabaseError('private')):
            response = self.predict()
        self.assertEqual(response.json(), {'phrases': list(DEFAULT_PHRASES[:6])})

    def test_legacy_validation(self):
        for changes in ({'recent': None}, {'activity': ''}, {'time': 'noon'}, {'patient_id': str(uuid4())}):
            with self.subTest(changes=changes):
                self.assertEqual(self.predict(**changes).status_code, 400)
        self.assertEqual(self.client.post('/api/predict', {}, content_type='application/json').status_code, 400)
