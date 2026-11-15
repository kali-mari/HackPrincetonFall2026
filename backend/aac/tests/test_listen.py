"""Listen mode: the Listener pipeline and WS /ws/conversation/; no model, mic or network."""

import sys
import subprocess
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from jsonschema import Draft202012Validator
from django.test import SimpleTestCase, override_settings

from aac import consumers, listen
from aac.consumers import ConversationConsumer
from aac.listen import Listener, capture_command
from aac.openapi import SCHEMAS
from aac.transcription import TranscriptionUnavailable
from config.asgi import application

BROWSER = [(b'origin', b'http://localhost:5173')]
CHUNK = listen.WINDOW * 2  # bytes per voice-detector step


class FakeVad:
    """Emits one phrase per window of audio, and one more on flush."""

    def __init__(self):
        self.ready = []
        self.seen = 0

    def accept_waveform(self, samples):
        self.ready.append(SimpleNamespace(start=self.seen, samples=samples))
        self.seen += len(samples)

    def empty(self):
        return not self.ready

    @property
    def front(self):
        return self.ready[0]

    def pop(self):
        self.ready.pop(0)

    def flush(self):
        self.ready.append(SimpleNamespace(start=self.seen, samples=[0.0]))


def source(chunks, exit_code=0):
    code = f'import sys; sys.stdout.buffer.write(bytes({chunks * CHUNK})); sys.exit({exit_code})'
    return [sys.executable, '-c', code]


class ListenerTest(SimpleTestCase):
    def setUp(self):
        patcher = patch.object(listen, '_pause_until', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_listener(self, command, transcribe=lambda samples: f'phrase {len(samples)}'):
        texts, ends, done = [], [], threading.Event()

        def on_end(error):
            ends.append(error)
            done.set()

        with patch.object(listen, 'capture_command', return_value=command), \
                patch.object(listen, 'load_vad', return_value=FakeVad()), \
                patch.object(listen.transcription, 'load'), \
                patch.object(listen.transcription, 'transcribe_samples', side_effect=transcribe):
            listener = Listener(lambda text, delay: texts.append((text, delay)), on_end)
            listener.start()
            self.assertTrue(done.wait(10))
        return texts, ends

    def test_each_phrase_then_clean_end(self):
        texts, ends = self.run_listener(source(2))
        self.assertEqual([text for text, _ in texts], ['phrase 512', 'phrase 512', 'phrase 1'])
        self.assertTrue(all(delay >= 0 for _, delay in texts))
        self.assertEqual(ends, [None])

    def test_failed_capture_reports_safe_error(self):
        with self.assertLogs('aac.listen', 'WARNING'):
            texts, ends = self.run_listener(source(0, exit_code=1))
        self.assertEqual(texts, [])
        self.assertEqual(ends, ['Microphone is not available.'])

    def test_blank_text_and_failed_decode_are_skipped(self):
        results = iter(['', RuntimeError('boom'), 'kept'])

        def transcribe(samples):
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result

        with self.assertLogs('aac.listen', 'ERROR'):
            texts, ends = self.run_listener(source(2), transcribe)
        self.assertEqual([text for text, _ in texts], ['kept'])
        self.assertEqual(ends, [None])

    def test_stop_discards_pending_phrases_and_skips_on_end(self):
        texts, ends, release = [], [], threading.Event()

        def transcribe(samples):
            release.wait(5)
            return 'late'

        with patch.object(listen, 'capture_command', return_value=source(2)), \
                patch.object(listen, 'load_vad', return_value=FakeVad()), \
                patch.object(listen.transcription, 'load'), \
                patch.object(listen.transcription, 'transcribe_samples', side_effect=transcribe):
            listener = Listener(lambda *args: texts.append(args), ends.append)
            listener.start()
            listener.stop()
            release.set()
            listener.process.wait(5)
        self.assertEqual((texts, ends), ([], []))

    def test_stop_reaps_capture_even_when_sigterm_cannot_finish(self):
        # Models a capture tool stuck flushing stdout after the reader stops.
        command = [sys.executable, '-u', '-c',
                   'import signal,sys,time; signal.signal(signal.SIGTERM, lambda *a: None); '
                   'sys.stdout.write("ready\\n"); sys.stdout.flush(); time.sleep(30)']
        listener = Listener(None, None)
        listener.process = subprocess.Popen(command, stdout=subprocess.PIPE)
        try:
            self.assertEqual(listener.process.stdout.readline(), b'ready\n')
            started = time.monotonic()
            listener.stop()
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNotNone(listener.process.returncode)
        finally:
            if listener.process.poll() is None:
                listener.process.kill()
            listener.process.wait()
            listener.process.stdout.close()

    def test_pause_feeds_silence_instead_of_the_microphone(self):
        heard = []
        vad = FakeVad()
        accept = vad.accept_waveform
        vad.accept_waveform = lambda samples: (heard.append(set(samples)), accept(samples))
        code = f'import sys; sys.stdout.buffer.write(bytes([1, 0]) * {listen.WINDOW * 2})'
        listen.pause(5)
        done = threading.Event()
        with patch.object(listen, 'capture_command', return_value=[sys.executable, '-c', code]), \
                patch.object(listen, 'load_vad', return_value=vad), \
                patch.object(listen.transcription, 'load'), \
                patch.object(listen.transcription, 'transcribe_samples', return_value='x'):
            Listener(lambda *args: None, lambda error: done.set()).start()
            self.assertTrue(done.wait(10))
        self.assertEqual(heard, [{0.0}, {0.0}])

    def test_pause_extends_but_never_shortens(self):
        listen.pause(10)
        until = listen._pause_until
        listen.pause(1)
        self.assertEqual(listen._pause_until, until)
        listen.pause(20)
        self.assertGreater(listen._pause_until, until)

    def test_backlog_keeps_only_the_newest_phrases(self):
        listener = Listener(None, None)
        vad = FakeVad()
        for _ in range(listen.MAX_PENDING + 2):
            vad.accept_waveform([0.0])
        with self.assertLogs('aac.listen', 'WARNING'):
            listener._queue_phrases(vad, 0.0)
        self.assertEqual(listener.phrases.qsize(), listen.MAX_PENDING)
        self.assertEqual(listener.phrases.get()[1][1], 3 / listen.SAMPLE_RATE)

    def test_capture_commands(self):
        self.assertEqual(capture_command('plughw:1,0')[:4], ['arecord', '-q', '-D', 'plughw:1,0'])
        command = capture_command('file:/tmp/clip.wav')
        self.assertEqual(command[0], 'ffmpeg')
        self.assertNotIn('-re', command)  # the Listener paces files itself
        self.assertEqual(command[command.index('-i') + 1], '/tmp/clip.wav')

    @override_settings(LISTEN_VAD_MODEL=Path('/missing/silero_vad.onnx'))
    def test_missing_voice_detector_is_unavailable(self):
        with self.assertRaisesMessage(TranscriptionUnavailable, 'Voice detector'):
            listen.load_vad()


class FakeListener:
    """Stands in for Listener; tests call on_text/on_end the way its threads would."""

    instances = []
    fail = None

    def __init__(self, on_text, on_end):
        self.on_text, self.on_end = on_text, on_end
        self.stopped = False
        FakeListener.instances.append(self)

    def start(self):
        if FakeListener.fail:
            raise TranscriptionUnavailable(FakeListener.fail)

    def stop(self):
        self.stopped = True

    def emit(self, text):  # from another thread, like the real worker
        threading.Thread(target=self.on_text, args=(text, 0.5)).start()

    def end(self, error):
        threading.Thread(target=self.on_end, args=(error,)).start()


class ConversationSocketTest(IsolatedAsyncioTestCase):
    def setUp(self):
        FakeListener.instances = []
        FakeListener.fail = None
        ConversationConsumer.owner = None
        patcher = patch.object(consumers, 'Listener', FakeListener)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.open = []

    async def asyncTearDown(self):
        for ws in self.open:
            await ws.disconnect()

    async def asyncSetUp(self):
        validator = Draft202012Validator(SCHEMAS['ConversationServerMessage'])
        sent = WebsocketCommunicator.receive_json_from

        async def checked(communicator, timeout=1):  # every server message matches OpenAPI
            message = await sent(communicator, timeout)
            validator.validate(message)
            return message

        patcher = patch.object(WebsocketCommunicator, 'receive_json_from', checked)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def connect(self, headers=BROWSER):
        ws = WebsocketCommunicator(application, '/ws/conversation/', headers=list(headers))
        connected, _ = await ws.connect()
        if connected:
            self.open.append(ws)
            self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': False})
        return ws, connected

    async def start(self, ws):
        Draft202012Validator(SCHEMAS['ConversationClientMessage']).validate({'type': 'start'})
        await ws.send_json_to({'type': 'start'})
        self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': True})
        return FakeListener.instances[-1]

    async def test_start_streams_numbered_transcripts_then_stop(self):
        ws, _ = await self.connect()
        listener = await self.start(ws)
        for seq, text in enumerate(['Time for lunch.', 'Do you want juice?'], 1):
            listener.emit(text)
            self.assertEqual(await ws.receive_json_from(), {'type': 'transcript', 'seq': seq, 'text': text})
        await ws.send_json_to({'type': 'stop'})
        self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': False})
        self.assertTrue(listener.stopped)
        listener.emit('late')
        self.assertTrue(await ws.receive_nothing(0.2))

    async def test_one_listener_at_a_time_and_disconnect_frees_it(self):
        first, _ = await self.connect()
        second, _ = await self.connect()
        listener = await self.start(first)
        await second.send_json_to({'type': 'start'})
        self.assertEqual((await second.receive_json_from())['type'], 'error')
        await first.disconnect()
        self.open.remove(first)
        self.assertTrue(listener.stopped)
        await self.start(second)

    async def test_start_warms_the_suggestion_model_without_waiting(self):
        with patch.object(consumers.conversation, 'warm') as warm:
            ws, _ = await self.connect()
            await self.start(ws)
        warm.assert_called_once_with()

    async def test_start_twice_is_harmless(self):
        ws, _ = await self.connect()
        await self.start(ws)
        await self.start(ws)
        self.assertEqual(len(FakeListener.instances), 1)

    async def test_unavailable_sends_error_and_frees_the_mic(self):
        ws, _ = await self.connect()
        FakeListener.fail = 'Voice detector model is not installed.'
        await ws.send_json_to({'type': 'start'})
        self.assertEqual(await ws.receive_json_from(),
                         {'type': 'error', 'message': 'Voice detector model is not installed.'})
        self.assertIsNone(ConversationConsumer.owner)

    async def test_capture_ending_reports_error_and_state(self):
        ws, _ = await self.connect()
        listener = await self.start(ws)
        listener.end('Microphone is not available.')
        self.assertEqual(await ws.receive_json_from(),
                         {'type': 'error', 'message': 'Microphone is not available.'})
        self.assertEqual(await ws.receive_json_from(), {'type': 'state', 'listening': False})
        self.assertIsNone(ConversationConsumer.owner)

    async def test_invalid_messages_get_an_error_and_stay_connected(self):
        ws, _ = await self.connect()
        for frame in ('not json', '{"type": "pause"}', '{"type": "start", "x": 1}'):
            await ws.send_to(text_data=frame)
            self.assertEqual((await ws.receive_json_from())['type'], 'error')
        await ws.send_to(bytes_data=b'\x00')
        self.assertEqual((await ws.receive_json_from())['type'], 'error')
        await self.start(ws)

    async def test_other_browser_origins_are_rejected(self):
        with self.assertLogs('aac.consumers', 'WARNING'):
            _, connected = await self.connect([(b'origin', b'http://evil.example')])
        self.assertFalse(connected)
        _, connected = await self.connect([])  # command-line clients send no Origin
        self.assertTrue(connected)
