"""Runtime configuration and browser CORS; no database or cloud access."""

import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[2]
SETTINGS_FILE = BACKEND_DIR / 'config' / 'settings.py'


class RuntimeSettingsTests(SimpleTestCase):
    def read_settings(self, environment=None, dotenv_loader=None):
        # Never read the developer's real .env or inherit credentials/config.
        with patch.dict(os.environ, environment or {}, clear=True):
            with patch('dotenv.load_dotenv', side_effect=dotenv_loader) as loader:
                values = runpy.run_path(str(SETTINGS_FILE))
                loader.assert_called_once_with(BACKEND_DIR / '.env', override=False)
                return values

    def test_local_defaults(self):
        values = self.read_settings()
        self.assertTrue(values['DEBUG'])
        self.assertEqual(values['ALLOWED_HOSTS'], ['localhost', '127.0.0.1', '[::1]'])
        self.assertEqual(values['BACKEND_PUBLIC_BASE_URL'], 'http://localhost:8000')
        self.assertEqual(values['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(values['DATABASES']['default']['NAME'], BACKEND_DIR / 'db.sqlite3')
        self.assertEqual(values['MEDIA_ROOT'], BACKEND_DIR / 'media')
        self.assertEqual(values['STATIC_ROOT'], BACKEND_DIR / 'staticfiles')
        self.assertEqual(values['MEDIA_URL'], '/media/')
        self.assertEqual(values['STATIC_URL'], '/static/')
        self.assertEqual(values['ASGI_APPLICATION'], 'config.asgi.application')
        self.assertEqual(values['CORS_ALLOWED_ORIGINS'], ['http://localhost:5173'])
        self.assertEqual(values['LEGACY_DEMO_PATIENT_ID'], UUID('22222222-2222-4222-8222-222222222222'))
        middleware = values['MIDDLEWARE']
        self.assertLess(
            middleware.index('corsheaders.middleware.CorsMiddleware'),
            middleware.index('django.middleware.common.CommonMiddleware'),
        )

    def test_environment_values_and_absolute_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            values = self.read_settings({
                'DJANGO_DEBUG': 'false',
                'DJANGO_SECRET_KEY': 'synthetic-test-key-not-a-real-secret',
                'DJANGO_ALLOWED_HOSTS': ' localhost, 192.0.2.1, ,',
                'SQLITE_PATH': str(root / 'device.sqlite3'),
                'MEDIA_ROOT': str(root / 'audio'),
                'STATIC_ROOT': str(root / 'static'),
                'BACKEND_PUBLIC_BASE_URL': 'http://192.0.2.1:8000/',
            })
            self.assertFalse(values['DEBUG'])
            self.assertEqual(values['SECRET_KEY'], 'synthetic-test-key-not-a-real-secret')
            self.assertEqual(values['ALLOWED_HOSTS'], ['localhost', '192.0.2.1'])
            self.assertEqual(values['DATABASES']['default']['NAME'], root / 'device.sqlite3')
            self.assertEqual(values['MEDIA_ROOT'], root / 'audio')
            self.assertEqual(values['STATIC_ROOT'], root / 'static')
            self.assertEqual(values['BACKEND_PUBLIC_BASE_URL'], 'http://192.0.2.1:8000')

    def test_relative_paths_are_backend_relative(self):
        values = self.read_settings({
            'SQLITE_PATH': 'data/device.sqlite3',
            'MEDIA_ROOT': 'data/media',
            'STATIC_ROOT': 'data/static',
        })
        self.assertEqual(values['DATABASES']['default']['NAME'], BACKEND_DIR / 'data/device.sqlite3')
        self.assertEqual(values['MEDIA_ROOT'], BACKEND_DIR / 'data/media')
        self.assertEqual(values['STATIC_ROOT'], BACKEND_DIR / 'data/static')

    def test_speech_and_casting_settings(self):
        values = self.read_settings()
        self.assertEqual((values['SPEECH_PROVIDER'], values['SPEECH_VOICE_ID'], values['SPEECH_MODEL_ID']),
                         ('elevenlabs', '', ''))
        self.assertTrue(values['SPEECH_CACHE'])
        self.assertEqual((values['ELEVENLABS_API_KEY'], values['GOOGLE_HOME_HOST']), ('', ''))
        values = self.read_settings({
            'SPEECH_PROVIDER': ' ElevenLabs ', 'SPEECH_VOICE_ID': 'voice', 'SPEECH_CACHE': 'false',
            'GOOGLE_HOME_HOST': '192.0.2.50', 'BACKEND_PUBLIC_BASE_URL': 'http://192.0.2.1:8000',
        })
        self.assertEqual((values['SPEECH_PROVIDER'], values['SPEECH_CACHE'], values['GOOGLE_HOME_HOST']),
                         ('elevenlabs', False, '192.0.2.50'))

    def test_configured_legacy_demo_patient_id(self):
        values = self.read_settings({'LEGACY_DEMO_PATIENT_ID': '99999999-9999-4999-8999-999999999999'})
        self.assertEqual(values['LEGACY_DEMO_PATIENT_ID'], UUID('99999999-9999-4999-8999-999999999999'))

    def test_dotenv_loads_without_overriding_process_environment(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text(
                'DJANGO_DEBUG=false\n'
                'DJANGO_SECRET_KEY=synthetic-file-key\n'
                'MEDIA_ROOT=file-media\n'
                'BACKEND_PUBLIC_BASE_URL=http://file.example:8000\n',
                encoding='utf-8',
            )

            def isolated_dotenv(path, override):
                return load_dotenv(env_file, override=override)

            values = self.read_settings(
                {'BACKEND_PUBLIC_BASE_URL': 'https://process.example'},
                dotenv_loader=isolated_dotenv,
            )
            self.assertFalse(values['DEBUG'])
            self.assertEqual(values['SECRET_KEY'], 'synthetic-file-key')
            self.assertEqual(values['MEDIA_ROOT'], BACKEND_DIR / 'file-media')
            self.assertEqual(values['BACKEND_PUBLIC_BASE_URL'], 'https://process.example')

    def test_invalid_settings_fail_without_echoing_values(self):
        cases = [
            {'DJANGO_DEBUG': 'not-a-boolean'},
            {'DJANGO_DEBUG': 'false'},
            {'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': 'django-insecure-local-development-only'},
            *[{name: ' '} for name in ('SQLITE_PATH', 'MEDIA_ROOT', 'STATIC_ROOT')],
            *[{'BACKEND_PUBLIC_BASE_URL': value} for value in (
                '', '/relative', 'ftp://example.com', 'http://',
                'http://user:private@example.com', 'http://example.com?secret=private',
                'http://example.com#private', 'http://example.com:invalid',
                'http://example.com:99999', 'http://[invalid', 'http://bad host',
            )],
            *[{'LEGACY_DEMO_PATIENT_ID': value} for value in ('', 'private-not-a-uuid')],
            {'SPEECH_CACHE': 'private'},
            *[{'GOOGLE_HOME_HOST': '192.0.2.50', 'BACKEND_PUBLIC_BASE_URL': url}
              for url in ('http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::1]:8000')],
        ]
        for environment in cases:
            with self.subTest(setting=next(iter(environment))):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    self.read_settings(environment)
                self.assertNotIn('private', str(raised.exception))


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1', '[::1]'],
    DEBUG=False,
    CORS_ALLOWED_ORIGINS=['http://localhost:5173'],
    CORS_URLS_REGEX=r'^/api/',
)
class DevelopmentCorsTests(SimpleTestCase):
    def test_preflight_accepts_frontend_json_post(self):
        response = self.client.options(
            '/api/predict',
            HTTP_ORIGIN='http://localhost:5173',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:5173')
        self.assertIn('POST', response['Access-Control-Allow-Methods'])
        self.assertIn('content-type', response['Access-Control-Allow-Headers'])
        self.assertNotIn('Access-Control-Allow-Credentials', response)

    def test_cors_headers_preserve_actual_scaffold_and_transport_errors(self):
        for body, content_type, status in (
            ('{}', 'application/json', 501),
            ('{', 'application/json', 400),
        ):
            with self.subTest(status=status):
                response = self.client.post(
                    '/api/learn/analyze', body, content_type=content_type,
                    HTTP_ORIGIN='http://localhost:5173',
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:5173')
                self.assertEqual(response['Content-Type'], 'application/json')

    def test_other_origins_receive_no_cors_permission(self):
        for origin in ('https://untrusted.example', 'http://localhost:5174', 'null'):
            with self.subTest(origin=origin):
                response = self.client.get('/api/openapi.json', HTTP_ORIGIN=origin)
                self.assertEqual(response.status_code, 200)  # CORS is not authentication.
                self.assertNotIn('Access-Control-Allow-Origin', response)

    def test_nonbrowser_and_nonapi_requests_do_not_get_cors_headers(self):
        response = self.client.get('/api/openapi.json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', response)
        response = self.client.get('/missing', HTTP_ORIGIN='http://localhost:5173')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('Access-Control-Allow-Origin', response)

    def test_localhost_allowed_and_unlisted_host_rejected(self):
        self.assertEqual(
            self.client.get('/api/docs', HTTP_HOST='localhost:8000').status_code, 200
        )
        self.assertEqual(
            self.client.get('/api/docs', HTTP_HOST='untrusted.example').status_code, 400
        )
