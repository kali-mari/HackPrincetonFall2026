#!/usr/bin/env python3
"""Linux side of the single-board (Arduino UNO Q only) setup.

The sketch in hardware/unoq_board runs on the UNO Q's microcontroller. This script runs
on the same board's Linux side, next to the backend, and does two jobs over the board's
built-in Bridge (the arduino-router service):

1. Button presses from the sketch -> JSON on the backend WebSocket (same messages as
   hardware/bridge.py sends for the USB serial setup).
2. CPU %, RAM used, load average and running jobs -> the 16x2 LCD, once a second.

Install hardware/requirements.txt into the backend's Python, then run:
    /home/arduino/aac-integration/backend/.venv/bin/python unoq_bridge.py
"""
import argparse
import json
import logging
import select
import socket
import time

import msgpack
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

log = logging.getLogger("unoq_bridge")

ROUTER_SOCKET = "/var/run/arduino-router.sock"
RETRY_SECONDS = 2
LCD_SECONDS = 1.0

# Token from the sketch -> WebSocket message (same as bridge.py)
MESSAGES = {
    "PREV": {"action": "PREV", "source": "button"},
    "NEXT": {"action": "NEXT", "source": "button"},
    "SELECT": {"action": "SELECT", "source": "button"},
    "DELETE": {"action": "DELETE", "source": "button"},
    "SPEAK": {"action": "SPEAK", "source": "button"},
    "LISTEN": {"action": "LISTEN", "source": "button"},
}

# msgpack-rpc message types used by the router
REQUEST, RESPONSE, NOTIFY = 0, 1, 2


# ---- System stats for the LCD ----

class CpuMeter:
    """CPU usage between calls, from /proc/stat."""

    def __init__(self):
        self.idle = 0.0
        self.total = 0.0
        self.percent()  # prime the counters so the first real reading is right

    def percent(self):
        with open("/proc/stat") as f:
            fields = [float(x) for x in f.readline().split()[1:8]]
        idle = fields[3] + fields[4]
        total = sum(fields)
        diff_idle, diff_total = idle - self.idle, total - self.total
        self.idle, self.total = idle, total
        if diff_total <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - diff_idle / diff_total)))


def memory_used_gb():
    """RAM in use (total minus available), in GB."""
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, rest = line.split(":", 1)
            values[key] = int(rest.split()[0])
    return (values["MemTotal"] - values["MemAvailable"]) / (1024 * 1024)


def load_and_jobs():
    """1-minute load average and the number of running tasks."""
    with open("/proc/loadavg") as f:
        parts = f.read().split()  # e.g. 1.26 1.33 1.32 1/274 18900
    return float(parts[0]), int(parts[3].split("/")[0])


def lcd_lines(cpu):
    load, jobs = load_and_jobs()
    line1 = f"CPU:{cpu.percent():3.0f}% R:{memory_used_gb():.1f}G"
    line2 = f"LD:{load:.2f} JOBS:{jobs}"
    return line1[:16], line2[:16]


# ---- Backend WebSocket ----

class Backend:
    """Sends button messages to the backend, reconnecting when the socket drops."""

    def __init__(self, url):
        self.url = url
        self.ws = None
        self.next_try = 0.0

    def _connect(self):
        if self.ws is not None or time.monotonic() < self.next_try:
            return
        try:
            self.ws = connect(self.url, open_timeout=RETRY_SECONDS, legacy=True)
            log.info("Backend connected: %s", self.url)
        except (OSError, WebSocketException, TimeoutError) as exc:
            self.next_try = time.monotonic() + RETRY_SECONDS
            log.warning("Backend unavailable at %s (%s). Retrying...", self.url, exc)

    def _drop(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = None

    def keep_alive(self):
        """Connect if needed and drain what the server broadcast back to us."""
        self._connect()
        if self.ws is None:
            return
        try:
            while True:
                self.ws.recv(timeout=0)
        except TimeoutError:
            pass
        except (OSError, WebSocketException):
            log.warning("Backend disconnected. Reconnecting...")
            self._drop()

    def send(self, message):
        for _ in range(2):  # one reconnect-and-retry so a stale socket does not eat a press
            self._connect()
            if self.ws is None:
                break
            try:
                self.ws.send(json.dumps(message))
                log.info("Sent %s", message)
                return
            except (OSError, WebSocketException):
                self._drop()
                self.next_try = 0.0
        log.warning("Dropped %s: backend not connected", message)


# ---- Router (Bridge to the microcontroller) ----

def connect_router(path):
    """Connect to arduino-router and ask it to deliver aac_token calls to us."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    sock.sendall(msgpack.packb([REQUEST, 0, "$/register", ["aac_token"]]))
    log.info("Router connected: %s", path)
    return sock


def handle_router_message(msg, sock, backend, lcd_errors):
    if not isinstance(msg, (list, tuple)) or not msg:
        return
    if msg[0] == RESPONSE:
        _, msgid, error, _ = msg
        if error and msgid == 0:
            log.error("Could not register aac_token with the router: %s", error)
        elif error and error != lcd_errors.get("last"):
            lcd_errors["last"] = error  # log each distinct LCD error once, not every second
            log.warning("LCD update failed: %s", error)
        elif not error and msgid != 0 and lcd_errors.get("last"):
            lcd_errors["last"] = None
            log.info("LCD updates working again")
        return

    if msg[0] == REQUEST:
        _, msgid, method, params = msg
        sock.sendall(msgpack.packb([RESPONSE, msgid, None, None]))
    elif msg[0] == NOTIFY:
        _, method, params = msg
    else:
        return

    if method != "aac_token" or not params:
        return
    message = MESSAGES.get(str(params[0]).strip())
    if message:
        backend.send(dict(message))
    else:
        log.debug("Ignored token: %r", params[0])


def run(ws_url, router_path):
    backend = Backend(ws_url)
    cpu = CpuMeter()
    sock = None
    msgid = 0
    lcd_errors = {}
    next_lcd = time.monotonic()

    while True:
        if sock is None:
            try:
                sock = connect_router(router_path)
                unpacker = msgpack.Unpacker(raw=False)
            except OSError as exc:
                log.warning("Router unavailable at %s (%s). Retrying...", router_path, exc)
                time.sleep(RETRY_SECONDS)
                continue

        try:
            readable, _, _ = select.select([sock], [], [], max(0.0, next_lcd - time.monotonic()))
            if readable:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("router closed the connection")
                unpacker.feed(data)
                for msg in unpacker:
                    handle_router_message(msg, sock, backend, lcd_errors)

            if time.monotonic() >= next_lcd:
                next_lcd = time.monotonic() + LCD_SECONDS
                for row, text in enumerate(lcd_lines(cpu)):
                    msgid = msgid % 1_000_000 + 1  # 0 is reserved for the register call
                    sock.sendall(msgpack.packb([REQUEST, msgid, "lcd_line", [row, text]]))
                backend.keep_alive()
        except OSError as exc:
            log.warning("Router connection lost (%s). Reconnecting...", exc)
            sock.close()
            sock = None
            time.sleep(RETRY_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="UNO Q buttons -> backend WebSocket, system stats -> LCD.")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8000/ws/input/")
    parser.add_argument("--router-socket", default=ROUTER_SOCKET)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        run(args.ws_url, args.router_socket)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
