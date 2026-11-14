"""Event recording, history pagination and legacy /api/log against migrated SQLite."""

from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError
from django.test import Client, TestCase
from jsonschema import Draft202012Validator, FormatChecker

from aac.history import CURSOR_SALT, time_bucket
from aac.models import CommunicationEvent, PredictionRecord, Profile
from aac.openapi import SCHEMAS

PREFERENCES = {'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'], 'default_activity': 'play'}
PHRASES = ['I want water', 'More please', 'I am hungry', 'All done', 'Help me', 'Thank you']


def make_patient(name='Demo patient', **extra):
    return Profile.objects.create(
        role='patient', display_name=name, timezone='America/New_York', language='en',
        preferences=PREFERENCES, **extra,
    )


class EventTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.patient = make_patient()
        self.other = make_patient('Other patient')
        self.prediction = PredictionRecord.objects.create(
            patient=self.patient, activity='lunch', time_bucket='midday', phrases=PHRASES, source='default',
        )

    def assert_schema(self, response, schema, status=200):
        self.assertEqual(response.status_code, status, response.content)
        Draft202012Validator(
            {'$ref': f'#/components/schemas/{schema}', 'components': {'schemas': SCHEMAS}},
            format_checker=FormatChecker(),
        ).validate(response.json())
        return response.json()

    def error(self, response, status=400):
        result = self.assert_schema(response, 'Error', status)
        self.assertEqual(result['error']['code'], {
            400: 'invalid_request', 404: 'not_found', 409: 'conflict', 503: 'unavailable',
        }[status])
        return result

    def payload(self, **changes):
        result = {
            'event_id': str(uuid4()), 'utterance_id': str(uuid4()), 'patient_id': str(self.patient.pk),
            'kind': 'spoken', 'text': 'I want water', 'timestamp': '2026-11-14T17:30:00Z',
            'activity': 'lunch', 'input_source': 'button',
        }
        result.update(changes)
        return {key: value for key, value in result.items() if value is not None}

    def post(self, payload):
        return self.client.post('/api/aac/events', payload, content_type='application/json')

    def history(self, patient=None, **params):
        return self.client.get(f'/api/aac/patients/{(patient or self.patient).pk}/events', params)

    def test_record_event_and_identical_retry(self):
        payload = self.payload(prediction_id=str(self.prediction.pk), candidate_index=0)
        receipt = self.assert_schema(self.post(payload), 'EventReceipt', 201)
        self.assertEqual(receipt, {'event_id': payload['event_id']})
        # Same normalized content: extra whitespace and an equivalent offset.
        retry = {**payload, 'text': '  I want water ', 'timestamp': '2026-11-14T12:30:00-05:00'}
        self.assertEqual(self.assert_schema(self.post(retry), 'EventReceipt', 200), receipt)
        self.assertEqual(CommunicationEvent.objects.count(), 1)
        event = CommunicationEvent.objects.get()
        self.assertEqual(event.occurred_at, datetime(2026, 11, 14, 17, 30, tzinfo=timezone.utc))
        self.assertEqual(event.time_bucket, 'midday')  # 12:30 in America/New_York

    def test_changed_retry_conflicts_without_writing(self):
        payload = self.payload()
        self.post(payload)
        for changes in ({'text': 'Help me'}, {'kind': 'selection'}, {'activity': 'play'},
                        {'timestamp': '2026-11-14T17:30:01Z'}, {'input_source': 'keyboard'},
                        {'patient_id': str(self.other.pk)}):
            with self.subTest(changes=changes):
                self.error(self.post({**payload, **changes}), 409)
        self.error(self.post({key: value for key, value in payload.items() if key != 'activity'}), 409)
        self.assertEqual(CommunicationEvent.objects.count(), 1)

    def test_utterance_links_kinds_but_allows_one_spoken(self):
        utterance = str(uuid4())
        attributed = {'prediction_id': str(self.prediction.pk), 'candidate_index': 0}
        self.assert_schema(self.post(self.payload(utterance_id=utterance, kind='selection')), 'EventReceipt', 201)
        self.assert_schema(self.post(self.payload(utterance_id=utterance)), 'EventReceipt', 201)
        self.assert_schema(self.post(self.payload(
            utterance_id=utterance, kind='feedback', outcome='accepted', **attributed,
        )), 'EventReceipt', 201)
        self.error(self.post(self.payload(utterance_id=utterance)), 409)
        self.error(self.post(self.payload(utterance_id=utterance, patient_id=str(self.other.pk), kind='selection')), 409)
        # Intentional repeated speech uses new IDs and is preserved.
        self.assert_schema(self.post(self.payload()), 'EventReceipt', 201)
        self.assertEqual(CommunicationEvent.objects.filter(kind='spoken', text='I want water').count(), 2)

    def test_prediction_attribution_is_patient_scoped_and_exact(self):
        other_prediction = PredictionRecord.objects.create(
            patient=self.other, time_bucket='midday', phrases=PHRASES, source='default',
        )
        self.error(self.post(self.payload(prediction_id=str(uuid4()), candidate_index=0)), 404)
        self.error(self.post(self.payload(prediction_id=str(other_prediction.pk), candidate_index=0)), 404)
        self.error(self.post(self.payload(prediction_id=str(self.prediction.pk), candidate_index=1)), 400)
        self.error(self.post(self.payload(prediction_id=str(self.prediction.pk), candidate_index=0, text='i want water')), 400)
        self.assert_schema(self.post(self.payload(
            prediction_id=str(self.prediction.pk), candidate_index=4, text='Help me',
        )), 'EventReceipt', 201)
        self.assertEqual(CommunicationEvent.objects.count(), 1)

    def test_invalid_events_write_nothing(self):
        attributed = {'prediction_id': str(self.prediction.pk), 'candidate_index': 0}
        cases = [
            {'kind': 'typed'}, {'kind': None}, {'event_id': 'bad'}, {'utterance_id': None},
            {'patient_id': None}, {'text': ' '}, {'text': 'x' * 501}, {'text': 3},
            {'timestamp': '2026-11-14T17:30:00'}, {'timestamp': '2026-11-14'},
            {'input_source': 'touch'}, {'input_source': None}, {'activity': ''}, {'activity': 'x' * 101},
            {'unknown': True}, {'outcome': 'accepted'}, {'received_at': '2026-11-14T17:30:00Z'},
            {'prediction_id': str(self.prediction.pk)}, {'candidate_index': 0},
            {**attributed, 'candidate_index': 6}, {**attributed, 'candidate_index': True},
            {**attributed, 'candidate_index': -1},
            {'kind': 'feedback', 'outcome': 'accepted'},
            {'kind': 'feedback', **attributed}, {'kind': 'feedback', 'outcome': 'maybe', **attributed},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                payload = self.payload(**{key: value for key, value in changes.items() if value is not None})
                for key, value in changes.items():
                    if value is None:
                        payload.pop(key, None)
                self.error(self.post(payload))
        self.error(self.post({}))
        self.assertEqual(CommunicationEvent.objects.count(), 0)

    def test_unknown_or_caregiver_patient_is_not_found(self):
        caregiver = Profile.objects.create(role='caregiver', display_name='Caregiver')
        for identifier in (uuid4(), caregiver.pk):
            self.error(self.post(self.payload(patient_id=str(identifier))), 404)
            self.error(self.history(patient=Profile(pk=identifier)), 404)

    def test_concurrent_conflicting_insert_is_409_not_503(self):
        with patch('aac.views.CommunicationEvent.objects.create', side_effect=IntegrityError('private')):
            result = self.error(self.post(self.payload()), 409)
        self.assertNotIn('private', result['error']['message'])

    def test_storage_failure_is_503_without_details(self):
        with patch('aac.views.CommunicationEvent.objects.create', side_effect=DatabaseError('private')):
            result = self.error(self.post(self.payload()), 503)
        self.assertNotIn('private', result['error']['message'])
        with patch('aac.views.Profile.objects.get', side_effect=DatabaseError('private')):
            self.error(self.history(), 503)

    def test_history_is_newest_first_paginated_and_isolated(self):
        times = ['2026-11-14T10:00:00Z', '2026-11-14T12:00:00Z', '2026-11-14T12:00:00Z', '2026-11-13T09:00:00Z']
        for moment in times:
            self.post(self.payload(timestamp=moment))
        self.post(self.payload(patient_id=str(self.other.pk)))
        expected = [str(event.pk) for event in CommunicationEvent.objects.filter(
            patient=self.patient).order_by('-occurred_at', '-id')]
        first = self.assert_schema(self.history(limit=3), 'EventPage')
        self.assertEqual([row['event_id'] for row in first['events']], expected[:3])
        self.assertEqual(first['events'][0]['timestamp'], '2026-11-14T12:00:00+00:00')
        second = self.assert_schema(self.history(limit=3, cursor=first['next_cursor']), 'EventPage')
        self.assertEqual([row['event_id'] for row in second['events']], expected[3:])
        self.assertIsNone(second['next_cursor'])
        self.error(self.history(patient=self.other, cursor=first['next_cursor']))
        for params in ({'cursor': first['next_cursor'] + 'x'}, {'cursor': ''}, {'limit': 0},
                       {'limit': 101}, {'unknown': 1}):
            self.error(self.history(**params))
        self.error(self.client.get(f'/api/aac/patients/{self.patient.pk}/events?cursor=a&cursor=b'))
        forged = signing.dumps({'patient': str(self.patient.pk), 'timestamp': 'bad', 'event': expected[0],
                                'order': 'timestamp_desc', 'version': 1}, salt=CURSOR_SALT)
        self.error(self.history(cursor=forged))
        other = self.assert_schema(self.history(patient=self.other), 'EventPage')
        self.assertEqual(len(other['events']), 1)

    def test_empty_history(self):
        self.assertEqual(self.assert_schema(self.history(), 'EventPage'), {'events': [], 'next_cursor': None})

    def test_patient_deletion_removes_only_their_events_and_predictions(self):
        self.post(self.payload(prediction_id=str(self.prediction.pk), candidate_index=0))
        self.post(self.payload(patient_id=str(self.other.pk)))
        self.assertEqual(self.client.delete(f'/api/profile/patients/{self.patient.pk}').status_code, 204)
        self.assertFalse(CommunicationEvent.objects.filter(patient_id=self.patient.pk).exists())
        self.assertFalse(PredictionRecord.objects.filter(patient_id=self.patient.pk).exists())
        self.assertEqual(CommunicationEvent.objects.filter(patient=self.other).count(), 1)

    def test_time_bucket_boundaries_use_patient_timezone(self):
        cases = [(4, 'night'), (5, 'morning'), (10, 'morning'), (11, 'midday'), (14, 'afternoon'),
                 (17, 'evening'), (20, 'evening'), (21, 'night'), (23, 'night')]
        for hour, bucket in cases:
            moment = datetime(2026, 7, 1, hour, tzinfo=timezone.utc)
            self.assertEqual(time_bucket(moment, 'UTC'), bucket)
        # 01:00 UTC is 21:00 the previous evening in New York (EDT).
        self.assertEqual(time_bucket(datetime(2026, 7, 1, 1, tzinfo=timezone.utc), 'America/New_York'), 'night')
        self.assertEqual(time_bucket(datetime(2026, 7, 1, 0, tzinfo=timezone.utc), 'America/New_York'), 'evening')


class LegacyLogTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def log(self, payload):
        return self.client.post('/api/log', payload, content_type='application/json')

    def test_log_saves_spoken_event_for_fixed_demo_patient(self):
        patient = make_patient(pk=settings.LEGACY_DEMO_PATIENT_ID)
        payload = {'text': ' More please ', 'timestamp': '2026-11-14T13:00:00Z'}
        for _ in range(2):  # No retry key: repeats are separate utterances.
            response = self.log(payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'ok': True})
        events = CommunicationEvent.objects.filter(patient=patient)
        self.assertEqual(events.count(), 2)
        self.assertEqual(len({event.utterance_id for event in events}), 2)
        event = events.first()
        self.assertEqual((event.kind, event.text, event.input_source, event.activity, event.time_bucket),
                         ('spoken', 'More please', None, None, 'morning'))
        page = self.client.get(f'/api/aac/patients/{patient.pk}/events').json()
        Draft202012Validator(
            {'$ref': '#/components/schemas/EventPage', 'components': {'schemas': SCHEMAS}},
        ).validate(page)

    def test_log_validation_and_missing_demo_patient(self):
        make_patient(pk=settings.LEGACY_DEMO_PATIENT_ID)
        for payload in ({}, {'text': 'Hi'}, {'text': ' ', 'timestamp': '2026-11-14T13:00:00Z'},
                        {'text': 'Hi', 'timestamp': '2026-11-14'}, {'text': 'Hi', 'timestamp': '2026-11-14T13:00:00Z', 'x': 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.log(payload).status_code, 400)
        Profile.objects.all().delete()
        response = self.log({'text': 'Hi', 'timestamp': '2026-11-14T13:00:00Z'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'unavailable')
        self.assertEqual(CommunicationEvent.objects.count(), 0)


class SeedHistoryTests(TestCase):
    def test_seed_history_is_idempotent_and_confirmed_speech(self):
        for _ in range(2):
            call_command('seed_demo', stdout=StringIO())
        events = CommunicationEvent.objects.filter(patient_id=settings.LEGACY_DEMO_PATIENT_ID)
        self.assertEqual(events.count(), 20)
        self.assertEqual(set(events.values_list('kind', flat=True)), {'spoken'})
        self.assertEqual(events.values('utterance_id').distinct().count(), 20)
        breakfast = events.filter(activity='breakfast').values_list('time_bucket', flat=True)
        self.assertEqual(set(breakfast), {'morning'})
        events.filter(text='Good night').delete()
        call_command('seed_demo', stdout=StringIO())
        self.assertEqual(events.count(), 20)  # Deleted rows are re-created; others untouched.
