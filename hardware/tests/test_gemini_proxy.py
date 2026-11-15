"""The USB proxy may forward opaque Gemini TLS, never arbitrary destinations."""

import http.client
from http.server import ThreadingHTTPServer
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gemini_proxy import GeminiTunnel


class GeminiProxyTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), GeminiTunnel)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def test_other_destinations_cannot_open_an_upstream_connection(self):
        for target in ['example.com:443', 'generativelanguage.googleapis.com:80',
                       'generativelanguage.googleapis.com:443@other.example:443']:
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
            connection.connect()
            with patch('gemini_proxy.socket.create_connection') as upstream:
                connection.request('CONNECT', target)
                self.assertEqual(connection.getresponse().status, 403)
                upstream.assert_not_called()
            connection.close()

    def test_allowed_destination_forwards_bytes_without_inspecting_them(self):
        upstream, peer = socket.socketpair()
        client = socket.socket()
        client.settimeout(2)
        client.connect(self.server.server_address)
        reader = client.makefile('rb')
        try:
            with patch('gemini_proxy.socket.create_connection', return_value=upstream) as connect:
                client.sendall(b'CONNECT generativelanguage.googleapis.com:443 HTTP/1.1\r\nHost: localhost\r\n\r\n')
                self.assertIn(b'200 Connection Established', reader.readline())
                while reader.readline() != b'\r\n':
                    pass
                payload = b'\x16\x03\x01opaque-test-bytes'
                client.sendall(payload)
                peer.settimeout(2)
                self.assertEqual(peer.recv(len(payload)), payload)
                peer.sendall(payload)
                self.assertEqual(reader.read(len(payload)), payload)
                connect.assert_called_once_with(('generativelanguage.googleapis.com', 443), timeout=5)
        finally:
            reader.close()
            client.close()
            peer.close()
