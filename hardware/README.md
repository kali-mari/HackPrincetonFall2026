# Hardware: switch board and serial bridge

The Elegoo UNO R3 (an Arduino Uno clone) reads five buttons and an optional sound sensor and prints one token per line over USB serial. `bridge.py` turns each line into a JSON message on the backend WebSocket `ws://localhost:8000/ws/input/`.

- `aac_switch/aac_switch.ino`: the sketch for the demo.
- `test/test.ino`: wiring check. It prints friendly messages and live sound levels, not the protocol.
- `bridge.py`: serial to WebSocket bridge.

For the two-board USB setup (Mac bridge/frontend, UNO Q backend/SQLite), see
[device testing](../docs/device-testing.md).

`mac_mic.py` optionally supplies the MacBook microphone to UNO Q caregiver Listen
mode through a local USB tunnel. It captures only during an active listening
session; see the same guide for setup. This is separate from the A0 vocal switch.

## Single-board setup (UNO Q only)

Everything can run on the Arduino UNO Q with no UNO R3 and no Mac bridge:

- `unoq_board/`: Arduino app whose sketch runs on the UNO Q's microcontroller. It reads the five buttons on D2-D6 (same wiring and tokens as below, including the PREV + NEXT listen chord) and drives a 16x2 LCD1602 on D7-D12 (RS D7, E D8, D4 D9, D5 D10, D6 D11, D7 D12, RW to GND). There is no vocal switch in this setup.
- `unoq_bridge.py`: runs on the UNO Q's Linux side. It forwards button presses to `ws://127.0.0.1:8000/ws/input/` and writes CPU %, RAM used, load and running jobs to the LCD once a second. It talks to the sketch through the board's Bridge (`arduino-router`), not a serial port.

On the board (over `adb shell`; `TMPDIR=/tmp` is needed because adb sets a temp folder that does not exist):

```bash
# 1. Build, flash and start the sketch. Copy unoq_board/ to /home/arduino/ArduinoApps/aac-board first.
#    Keep the app running: stopping it also stops the sketch.
TMPDIR=/tmp arduino-app-cli app start user:aac-board

# 2. Install the bridge dependencies into the backend's Python, then start it.
/home/arduino/aac-integration/backend/.venv/bin/python -m pip install -r /home/arduino/hardware/requirements.txt
/home/arduino/aac-integration/backend/.venv/bin/python /home/arduino/hardware/unoq_bridge.py
```

The sketch avoids the LiquidCrystal library so the board does not need to download anything to build it.

## Wiring

Buttons use `INPUT_PULLUP`: wire each one between its pin and GND (pressed = LOW). No resistors needed.

| Pin | Input | Serial line |
| --- | --- | --- |
| D2 | PREV button | `PREV` |
| D3 | NEXT button | `NEXT` |
| D4 | WORD button (select) | `SELECT` |
| D5 | DEL button | `DELETE` |
| D6 | SAY button | `SPEAK` |
| A0 | sound sensor (optional vocal switch) | `VOICE` |
| D2 + D3 | PREV and NEXT held together | `LISTEN` |
| GND | button common rail | |

## Upload the sketch

1. Run `test/test.ino` first and check that every button prints when pressed.
2. Open `aac_switch/aac_switch.ino` in the Arduino IDE, pick the board **Arduino Uno** (the Elegoo UNO R3 uses the same board setting) and port, and upload. Or, with `arduino-cli`:
   ```sh
   arduino-cli compile --fqbn arduino:avr:uno hardware/aac_switch
   arduino-cli upload  --fqbn arduino:avr:uno -p <serial port> hardware/aac_switch
   ```
3. Optional check in the Serial Monitor at 9600 baud: each press prints one token, such as `NEXT`. Then close the Serial Monitor, because only one program can hold the port.

### Calibrate the vocal switch

At the top of the sketch:

- `SOUND_THRESHOLD`: A0 level that counts as sound (0 to 1023).
- `SOUND_HOLD_MS`: how long the sound must last before `VOICE` fires (500 ms).
- `SOUND_GAP_MS`: dips shorter than this don't reset the timer, and after firing the level must stay quiet this long before the switch can fire again.

Set `DEBUG = true` to print `# sound <level>` once a second while you tune the threshold (the bridge ignores those lines). Set it back to `false` before the demo. The default `SOUND_THRESHOLD` is 1024, which disables the vocal switch so a floating A0 pin can't fire `VOICE`. Lower it only after connecting and calibrating a sound sensor.

### Listen chord

Holding PREV and NEXT together prints `LISTEN` once; the frontend uses it to toggle caregiver listen mode. It fires again only after both buttons are released. Each button still prints its own `PREV`/`NEXT` first, and the two cancel out on the scan.

## Run the bridge

```sh
python -m venv hardware/.venv
source hardware/.venv/bin/activate
pip install -r hardware/requirements.txt

# Find the port: ls /dev/cu.usb* (macOS), ls /dev/ttyACM* (Linux), Device Manager (Windows COMx)
python hardware/bridge.py --port /dev/cu.usbmodem1101
```

Options: `--baud 9600`, `--ws-url ws://localhost:8000/ws/input/`, `--verbose` (log ignored lines and every send).

`--dry-run` prints the JSON for each press instead of sending it, so you can test the Arduino with no backend:

```sh
python hardware/bridge.py --port /dev/cu.usbmodem1101 --dry-run
# {"action": "NEXT", "source": "button"}
```

The bridge reconnects to the serial port and the WebSocket on its own and prints one line when either connects or drops. Presses made while the WebSocket is down are dropped, not replayed, so a stale press never selects something later. If the port won't open, close the Arduino Serial Monitor (or any other program using it).

Tests (no hardware needed): `python -m unittest discover hardware/tests`.

## Protocol

Serial: 9600 baud, one uppercase token per line, newline terminated. Anything else is ignored.

| Input | Serial line | WebSocket message |
| --- | --- | --- |
| D2 PREV | `PREV` | `{"action": "PREV", "source": "button"}` |
| D3 NEXT | `NEXT` | `{"action": "NEXT", "source": "button"}` |
| D4 WORD | `SELECT` | `{"action": "SELECT", "source": "button"}` |
| D5 DEL | `DELETE` | `{"action": "DELETE", "source": "button"}` |
| D6 SAY | `SPEAK` | `{"action": "SPEAK", "source": "button"}` |
| D2 + D3 held together | `LISTEN` | `{"action": "LISTEN", "source": "button"}` |
| A0 sound | `VOICE` | `{"action": "SELECT", "source": "voice"}` |
| legacy, no hardware | `TOUCH` | `{"action": "SELECT", "source": "touch"}` |

The keyboard fallback (Space = NEXT, Enter = SELECT) lives in the frontend and is not part of this protocol.
