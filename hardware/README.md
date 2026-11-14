# Hardware: switch board and serial bridge

The Arduino reads five buttons and an optional sound sensor and prints one token per line over USB serial. `bridge.py` turns each line into a JSON message on the backend WebSocket `ws://localhost:8000/ws/input/`.

- `aac_switch/aac_switch.ino`: the sketch for the demo.
- `test/test.ino`: wiring check. It prints friendly messages and live sound levels, not the protocol.
- `bridge.py`: serial to WebSocket bridge.

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
| GND | button common rail | |

## Upload the sketch

1. Run `test/test.ino` first and check that every button prints when pressed.
2. Open `aac_switch/aac_switch.ino` in the Arduino IDE, pick the board (Arduino Uno) and port, and upload. Or, with `arduino-cli`:
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

Set `DEBUG = true` to print `# sound <level>` once a second while you tune the threshold (the bridge ignores those lines). Set it back to `false` before the demo. Without a sound sensor, set `SOUND_THRESHOLD` to 1024 to turn the vocal switch off, so a floating A0 pin can't fire `VOICE`.

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
| A0 sound | `VOICE` | `{"action": "SELECT", "source": "voice"}` |
| legacy, no hardware | `TOUCH` | `{"action": "SELECT", "source": "touch"}` |

The keyboard fallback (Space = NEXT, Enter = SELECT) lives in the frontend and is not part of this protocol.
