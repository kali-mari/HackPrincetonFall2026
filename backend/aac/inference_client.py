"""Private same-device inference protocol. Never log request/response contents."""

import json
import socket
import threading

from django.conf import settings

from .transcription import TranscriptionUnavailable

MAX_FRAME = 2 * 1024 * 1024


class InferenceUnavailable(Exception):
    pass


def send(connection, message):
    data = json.dumps(message, allow_nan=False).encode() + b'\n'
    if len(data) > MAX_FRAME:
        raise InferenceUnavailable('Local inference request is too large.')
    connection.sendall(data)


def receive(stream):
    line = stream.readline(MAX_FRAME + 1)
    if not line or len(line) > MAX_FRAME or not line.endswith(b'\n'):
        raise InferenceUnavailable('Local inference disconnected.')
    message = json.loads(line)
    if not isinstance(message, dict) or message.get('error'):
        raise InferenceUnavailable('Local inference is unavailable.')
    return message


def connect(timeout):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(settings.INFERENCE_SOCKET)
    except OSError:
        connection.close()
        raise
    return connection


def request(message, timeout=10):
    try:
        with connect(timeout) as connection, connection.makefile('rb') as stream:
            send(connection, message)
            return receive(stream)
    except (OSError, ValueError, InferenceUnavailable):
        raise InferenceUnavailable('Local inference is unavailable.') from None


class RemoteListener:
    def __init__(self, on_text, on_end):
        self.on_text, self.on_end = on_text, on_end
        self.stopped = threading.Event()
        self.connection = self.stream = None

    def start(self):
        try:
            self.connection = connect(30)
            self.stream = self.connection.makefile('rb')
            send(self.connection, {'op': 'listen'})
            if receive(self.stream) != {'ready': True}:
                raise InferenceUnavailable()
            # Server sends a heartbeat every second, even during silence.
            self.connection.settimeout(5)
        except (OSError, ValueError, InferenceUnavailable):
            self.stop()
            if self.stream:
                self.stream.close()
            raise TranscriptionUnavailable('Local listening service is unavailable.') from None
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        error = None
        try:
            while not self.stopped.is_set():
                message = receive(self.stream)
                if 'text' in message:
                    if not self.stopped.is_set():
                        self.on_text(message['text'], message['delay'])
                elif 'end' in message:
                    error = message['end']
                    break
        except (OSError, ValueError, InferenceUnavailable):
            error = 'Local listening service disconnected.'
        finally:
            notify = not self.stopped.is_set()
            self.stop()
            self.stream.close()
            if notify:
                self.on_end(error)

    def stop(self):
        self.stopped.set()
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
