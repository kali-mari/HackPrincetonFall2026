"""Serial-to-WebSocket bridge for the AAC switch Arduino.

Reads one token per line from hardware/aac_switch and sends the matching
{"action", "source"} JSON message to the backend at /ws/input/.

    python hardware/bridge.py --port /dev/cu.usbmodem1101
    python hardware/bridge.py --port /dev/cu.usbmodem1101 --dry-run
"""

import argparse
import json
import logging
import sys
import time

import serial
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

log = logging.getLogger("bridge")

# Serial line -> WebSocket message
MESSAGES = {
    "PREV": {"action": "PREV", "source": "button"},
    "NEXT": {"action": "NEXT", "source": "button"},
    "SELECT": {"action": "SELECT", "source": "button"},
    "DELETE": {"action": "DELETE", "source": "button"},
    "SPEAK": {"action": "SPEAK", "source": "button"},
    "VOICE": {"action": "SELECT", "source": "voice"},
    "TOUCH": {"action": "SELECT", "source": "touch"},
}

RETRY_SECONDS = 2


def parse_line(line):
    """Map one serial line to a message dict, or None for blank/unknown/garbled lines."""
    message = MESSAGES.get(line.strip())
    return dict(message) if message else None


def open_serial(port, baud):
    # Short read timeout keeps the loop responsive for WebSocket reconnects
    return serial.Serial(port, baud, timeout=0.1)


def connect_ws(url):
    # legacy=True: keep the socket open across loop iterations instead of a with-block
    # (websockets 17.1+ warns on a bare connect() otherwise)
    return connect(url, open_timeout=RETRY_SECONDS, legacy=True)


def ws_is_open(ws):
    """Drain anything the server broadcast back and report whether the socket is still up."""
    try:
        while True:
            ws.recv(timeout=0)
    except TimeoutError:
        return True
    except (OSError, WebSocketException):
        return False


def run(port, baud, ws_url, dry_run, open_serial=open_serial, connect_ws=connect_ws,
        retry_seconds=RETRY_SECONDS):
    ser = None
    ws = None
    next_ws_attempt = 0.0
    last_status = None

    def status(text):
        # One line per state change, not one per retry
        nonlocal last_status
        if text != last_status:
            print(text, flush=True)
            last_status = text

    while True:
        if ser is None:
            try:
                ser = open_serial(port, baud)
                status(f"Serial connected: {port} at {baud} baud")
            except (serial.SerialException, OSError) as exc:
                log.debug("Serial open failed: %s", exc)
                status(f"Serial port {port} unavailable. Is the Arduino plugged in, and the Arduino "
                       f"Serial Monitor closed? (only one program can hold the port) Retrying...")
                time.sleep(retry_seconds)
                continue

        if not dry_run:
            if ws is not None and not ws_is_open(ws):
                status("WebSocket disconnected; dropping presses until it reconnects.")
                ws = None
                next_ws_attempt = time.monotonic() + retry_seconds
            if ws is None and time.monotonic() >= next_ws_attempt:
                try:
                    ws = connect_ws(ws_url)
                    # Discard presses that piled up while disconnected; never replay them
                    ser.reset_input_buffer()
                    status(f"WebSocket connected: {ws_url}")
                except (OSError, WebSocketException) as exc:
                    log.debug("WebSocket connect failed: %s", exc)
                    status(f"WebSocket {ws_url} unavailable; dropping presses until it connects. Retrying...")
                    next_ws_attempt = time.monotonic() + retry_seconds

        try:
            raw = ser.readline()
        except (serial.SerialException, OSError) as exc:
            log.debug("Serial read failed: %s", exc)
            status(f"Serial disconnected from {port}. Reconnecting...")
            ser.close()
            ser = None
            time.sleep(retry_seconds)
            continue

        if not raw:
            continue
        line = raw.decode("ascii", errors="replace")
        message = parse_line(line)
        if message is None:
            log.debug("Ignored serial line: %r", line)
            continue

        payload = json.dumps(message)
        if dry_run:
            print(payload, flush=True)
        elif ws is None:
            log.warning("Dropped %s: WebSocket not connected", payload)
        else:
            try:
                ws.send(payload)
                log.debug("Sent %s", payload)
            except (OSError, WebSocketException) as exc:
                log.warning("Dropped %s: send failed (%s)", payload, exc)
                status("WebSocket disconnected; dropping presses until it reconnects.")
                ws = None
                next_ws_attempt = time.monotonic() + retry_seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description="Forward AAC switch presses from serial to the backend WebSocket.")
    parser.add_argument("--port", required=True, help="serial port, e.g. /dev/cu.usbmodem1101 or COM3")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--ws-url", default="ws://localhost:8000/ws/input/")
    parser.add_argument("--dry-run", action="store_true", help="print the JSON instead of sending it")
    parser.add_argument("--verbose", action="store_true", help="log ignored lines and every send")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    try:
        run(args.port, args.baud, args.ws_url, args.dry_run)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
