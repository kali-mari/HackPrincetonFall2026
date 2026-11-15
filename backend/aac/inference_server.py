"""One CPU inference process; filesystem socket only, no public HTTP routes or DB.

Run with INFERENCE_SOCKET blank to avoid recursively calling the client.
Disconnecting a listen socket owns and stops its capture subprocess.
"""

import json
import math
import os
from pathlib import Path
import queue
import select
import signal
import socketserver
import threading

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.conf import settings

from . import embeddings, listen, transcription
from .inference_client import MAX_FRAME, send


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    # Only one microphone session, including while it is loading/stopping.
    microphone = threading.Lock()

    def handle_error(self, request, client_address):
        # socketserver's default traceback can expose exception payloads.
        pass


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            line = self.rfile.readline(MAX_FRAME + 1)
            if len(line) > MAX_FRAME or not line.endswith(b'\n'):
                raise ValueError()
            message = json.loads(line)
            op = message.get('op')
            if op == 'health':
                send(self.connection, {'ready': True})
            elif op == 'embed':
                texts = message.get('texts')
                if (not isinstance(texts, list) or not 1 <= len(texts) <= 1024
                        or not all(isinstance(t, str) and len(t) <= 10000 for t in texts)):
                    raise ValueError()
                send(self.connection, {'vectors': embeddings.embed(texts)})
            elif op == 'pause':
                seconds = message.get('seconds')
                if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                        or not math.isfinite(seconds) or not 0 <= seconds <= 300):
                    raise ValueError()
                listen.pause(seconds)
                send(self.connection, {'ok': True})
            elif op == 'listen':
                self.session()
            else:
                raise ValueError()
        except Exception:
            # No request bodies, audio, transcripts, or exception details in logs.
            try:
                send(self.connection, {'error': 'Local inference is unavailable.'})
            except OSError:
                pass

    def session(self):
        if not self.server.microphone.acquire(blocking=False):
            raise ValueError()
        events = queue.Queue(maxsize=8)
        stopped = threading.Event()

        def emit(message):
            if stopped.is_set():
                return
            try:
                events.put_nowait(message)
            except queue.Full:
                try:
                    events.get_nowait()
                except queue.Empty:
                    pass
                try:
                    events.put_nowait(message)
                except queue.Full:
                    pass

        listener = listen.Listener(
            lambda text, delay: emit({'text': text, 'delay': delay}),
            lambda error: emit({'end': error}),
        )
        self.server.active_listener = listener
        try:
            listener.start()
            send(self.connection, {'ready': True})
            while True:
                # EOF (including a crashed backend) releases the microphone.
                if select.select([self.connection], [], [], 0)[0]:
                    break
                try:
                    message = events.get(timeout=0.2)
                except queue.Empty:
                    message = {'heartbeat': True}
                send(self.connection, message)
                if 'end' in message:
                    break
        finally:
            stopped.set()
            listener.stop()
            self.server.active_listener = None
            while not events.empty():
                events.get_nowait()
            self.server.microphone.release()


def main():
    if settings.INFERENCE_SOCKET:
        raise SystemExit('The inference server must not set INFERENCE_SOCKET.')
    path = Path(os.environ.get('INFERENCE_SERVER_SOCKET', '/run/aac/inference.sock'))
    # Fail readiness before opening the socket, without ever opening a microphone.
    transcription.load()
    listen.load_vad()
    if embeddings.enabled():
        embeddings.embed(['ready'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with Server(str(path), Handler) as server:
        path.chmod(0o660)

        def shutdown(*_):
            # Exiting closes all sockets; init reaps any capture subprocess.
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, shutdown)
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            listener = getattr(server, 'active_listener', None)
            if listener:
                listener.stop()
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
