"""Loopback-only CONNECT tunnel for UNO Q Gemini HTTPS over USB.

Only generativelanguage.googleapis.com:443 is accepted. TLS remains end to end;
this helper never sees or logs API keys, prompts, or responses.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socket
import time

TARGET = 'generativelanguage.googleapis.com:443'


class GeminiTunnel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        if self.path.lower() != TARGET:
            self.send_error(403, 'Only Gemini HTTPS is allowed')
            return
        try:
            upstream = socket.create_connection(('generativelanguage.googleapis.com', 443), timeout=5)
        except OSError:
            self.send_error(502, 'Gemini connection unavailable')
            return
        with upstream:
            self.send_response(200, 'Connection Established')
            self.end_headers()
            self.wfile.flush()
            self.connection.settimeout(10)
            upstream.settimeout(10)
            last_data = time.monotonic()
            try:
                while time.monotonic() - last_data < 30:
                    ready, _, _ = select.select([self.connection, upstream], [], [], 1)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        destination = upstream if source is self.connection else self.connection
                        destination.sendall(data)
                        last_data = time.monotonic()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), GeminiTunnel) as server:
        print(f'Gemini TLS tunnel ready on 127.0.0.1:{args.port}.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
