"""Bridge tests with fake serial/WebSocket objects (no hardware or server).

    python -m unittest discover hardware/tests
"""

import contextlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bridge  # noqa: E402
from websockets.exceptions import ConnectionClosedError  # noqa: E402


class Done(Exception):
    """Raised by the fake serial port once its lines run out, to stop bridge.run()."""


class FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)
        self.resets = 0

    def readline(self):
        if not self.lines:
            raise Done
        return self.lines.pop(0)

    def reset_input_buffer(self):
        self.resets += 1

    def close(self):
        pass


class FakeWebSocket:
    def __init__(self, fail_sends=0):
        self.sent = []
        self.fail_sends = fail_sends

    def recv(self, timeout=None):
        raise TimeoutError

    def send(self, payload):
        if self.fail_sends:
            self.fail_sends -= 1
            raise ConnectionClosedError(None, None)
        self.sent.append(json.loads(payload))


def run_bridge(ser, connect_ws=None, dry_run=False):
    out = io.StringIO()
    # stderr swallows the bridge's "Dropped ..." warnings
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            bridge.run("FAKE", 9600, "ws://test/ws/input/", dry_run,
                       open_serial=lambda port, baud: ser,
                       connect_ws=connect_ws or (lambda url: FakeWebSocket()),
                       retry_seconds=0)
        except Done:
            pass
    return out.getvalue()


class ParseLineTests(unittest.TestCase):
    def test_every_serial_line(self):
        expected = {
            "PREV": {"action": "PREV", "source": "button"},
            "NEXT": {"action": "NEXT", "source": "button"},
            "SELECT": {"action": "SELECT", "source": "button"},
            "DELETE": {"action": "DELETE", "source": "button"},
            "SPEAK": {"action": "SPEAK", "source": "button"},
            "LISTEN": {"action": "LISTEN", "source": "button"},
            "VOICE": {"action": "SELECT", "source": "voice"},
            "TOUCH": {"action": "SELECT", "source": "touch"},
        }
        for line, message in expected.items():
            self.assertEqual(bridge.parse_line(line), message, line)

    def test_whitespace_and_line_endings(self):
        for line in ("NEXT\r\n", "NEXT\n", "  NEXT  ", "\tNEXT\r"):
            self.assertEqual(bridge.parse_line(line), {"action": "NEXT", "source": "button"}, repr(line))

    def test_rejected_lines(self):
        for line in ("next", "Select", "", "   ", "\r\n", "NEX", "EXT", "NEXTNEXT", "NEXT SELECT",
                     "# sound 312", "�NEXT", "BOGUS"):
            self.assertIsNone(bridge.parse_line(line), repr(line))

    def test_result_is_a_copy(self):
        bridge.parse_line("NEXT")["action"] = "CHANGED"
        self.assertEqual(bridge.parse_line("NEXT")["action"], "NEXT")


class RunTests(unittest.TestCase):
    def test_dry_run_prints_json(self):
        def no_ws(url):
            raise AssertionError("dry run must not connect")

        ser = FakeSerial([b"NEXT\r\n", b"", b"garbage\r\n", b"\xff\xfe\r\n", b"VOICE\r\n", b"SPEAK\r\n"])
        out = run_bridge(ser, connect_ws=no_ws, dry_run=True)
        messages = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
        self.assertEqual(messages, [
            {"action": "NEXT", "source": "button"},
            {"action": "SELECT", "source": "voice"},
            {"action": "SPEAK", "source": "button"},
        ])
        self.assertIn("Serial connected", out)

    def test_sends_to_websocket(self):
        ws = FakeWebSocket()
        run_bridge(FakeSerial([b"PREV\r\n", b"DELETE\r\n"]), connect_ws=lambda url: ws)
        self.assertEqual(ws.sent, [{"action": "PREV", "source": "button"},
                                   {"action": "DELETE", "source": "button"}])

    def test_presses_while_disconnected_are_dropped(self):
        ws = FakeWebSocket()
        attempts = []

        def flaky_connect(url):
            attempts.append(url)
            if len(attempts) <= 2:
                raise ConnectionRefusedError
            return ws

        ser = FakeSerial([b"NEXT\r\n", b"SELECT\r\n", b"PREV\r\n"])
        run_bridge(ser, connect_ws=flaky_connect)
        # NEXT and SELECT arrived while down; only PREV (after reconnect) is sent
        self.assertEqual(ws.sent, [{"action": "PREV", "source": "button"}])
        # Bytes buffered during the outage are flushed on reconnect
        self.assertEqual(ser.resets, 1)

    def test_failed_send_is_dropped_not_retried(self):
        first = FakeWebSocket(fail_sends=1)
        second = FakeWebSocket()
        sockets = [first, second]
        ser = FakeSerial([b"NEXT\r\n", b"SELECT\r\n"])
        run_bridge(ser, connect_ws=lambda url: sockets.pop(0))
        self.assertEqual(first.sent, [])
        self.assertEqual(second.sent, [{"action": "SELECT", "source": "button"}])


if __name__ == "__main__":
    unittest.main()
