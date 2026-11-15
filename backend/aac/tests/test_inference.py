"""Exercise the real private socket protocol without models or a microphone."""

import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from aac import embeddings
from aac.inference_client import RemoteListener, InferenceUnavailable, request
from aac.inference_server import Server, Handler
from aac.transcription import TranscriptionUnavailable


class FakeListener:
    instances = []

    def __init__(self, on_text, on_end):
        self.on_text, self.on_end = on_text, on_end
        self.stopped = threading.Event()
        self.instances.append(self)

    def start(self):
        pass

    def stop(self):
        self.stopped.set()


class InferenceSocketTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(dir='/tmp', prefix='aac-')
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'inference.sock')
        self.enterContext(override_settings(INFERENCE_SOCKET=self.path))
        self.server = Server(self.path, Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.thread.start()
        self.addCleanup(self.close_server)
        FakeListener.instances = []
        self.enterContext(patch('aac.inference_server.listen.Listener', FakeListener))

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def listener(self):
        texts, ends = [], []
        remote = RemoteListener(lambda *args: texts.append(args), ends.append)
        self.addCleanup(remote.stop)
        remote.start()
        return remote, texts, ends

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_health_embeddings_and_pause_use_private_socket(self):
        self.assertEqual(request({'op': 'health'}), {'ready': True})
        with patch('aac.inference_server.embeddings.embed', return_value=[[0.0, 1.0]]) as embed:
            self.assertEqual(request({'op': 'embed', 'texts': ['private']}), {'vectors': [[0.0, 1.0]]})
            embed.assert_called_once_with(['private'])
        with patch('aac.inference_server.listen.pause') as pause:
            self.assertEqual(request({'op': 'pause', 'seconds': 3}), {'ok': True})
            pause.assert_called_once_with(3)

    def test_stream_stop_discards_late_results_and_releases_microphone(self):
        remote, texts, ends = self.listener()
        local = FakeListener.instances[-1]
        local.on_text('private phrase', 0.1)
        self.wait_for(lambda: bool(texts))
        self.assertEqual(texts, [('private phrase', 0.1)])
        remote.stop()
        self.assertTrue(local.stopped.wait(2))
        local.on_text('late', 0)
        self.assertEqual(len(texts), 1)
        self.assertEqual(ends, [])
        self.listener()  # same microphone can be claimed again

    def test_second_listener_is_rejected_until_first_disconnects(self):
        remote, _, _ = self.listener()
        other = RemoteListener(None, None)
        with self.assertRaises(TranscriptionUnavailable):
            other.start()
        remote.stop()
        self.assertTrue(FakeListener.instances[0].stopped.wait(2))

    def test_capture_end_notifies_client_and_releases_microphone(self):
        _, _, ends = self.listener()
        local = FakeListener.instances[-1]
        local.on_end('Microphone is not available.')
        self.wait_for(lambda: bool(ends))
        self.assertEqual(ends, ['Microphone is not available.'])
        self.assertTrue(local.stopped.wait(2))

    def test_backend_crash_stops_capture_without_a_stop_message(self):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(self.path)
        connection.sendall(b'{"op":"listen"}\n')
        self.assertIn(b'ready', connection.recv(1024))
        connection.close()
        self.assertTrue(FakeListener.instances[-1].stopped.wait(2))

    def test_invalid_requests_are_generic_and_do_not_break_service(self):
        for message in ({'op': 'embed', 'texts': 'private'}, {'op': 'pause', 'seconds': -1},
                        {'op': 'pause', 'seconds': True}, {'op': 'unknown'}):
            with self.subTest(op=message['op']), self.assertRaises(InferenceUnavailable) as error:
                request(message)
            self.assertNotIn('private', str(error.exception))
        self.assertTrue(request({'op': 'health'})['ready'])

    def test_unavailable_service_has_safe_error_and_embedding_fallback(self):
        with override_settings(INFERENCE_SOCKET=self.path + '-missing', EMBED_PROVIDER='minilm'):
            with self.assertRaises(InferenceUnavailable):
                request({'op': 'health'})
            with self.assertRaises(embeddings.EmbeddingUnavailable):
                embeddings.embed(['private'])
            with self.assertRaises(TranscriptionUnavailable):
                RemoteListener(None, None).start()
