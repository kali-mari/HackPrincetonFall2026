"""Speech endpoints, provider-neutral caching/storage, cleanup and casting; no network."""

import io
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
from unittest.mock import Mock, patch
import urllib.error
from uuid import uuid4

from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from jsonschema import Draft202012Validator, FormatChecker

from aac import casting, speech
from aac.models import CommunicationEvent, Profile
from aac.openapi import SCHEMAS
from aac.speech import SpeechUnavailable

PREFERENCES = {'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'], 'default_activity': 'play'}
AUDIO = b'ID3 fake mp3 bytes'
URL = re.compile(r'^http://192\.0\.2\.1:8000/media/audio/([0-9a-f]{32}|[0-9a-f]{64})\.mp3$')


def make_patient(**extra):
    return Profile.objects.create(
        role='patient', display_name='Demo patient', timezone='UTC', language='en', **extra,
    )


class SpeechTestCase(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media = Path(directory.name)
        self.provider = Mock(return_value=AUDIO)
        for context in (
            override_settings(
                MEDIA_ROOT=self.media, SPEECH_PROVIDER='fake', SPEECH_VOICE_ID='default-voice',
                SPEECH_MODEL_ID='', SPEECH_CACHE=True, GOOGLE_HOME_HOST='',
                BACKEND_PUBLIC_BASE_URL='http://192.0.2.1:8000',
            ),
            patch.dict(speech.PROVIDERS, {'fake': self.provider}),
        ):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def files(self):
        return sorted(path.name for path in (self.media / 'audio').glob('*')) if (self.media / 'audio').exists() else []


class SpeakEndpointTests(SpeechTestCase):
    def setUp(self):
        super().setUp()
        self.patient = make_patient(preferences=PREFERENCES)

    def speak(self, text='I want water', patient=None, **changes):
        payload = {'patient_id': str((patient or self.patient).pk), 'text': text, **changes}
        return self.client.post('/api/aac/speak', payload, content_type='application/json')

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        Draft202012Validator(
            {'$ref': '#/components/schemas/SpeakResponse', 'components': {'schemas': SCHEMAS}},
            format_checker=FormatChecker(),
        ).validate(response.json())
        self.assertRegex(response.json()['audio_url'], URL)
        return response.json()['audio_url']

    def test_speech_writes_audio_and_records_no_event(self):
        url = self.ok(self.speak('  I want water '))
        self.provider.assert_called_once_with('I want water', 'default-voice', '')
        self.assertEqual((self.media / 'audio' / url.rsplit('/', 1)[1]).read_bytes(), AUDIO)
        self.assertEqual(CommunicationEvent.objects.count(), 0)

    def test_patient_voice_overrides_default(self):
        patient = make_patient(preferences={**PREFERENCES, 'voice_id': 'child-voice'})
        self.ok(self.speak(patient=patient))
        self.assertEqual(self.provider.call_args.args[1], 'child-voice')

    def test_cache_reuses_identical_audio_only(self):
        first = self.ok(self.speak())
        self.assertEqual(self.ok(self.speak()), first)
        self.assertEqual(self.provider.call_count, 1)
        self.assertNotEqual(self.ok(self.speak('Help me')), first)
        patient = make_patient(preferences={**PREFERENCES, 'voice_id': 'child-voice'})
        self.assertNotEqual(self.ok(self.speak(patient=patient)), first)
        with override_settings(SPEECH_MODEL_ID='other-model'):
            self.assertNotEqual(self.ok(self.speak()), first)
        self.assertEqual(self.provider.call_count, 4)
        self.assertFalse(any(name.endswith('.tmp') for name in self.files()))

    def test_disabled_cache_uses_new_random_files(self):
        with override_settings(SPEECH_CACHE=False):
            urls = {self.ok(self.speak()) for _ in range(2)}
        self.assertEqual(len(urls), 2)
        self.assertEqual(self.provider.call_count, 2)

    def test_filename_never_contains_text(self):
        url = self.ok(self.speak('../../etc/passwd'))
        self.assertNotIn('passwd', url)
        self.assertEqual(len(self.files()), 1)

    def test_failures_are_503_without_files_or_details(self):
        cases = [
            ({}, Mock(side_effect=SpeechUnavailable('Speech is unavailable.'))),
            ({}, Mock(return_value=b'')),
            ({}, Mock(return_value=b'x' * (speech.MAX_AUDIO_BYTES + 1))),
            ({'SPEECH_VOICE_ID': ''}, self.provider),
            ({'SPEECH_PROVIDER': 'missing'}, self.provider),
        ]
        for overrides, provider in cases:
            with self.subTest(overrides=overrides), override_settings(**overrides), \
                    patch.dict(speech.PROVIDERS, {'fake': provider}):
                response = self.speak()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['error']['code'], 'unavailable')
                self.assertNotIn('I want water', response.content.decode())
        self.assertEqual(self.files(), [])

    def test_storage_failure_is_503(self):
        (self.media / 'audio').write_text('not a directory')
        response = self.speak()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['message'], 'Audio storage is unavailable.')

    def test_validation_and_missing_patient(self):
        for payload in ({}, {'text': 'Hi'}, {'patient_id': 'bad', 'text': 'Hi'},
                        {'patient_id': str(self.patient.pk), 'text': ' '},
                        {'patient_id': str(self.patient.pk), 'text': 'x' * 501},
                        {'patient_id': str(self.patient.pk), 'text': 'Hi', 'voice_id': 'x'}):
            with self.subTest(payload=payload):
                response = self.client.post('/api/aac/speak', payload, content_type='application/json')
                self.assertEqual(response.status_code, 400)
        caregiver = Profile.objects.create(role='caregiver', display_name='Caregiver')
        for identifier in (uuid4(), caregiver.pk):
            self.assertEqual(self.client.post('/api/aac/speak', {'patient_id': str(identifier), 'text': 'Hi'},
                                              content_type='application/json').status_code, 404)
        self.provider.assert_not_called()

    def test_casts_when_configured_without_changing_response(self):
        with patch('aac.views.cast_audio') as cast:
            url = self.ok(self.speak())
        cast.assert_called_once_with(url)
        with patch('aac.views.cast_audio') as cast:
            self.speak(text=' ')
        cast.assert_not_called()

    def test_listen_mode_hears_silence_while_the_clip_plays(self):
        self.provider.return_value = b'x' * 32_000  # 2 seconds at 128 kbit/s
        for cast_started, margin in ((False, 1.5), (True, 4)):
            with self.subTest(cast=cast_started), patch('aac.views.cast_audio', return_value=cast_started), \
                    patch('aac.views.listen.pause') as pause:
                self.ok(self.speak())
            pause.assert_called_once_with(2.0 + margin)
        with patch('aac.views.listen.pause') as pause:
            self.speak(text=' ')
        pause.assert_not_called()


class LegacySpeakTests(SpeechTestCase):
    def speak(self, payload):
        return self.client.post('/api/speak', payload, content_type='application/json')

    def test_legacy_shape_with_and_without_demo_patient(self):
        response = self.speak({'text': 'Thank you'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'audio_url'})
        self.assertEqual(self.provider.call_args.args[1], 'default-voice')
        make_patient(pk=settings.LEGACY_DEMO_PATIENT_ID, preferences={**PREFERENCES, 'voice_id': 'demo-voice'})
        self.speak({'text': 'Thank you'})
        self.assertEqual(self.provider.call_args.args[1], 'demo-voice')

    def test_legacy_validation(self):
        for payload in ({}, {'text': ''}, {'text': 'Hi', 'patient_id': str(uuid4())}):
            self.assertEqual(self.speak(payload).status_code, 400)


class ElevenLabsProviderTests(TestCase):
    @override_settings(ELEVENLABS_API_KEY='synthetic-test-key')
    def test_request_shape(self):
        response = io.BytesIO(AUDIO)
        with patch('aac.speech.urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(speech.elevenlabs('Hi', 'voice/../x', ''), AUDIO)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.elevenlabs.io/v1/text-to-speech/voice%2F..%2Fx?output_format=mp3_44100_128')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Xi-api-key'), 'synthetic-test-key')
        self.assertEqual(json.loads(request.data), {'text': 'Hi', 'model_id': 'eleven_flash_v2_5'})
        self.assertEqual(urlopen.call_args.kwargs['timeout'], speech.TIMEOUT_SECONDS)
        self.assertTrue(response.closed)

    @override_settings(ELEVENLABS_API_KEY='')
    def test_missing_key_never_calls_provider(self):
        with patch('aac.speech.urllib.request.urlopen') as urlopen, self.assertRaises(SpeechUnavailable):
            speech.elevenlabs('Hi', 'voice', '')
        urlopen.assert_not_called()

    @override_settings(ELEVENLABS_API_KEY='synthetic-test-key')
    def test_http_and_network_errors_are_unavailable(self):
        errors = (
            urllib.error.HTTPError('https://api.elevenlabs.io', 401, 'private', {}, io.BytesIO(b'private')),
            urllib.error.URLError('private'), TimeoutError(),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__), patch('aac.speech.urllib.request.urlopen', side_effect=error):
                with self.assertRaises(SpeechUnavailable) as raised:
                    speech.elevenlabs('Hi', 'voice', 'model')
                self.assertNotIn('private', str(raised.exception))


class CleanupAudioTests(SpeechTestCase):
    def test_removes_only_old_audio(self):
        audio = self.media / 'audio'
        audio.mkdir()
        old, new, partial, other = (audio / name for name in ('old.mp3', 'new.mp3', 'old.tmp', 'keep.txt'))
        for path in (old, new, partial, other):
            path.write_bytes(AUDIO)
        stale = time.time() - 48 * 3600
        for path in (old, partial, other):
            os.utime(path, (stale, stale))
        out = io.StringIO()
        call_command('cleanup_audio', stdout=out)
        self.assertEqual(sorted(path.name for path in audio.iterdir()), ['keep.txt', 'new.mp3'])
        self.assertIn('Removed 2', out.getvalue())

    def test_cache_hit_refreshes_age(self):
        url = speech.synthesize('Hi')
        path = self.media / 'audio' / url.rsplit('/', 1)[1]
        stale = time.time() - 48 * 3600
        os.utime(path, (stale, stale))
        speech.synthesize('Hi')
        call_command('cleanup_audio', stdout=io.StringIO())
        self.assertTrue(path.exists())

    def test_missing_directory_is_fine(self):
        call_command('cleanup_audio', '--hours', '0', stdout=io.StringIO())


class CastingTests(TestCase):
    @override_settings(GOOGLE_HOME_HOST='')
    def test_disabled_without_host(self):
        with patch('aac.casting.threading.Thread') as thread:
            self.assertFalse(casting.cast_audio('http://192.0.2.1:8000/media/audio/x.mp3'))
        thread.assert_not_called()

    @override_settings(GOOGLE_HOME_HOST='192.0.2.50')
    def test_starts_background_cast(self):
        with patch('aac.casting.threading.Thread') as thread:
            self.assertTrue(casting.cast_audio('http://192.0.2.1:8000/media/audio/x.mp3'))
        thread.assert_called_once_with(
            target=casting.play, args=('192.0.2.50', 'http://192.0.2.1:8000/media/audio/x.mp3'), daemon=True,
        )
        thread.return_value.start.assert_called_once_with()

    def test_play_uses_known_host_and_always_disconnects(self):
        device = Mock()
        with patch('aac.casting.pychromecast.get_chromecast_from_host', return_value=device) as connect:
            casting.play('192.0.2.50', 'http://192.0.2.1:8000/media/audio/x.mp3')
        connect.assert_called_once_with(('192.0.2.50', None, None, None, None), tries=1, timeout=casting.TIMEOUT_SECONDS)
        device.media_controller.play_media.assert_called_once_with(
            'http://192.0.2.1:8000/media/audio/x.mp3', 'audio/mpeg', stream_type='BUFFERED',
        )
        device.disconnect.assert_called_once()
        device.media_controller.play_media.side_effect = OSError('private')
        device.disconnect.side_effect = OSError('private')
        with patch('aac.casting.pychromecast.get_chromecast_from_host', return_value=device), \
                self.assertLogs('aac.casting', 'WARNING') as logs:
            casting.play('192.0.2.50', 'http://192.0.2.1:8000/media/audio/secret.mp3')
        self.assertNotIn('secret', ''.join(logs.output))
        with patch('aac.casting.pychromecast.get_chromecast_from_host', side_effect=OSError), \
                self.assertLogs('aac.casting', 'WARNING'):
            casting.play('192.0.2.50', 'http://192.0.2.1:8000/media/audio/x.mp3')
