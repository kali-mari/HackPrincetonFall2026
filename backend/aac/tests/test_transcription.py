"""Provider-neutral transcription: selection, audio conversion, caching; no model or network."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from aac import transcription
from aac.transcription import TranscriptionUnavailable, transcribe

HALF_AND_MINUS_HALF = b'\x00\x40\x00\xc0'  # 16384, -16384


@override_settings(TRANSCRIBE_PROVIDER='fake', TRANSCRIBE_MODEL_DIR=Path('/models/fake'),
                   TRANSCRIBE_THREADS=2, TRANSCRIBE_DEVICE='gpu')
class TranscriptionTest(SimpleTestCase):
    def setUp(self):
        self.decode = Mock(return_value=' hello there ')
        self.loader = Mock(return_value=self.decode)
        for target, values in ((transcription.PROVIDERS, {'fake': self.loader}), (transcription._loaded, {})):
            patcher = patch.dict(target, values, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_decodes_scaled_samples_and_strips_text(self):
        self.assertEqual(transcribe(HALF_AND_MINUS_HALF), 'hello there')
        self.decode.assert_called_once_with([0.5, -0.5])

    def test_loader_gets_model_threads_and_device_once(self):
        transcribe(HALF_AND_MINUS_HALF)
        transcribe(HALF_AND_MINUS_HALF)
        self.loader.assert_called_once_with(Path('/models/fake'), 2, 'gpu')

    def test_changed_device_loads_again(self):
        transcribe(HALF_AND_MINUS_HALF)
        with override_settings(TRANSCRIBE_DEVICE='cpu'):
            transcribe(HALF_AND_MINUS_HALF)
        self.assertEqual(self.loader.call_count, 2)

    @override_settings(TRANSCRIBE_PROVIDER='')
    def test_blank_provider_is_unavailable(self):
        with self.assertRaisesMessage(TranscriptionUnavailable, 'not configured'):
            transcribe(HALF_AND_MINUS_HALF)

    def test_rejects_partial_samples_and_long_audio(self):
        for pcm in (b'\x00', bytes(30 * 16000 * 2 + 2)):
            with self.assertRaises(ValueError):
                transcribe(pcm)
        self.loader.assert_not_called()

    def test_moonshine_without_model_files_is_unavailable(self):
        with TemporaryDirectory() as empty:
            with self.assertRaisesMessage(TranscriptionUnavailable, 'model is not installed'):
                transcription.moonshine(Path(empty), 1, 'cpu')

    @override_settings(TRANSCRIBE_PROVIDER='')
    def test_fetch_requires_a_provider(self):
        with self.assertRaises(CommandError):
            call_command('fetch_transcription_model')
