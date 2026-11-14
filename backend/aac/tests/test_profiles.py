"""Real profile feature tests against migrated SQLite, with response schemas."""

from copy import deepcopy
from io import StringIO
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from jsonschema import Draft202012Validator, FormatChecker

from aac.models import CaregiverPatient, Profile
from aac.openapi import SCHEMAS, build_openapi
from aac.profiles import CURSOR_SALT


PREFERENCES = {
    'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'], 'default_activity': 'play',
}
SETUP = {
    'display_name': 'Demo patient', 'timezone': 'America/New_York',
    'language': 'en', 'preferences': PREFERENCES,
}


class ProfileFeatureTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.caregiver = Profile.objects.create(role='caregiver', display_name='Demo caregiver')
        self.other_caregiver = Profile.objects.create(role='caregiver', display_name='Other caregiver')

    def assert_schema(self, response, schema, status=200):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response['Content-Type'], 'application/json')
        Draft202012Validator(
            {'$ref': f'#/components/schemas/{schema}', 'components': {'schemas': SCHEMAS}},
            format_checker=FormatChecker(),
        ).validate(response.json())
        return response.json()

    def create_patient(self, caregiver=None, **changes):
        payload = {**deepcopy(SETUP), 'caregiver_id': str((caregiver or self.caregiver).pk), **changes}
        response = self.client.post('/api/profile/patients', payload, content_type='application/json')
        return self.assert_schema(response, 'Patient', 201)

    def error(self, response, status=400):
        result = self.assert_schema(response, 'Error', status)
        self.assertEqual(result['error']['code'], {400: 'invalid_request', 404: 'not_found', 405: 'method_not_allowed', 503: 'unavailable'}[status])
        return result

    def test_caregiver_create_persists_and_repeated_names_are_not_deduplicated(self):
        ids = []
        for _ in range(2):
            result = self.assert_schema(self.client.post(
                '/api/profile/caregivers', {'display_name': '  Café caregiver  '},
                content_type='application/json',
            ), 'Caregiver', 201)
            ids.append(result['id'])
            row = Profile.objects.get(pk=result['id'])
            self.assertEqual(row.display_name, 'Café caregiver')
            self.assertIsNone(row.preferences)
        self.assertNotEqual(*ids)

    def test_patient_create_read_and_complete_preferences_replacement(self):
        patient = self.create_patient()
        self.assertTrue(CaregiverPatient.objects.filter(caregiver=self.caregiver, patient_id=patient['id']).exists())
        url = '/api/profile/patients/' + patient['id']
        # A fresh client reads persisted setup, not an in-memory active patient.
        self.assertEqual(self.assert_schema(Client().get(url), 'Patient'), patient)
        replacement = {'scan_interval_ms': 300, 'input_modes': ['keyboard'], 'default_activity': 'lunch', 'voice_id': 'demo-voice'}
        response = self.client.patch(url, {
            'display_name': 'Updated', 'timezone': 'UTC', 'preferences': replacement,
        }, content_type='application/json')
        updated = self.assert_schema(response, 'Patient')
        self.assertEqual(updated['preferences'], replacement)
        self.assertEqual(updated['created_at'], patient['created_at'])
        self.assertEqual(updated['id'], patient['id'])
        self.assertEqual(updated['timezone'], 'UTC')
        self.assertEqual(Profile.objects.get(pk=patient['id']).display_name, 'Updated')
        self.assertEqual(self.assert_schema(self.client.get(url), 'Patient'), updated)

    def test_all_six_operations_have_success_contracts_without_501(self):
        operations = [op for path, methods in build_openapi()['paths'].items()
                      if path.startswith('/api/profile/') for op in methods.values()]
        self.assertEqual(len(operations), 6)
        for operation in operations:
            self.assertEqual(operation['x-implementation-status'], 'implemented')
            self.assertNotIn('501', operation['responses'])
            self.assertIn('503', operation['responses'])

    def test_invalid_caregiver_payloads_write_nothing(self):
        count = Profile.objects.count()
        for payload in ({}, {'display_name': ''}, {'display_name': None}, {'display_name': True},
                        {'display_name': ' '}, {'display_name': 'x' * 81},
                        {'display_name': 'Demo', 'role': 'patient'}, {'display_name': 'Demo', 'id': str(uuid4())}):
            with self.subTest(payload=payload):
                self.error(self.client.post('/api/profile/caregivers', payload, content_type='application/json'))
        self.assertEqual(Profile.objects.count(), count)

    def test_invalid_patient_fields_and_relationships(self):
        cases = [
            {'caregiver_id': 'bad'}, {'caregiver_id': str(uuid4())},
            {'role': 'caregiver'}, {'id': str(uuid4())}, {'timezone': 'Not/AZone'},
            {'timezone': None}, {'language': 'fr'}, {'language': True},
            {'display_name': ' '}, {'preferences': None}, {'preferences': {}},
        ]
        existing_patient = self.create_patient()
        cases.append({'caregiver_id': existing_patient['id']})
        before = Profile.objects.count()
        for changes in cases:
            payload = {**deepcopy(SETUP), 'caregiver_id': str(self.caregiver.pk), **changes}
            status = 404 if changes.get('caregiver_id') in (existing_patient['id'], str(UUID(int=0))) else 400
            if changes.get('caregiver_id') not in (None, 'bad', existing_patient['id']):
                status = 404
            with self.subTest(changes=changes):
                self.error(self.client.post('/api/profile/patients', payload, content_type='application/json'), status)
        self.error(self.client.post('/api/profile/patients', {}, content_type='application/json'))
        self.assertEqual(Profile.objects.count(), before)

    def test_invalid_preferences_and_immutable_patch_leave_existing_setup(self):
        patient = self.create_patient()
        url = '/api/profile/patients/' + patient['id']
        preference_changes = (
            {'scan_interval_ms': True}, {'scan_interval_ms': 1500.0}, {'scan_interval_ms': 299},
            {'scan_interval_ms': 10001}, {'input_modes': []}, {'input_modes': ['touch']},
            {'input_modes': ['keyboard', 'keyboard']}, {'input_modes': 'keyboard'},
            {'input_modes': [True]}, {'input_modes': [{}]}, {'default_activity': ' '},
            {'voice_id': None}, {'unexpected': True},
        )
        for changes in preference_changes:
            with self.subTest(changes=changes):
                self.error(self.client.patch(url, {'preferences': {**PREFERENCES, **changes}}, content_type='application/json'))
        for payload in ({}, {'id': str(uuid4())}, {'role': 'caregiver'},
                        {'caregiver_id': str(self.other_caregiver.pk)},
                        {'preferences': {'scan_interval_ms': 1500}}, {'language': None}):
            self.error(self.client.patch(url, payload, content_type='application/json'))
        self.assertEqual(self.assert_schema(self.client.get(url), 'Patient'), patient)

    def test_supported_preference_boundaries(self):
        for interval in (300, 10000):
            result = self.create_patient(preferences={**PREFERENCES, 'scan_interval_ms': interval})
            self.assertEqual(result['preferences']['scan_interval_ms'], interval)

    def test_role_scoped_read_update_delete_and_list(self):
        for identifier in (self.caregiver.pk, uuid4()):
            url = f'/api/profile/patients/{identifier}'
            self.error(self.client.get(url), 404)
            self.error(self.client.patch(url, {'display_name': 'No change'}, content_type='application/json'), 404)
            self.error(self.client.delete(url), 404)
        patient = self.create_patient()
        self.error(self.client.get(f"/api/profile/caregivers/{patient['id']}/patients"), 404)
        self.error(self.client.get(f'/api/profile/caregivers/{uuid4()}/patients'), 404)

    def test_pagination_is_stable_scoped_and_has_no_empty_terminal_page(self):
        ids = sorted(self.create_patient()['id'] for _ in range(3))
        other = self.create_patient(caregiver=self.other_caregiver)
        url = f'/api/profile/caregivers/{self.caregiver.pk}/patients'
        first = self.assert_schema(self.client.get(url, {'limit': 2}), 'PatientPage')
        self.assertEqual([row['id'] for row in first['patients']], ids[:2])
        self.assertIsInstance(first['next_cursor'], str)
        self.assertLessEqual(len(first['next_cursor']), 512)
        second = self.assert_schema(self.client.get(url, {'limit': 1, 'cursor': first['next_cursor']}), 'PatientPage')
        self.assertEqual([row['id'] for row in second['patients']], ids[2:])
        self.assertIsNone(second['next_cursor'])
        self.assertNotIn(other['id'], ids)
        empty = self.assert_schema(self.client.get(f'/api/profile/caregivers/{self.other_caregiver.pk}/patients'), 'PatientPage')
        self.assertEqual(len(empty['patients']), 1)
        for params in ({'cursor': first['next_cursor'] + 'x'}, {'cursor': ''}, {'cursor': 'x' * 513},
                       {'limit': 0}, {'limit': 101}, {'limit': 'true'}, {'unknown': 1}):
            self.error(self.client.get(url, params))
        self.error(self.client.get(url + '?limit=1&limit=2'))
        self.error(self.client.get(url + '?cursor=x&cursor=y'))
        self.error(self.client.get(f'/api/profile/caregivers/{self.other_caregiver.pk}/patients', {'cursor': first['next_cursor']}))
        for payload in ([], {'after': 'bad'},
                        {'caregiver': str(self.caregiver.pk), 'after': ids[0], 'order': 'wrong', 'version': 1}):
            self.error(self.client.get(url, {'cursor': signing.dumps(payload, salt=CURSOR_SALT)}))

    def test_empty_list_has_null_cursor(self):
        response = self.client.get(f'/api/profile/caregivers/{self.caregiver.pk}/patients')
        self.assertEqual(self.assert_schema(response, 'PatientPage'), {'patients': [], 'next_cursor': None})

    def test_delete_only_patient_and_its_links(self):
        patient = self.create_patient()
        other = self.create_patient()
        CaregiverPatient.objects.create(caregiver=self.other_caregiver, patient_id=patient['id'])
        response = self.client.delete('/api/profile/patients/' + patient['id'])
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.assertFalse(Profile.objects.filter(pk=patient['id']).exists())
        self.assertFalse(CaregiverPatient.objects.filter(patient_id=patient['id']).exists())
        self.assertTrue(Profile.objects.filter(pk=other['id']).exists())
        self.assertEqual(Profile.objects.filter(role='caregiver').count(), 2)

    def test_creation_rolls_back_when_link_storage_fails(self):
        count = Profile.objects.count()
        with patch('aac.views.CaregiverPatient.objects.create', side_effect=DatabaseError('private storage details')):
            response = self.client.post('/api/profile/patients', {**SETUP, 'caregiver_id': str(self.caregiver.pk)}, content_type='application/json')
        result = self.error(response, 503)
        self.assertNotIn('private', result['error']['message'])
        self.assertEqual(Profile.objects.count(), count)
        self.assertEqual(CaregiverPatient.objects.count(), 0)

    def test_required_database_failure_is_json_not_fabricated_success(self):
        with patch('aac.views.Profile.objects.get', side_effect=DatabaseError('private details')):
            response = self.client.get(f'/api/profile/patients/{uuid4()}')
        self.error(response, 503)
        self.assertNotIn(b'private', response.content)

    def test_methods_and_transport_checks_for_implemented_routes(self):
        patient = self.create_patient()
        urls = {
            '/api/profile/caregivers': {'POST', 'OPTIONS'},
            '/api/profile/patients': {'POST', 'OPTIONS'},
            f'/api/profile/caregivers/{self.caregiver.pk}/patients': {'GET', 'HEAD', 'OPTIONS'},
            '/api/profile/patients/' + patient['id']: {'GET', 'HEAD', 'PATCH', 'DELETE', 'OPTIONS'},
        }
        for url, methods in urls.items():
            response = self.client.put(url, '{', content_type='application/json')
            self.error(response, 405)
            self.assertEqual(set(response['Allow'].split(', ')), methods)
            self.assertEqual(self.client.options(url).status_code, 204)
            if 'HEAD' in methods:
                response = self.client.head(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'')
        for url, method in (('/api/profile/caregivers', 'post'), ('/api/profile/patients', 'post'),
                            ('/api/profile/patients/' + patient['id'], 'patch')):
            for body in ('{', '[]', 'null', '{"value":NaN}'):
                self.error(getattr(self.client, method)(url, body, content_type='application/json'))
            self.error(getattr(self.client, method)(url, '{}', content_type='text/plain'))

    def test_model_validation_rejects_invalid_links_and_role_mutation(self):
        patient = Profile.objects.create(role='patient', **deepcopy(SETUP))
        for caregiver, linked_patient in ((patient, self.caregiver), (self.caregiver, self.other_caregiver), (patient, patient)):
            with self.assertRaises(ValidationError):
                CaregiverPatient.objects.create(caregiver=caregiver, patient=linked_patient)
        CaregiverPatient.objects.create(caregiver=self.caregiver, patient=patient)
        with self.assertRaises(ValidationError):
            CaregiverPatient.objects.create(caregiver=self.caregiver, patient=patient)
        patient.role = 'caregiver'
        patient.timezone = patient.language = patient.preferences = None
        with self.assertRaises(ValidationError):
            patient.save()

    def test_database_constraints_even_when_model_clean_is_bypassed(self):
        for row in (Profile(role='invalid', display_name='Demo'),
                    Profile(role='caregiver', display_name=''),
                    Profile(role='patient', display_name='Demo'),
                    Profile(role='patient', display_name='Demo', timezone='UTC', preferences=PREFERENCES)):
            with self.subTest(role=row.role):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Profile.objects.bulk_create([row])


class DemoSeedTests(TestCase):
    def seed(self):
        call_command('seed_demo', stdout=StringIO())

    def test_seed_reruns_preserve_edits(self):
        self.seed()
        patient = Profile.objects.get(pk=settings.LEGACY_DEMO_PATIENT_ID)
        patient.display_name = 'Edited demo'
        patient.save()
        self.seed()
        patient.refresh_from_db()
        self.assertEqual(patient.display_name, 'Edited demo')
        self.assertEqual(Profile.objects.count(), 2)
        self.assertEqual(CaregiverPatient.objects.count(), 1)

    @override_settings(LEGACY_DEMO_PATIENT_ID=UUID('99999999-9999-4999-8999-999999999999'))
    def test_seed_honors_fixed_configured_legacy_patient(self):
        self.seed()
        self.assertTrue(Profile.objects.filter(pk=settings.LEGACY_DEMO_PATIENT_ID, role='patient').exists())

    def test_seed_conflict_rolls_back_new_caregiver(self):
        Profile.objects.create(pk=settings.LEGACY_DEMO_PATIENT_ID, role='caregiver', display_name='Existing')
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Profile.objects.count(), 1)
        self.assertEqual(CaregiverPatient.objects.count(), 0)
