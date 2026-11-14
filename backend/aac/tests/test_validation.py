"""Value/transport helpers; no database or implemented business route claims."""

from datetime import datetime, timezone
import json
from uuid import UUID

from django.http import JsonResponse, QueryDict
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from jsonschema import Draft202012Validator

from aac.http import MAX_JSON_BYTES, check_method, error_response, read_json_object
from aac.openapi import IDS, SCHEMAS
from aac.validation import (
    InvalidRequest, query_limit, validate_fields, validate_integer,
    validate_string, validate_timestamp, validate_timezone, validate_uuid,
)


def validation_probe(request):
    """Test-only view illustrating explicit helper composition, not an API route."""
    response = check_method(request, ('POST',))
    if response is not None:
        return response
    try:
        payload = read_json_object(request)
        validate_fields(payload, allowed={'display_name'}, required={'display_name'})
        name = validate_string(payload['display_name'], 'display_name', max_length=80)
    except InvalidRequest as error:
        return error_response('invalid_request', str(error), 400)
    return JsonResponse({'display_name': name})


urlpatterns = [path('probe', validation_probe)]


class ValueValidationTests(SimpleTestCase):
    def test_required_unknown_and_empty_fields(self):
        payload = {'name': 'Demo'}
        self.assertIs(validate_fields(payload, allowed={'name'}, required={'name'}), payload)
        self.assertEqual(validate_fields({}, allowed={'name'}), {})
        for invalid, kwargs in (
            ([], {}), (None, {}),
            ({}, {'required': {'name'}}),
            ({'unexpected-private-content': 'private'}, {}),
            ({}, {'require_nonempty': True}),
        ):
            with self.subTest(payload_type=type(invalid).__name__):
                with self.assertRaises(InvalidRequest) as raised:
                    validate_fields(invalid, allowed={'name'}, **kwargs)
                self.assertNotIn('private', str(raised.exception))

    def test_strings_are_strict_bounded_and_unicode_preserving(self):
        self.assertEqual(validate_string('  Café 👋  ', 'name', max_length=80), 'Café 👋')
        self.assertEqual(validate_string(' x ', 'text', max_length=3, trim=False), ' x ')
        for value in (None, True, 1, [], {}, '', ' \t\n', 'long', ' x  '):
            with self.subTest(value=value):
                with self.assertRaises(InvalidRequest):
                    validate_string(value, 'name', max_length=3)

    def test_uuid_requires_wire_format_without_coercion(self):
        identifier = IDS['patient']
        self.assertEqual(validate_uuid(identifier, 'patient_id'), UUID(identifier))
        uppercase = 'abcdefab-1234-4567-89ab-abcdefabcdef'.upper()
        self.assertEqual(str(validate_uuid(uppercase, 'id')), uppercase.lower())
        for value in (None, 1, UUID(identifier), identifier.replace('-', ''),
                      '{' + identifier + '}', 'urn:uuid:' + identifier,
                      identifier + ' ', 'not-a-uuid'):
            with self.subTest(value=value):
                with self.assertRaises(InvalidRequest):
                    validate_uuid(value, 'patient_id')

    def test_timestamps_require_offsets_and_normalize_to_utc(self):
        expected = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
        for value in ('2026-11-14T12:00:00Z', '2026-11-14t12:00:00z',
                      '2026-11-14T07:00:00-05:00', '2026-11-14T17:30:00+05:30'):
            with self.subTest(value=value):
                self.assertEqual(validate_timestamp(value, 'time'), expected)
        fractional = validate_timestamp('2026-11-14T12:00:00.123456Z', 'time')
        self.assertEqual(fractional.microsecond, 123456)
        self.assertIs(fractional.tzinfo, timezone.utc)

    def test_invalid_timestamps_and_utc_overflow_are_safe(self):
        for value in (None, 1, True, '2026-11-14', '2026-11-14T12:00:00',
                      '2026-11-14 12:00:00Z', '2026-11-14T12:00Z',
                      '2026-02-30T12:00:00Z', '2026-11-14T24:00:00Z',
                      '2026-11-14T12:00:00+24:00', '2026-11-14T12:00:00+00:60',
                      '2026-11-14T12:00:00+0500', '2026-11-14T12:00:00Z ',
                      '0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'):
            with self.subTest(value=value):
                with self.assertRaises(InvalidRequest):
                    validate_timestamp(value, 'timestamp')

    def test_iana_timezones_not_machine_paths_or_offsets(self):
        for value in ('UTC', 'America/New_York', 'Asia/Kolkata'):
            self.assertEqual(validate_timezone(value).key, value)
        for value in (None, True, '', ' ', 'Not/AZone', '/etc/passwd',
                      '../UTC', '+05:30', ' America/New_York '):
            with self.subTest(value=value):
                with self.assertRaises(InvalidRequest):
                    validate_timezone(value)

    def test_json_integer_rejects_boolean_float_and_string(self):
        for value in (300, 1500, 10000):
            self.assertEqual(validate_integer(value, 'scan_interval_ms', minimum=300, maximum=10000), value)
        for value in (None, True, False, '1500', 1500.0, 299, 10001):
            with self.subTest(value=value):
                with self.assertRaises(InvalidRequest):
                    validate_integer(value, 'scan_interval_ms', minimum=300, maximum=10000)

    def test_query_limit_defaults_bounds_and_ambiguity(self):
        self.assertEqual(query_limit(QueryDict('')), 50)
        for raw, expected in (('1', 1), ('50', 50), ('100', 100), ('050', 50)):
            self.assertEqual(query_limit(QueryDict('limit=' + raw)), expected)
        for query in ('limit=', 'limit=0', 'limit=101', 'limit=-1', 'limit=true',
                      'limit=1.0', 'limit=1e2', 'limit=%2B1', 'limit=%201',
                      'limit=１', 'limit=1&limit=2', 'limit=50&limit=50',
                      'limit=' + '9' * 5000):
            with self.subTest(query=query[:40]):
                with self.assertRaises(InvalidRequest):
                    query_limit(QueryDict(query))


class JsonTransportTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_original_object_for_real_views(self):
        payload = {'name': 'Café', 'nested': {'count': 2}, 'values': [True, None]}
        request = self.factory.post('/probe', json.dumps(payload), content_type='application/json; charset=utf-8')
        self.assertEqual(read_json_object(request), payload)
        self.assertEqual(read_json_object(request), payload)  # Cached Django body.

    def test_body_limit_boundary(self):
        body = b'{"text":"' + b'x' * (MAX_JSON_BYTES - 11) + b'"}'
        self.assertEqual(len(body), MAX_JSON_BYTES)
        request = self.factory.post('/probe', body, content_type='application/json')
        self.assertIsInstance(read_json_object(request), dict)
        request = self.factory.post('/probe', body + b' ', content_type='application/json')
        with self.assertRaises(InvalidRequest):
            read_json_object(request)

    def test_django_request_limit_is_translated(self):
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
            request = self.factory.post('/probe', '{"name":"long"}', content_type='application/json')
            with self.assertRaisesMessage(InvalidRequest, 'request limit'):
                read_json_object(request)


@override_settings(ROOT_URLCONF=__name__)
class ValidationViewIntegrationTests(SimpleTestCase):
    def test_helpers_deliver_data_to_a_plain_view(self):
        response = self.client.post('/probe', {'display_name': '  Demo  '}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'display_name': 'Demo'})

    def test_transport_and_field_errors_keep_contract_envelope(self):
        for body, content_type in (
            ('{', 'application/json'), ('[]', 'application/json'),
            ('{}', 'text/plain'), ('{}', 'application/json'),
            ('{"display_name": true}', 'application/json'),
            ('{"display_name": " "}', 'application/json'),
            ('{"display_name": "Demo", "role": "patient"}', 'application/json'),
        ):
            with self.subTest(body=body):
                response = self.client.post('/probe', body, content_type=content_type)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'invalid_request')
                Draft202012Validator(SCHEMAS['Error']).validate(response.json())
                self.assertEqual(response['Cache-Control'], 'no-store')

    def test_method_checks_precede_body_parsing(self):
        response = self.client.put('/probe', '{', content_type='application/json')
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'POST, OPTIONS')
        response = self.client.options('/probe')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['Allow'], 'POST, OPTIONS')
        self.assertEqual(response.content, b'')
