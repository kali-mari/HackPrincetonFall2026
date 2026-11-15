# USB device test

The five-button demo uses this path:

```text
Elegoo UNO R3 -> Mac serial bridge -> USB ADB tunnel -> UNO Q Django/SQLite
Mac browser  -> Vite /api and /ws proxies -----------> UNO Q Django/SQLite
```

Both boards stay connected to the Mac. The R3 does not need a direct wire to the
UNO Q. Its buttons connect D2–D6 to GND; never connect these 5 V board pins to
UNO Q GPIO. The optional A0 sound input is disabled in the current firmware.

## Current board installation

The integration backend is `/home/arduino/aac-integration/backend` on UNO Q.
Its `.venv`, `.env`, `db.sqlite3`, `media`, and `models` link to the existing
installation under `/home/arduino/backend`. SQLite stays on UNO Q. The integration
code can be updated without copying the Mac's database or credentials.

The R3 was compiled on UNO Q with the ARM64 AVR compiler and flashed from the Mac
with native `avrdude`. The flash was read back and verified. Arduino's bundled
Intel AVR compiler failed on this Mac with `bad CPU type in executable`.

## Restart the demo

Run these from the repository root. Set `ADB` to the installed executable:

```sh
export ADB="$HOME/Library/Arduino15/packages/arduino/tools/adb/32.0.0/adb"
"$ADB" devices -l
```

Use the UNO Q identifier from that list as `<uno-q-id>`. With more than one ADB
device connected, always use `-s`. Serial port names can change after unplugging:

```sh
backend/.venv/bin/python -m serial.tools.list_ports -v
```

Choose the R3 port (USB VID:PID `2341:0043` on this setup), not the UNO Q serial
port (`2341:0078`). Close Arduino Serial Monitor before starting the bridge.

Terminal 1, only if the backend is not already running:

```sh
"$ADB" -s <uno-q-id> shell 'cd /home/arduino/aac-integration/backend && .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload'
```

Terminal 2, USB forwarding and R3 bridge:

```sh
"$ADB" -s <uno-q-id> forward tcp:8000 tcp:8000
backend/.venv/bin/python hardware/bridge.py --port <r3-serial-port> --verbose
```

Terminal 3, frontend:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://localhost:5173` and click **Tap to start** once to enable browser
audio. Keep the page open during the hardware test. Restart Vite after switching
branches if API requests return an empty 404 instead of Django JSON.

The backend currently has no speech-provider credentials. The frontend's **Backup
voice** uses the browser voice when `/api/speak` returns 503. Confirm sound is
audible; a successful API fallback alone does not prove that the speakers work.
Google Home should stay off for this test.

## Check each button

| Button | Pin | Expected bridge action | Board behavior |
| --- | --- | --- | --- |
| PREV | D2 | PREV | Scan backward |
| NEXT | D3 | NEXT | Scan forward |
| WORD | D4 | SELECT | Enter highlighted group or select a word |
| DEL | D5 | DELETE | Remove the last word |
| SAY | D6 | SPEAK | Speak a nonempty sentence |

Use **Space** for NEXT and **Enter** for SELECT to isolate a wiring problem from
the frontend. A green connection dot confirms the browser's WebSocket connection;
check the bridge log for actual physical button events. If a button produces no
event, check its pin, GND connection, and breadboard switch orientation.

For a complete test, select `I`, `want`, and `juice`, press SAY, hear the sentence,
and check **Caregiver dashboard** for the spoken event on UNO Q. Do not count an
empty-strip SAY press as an audio test.

## Caregiver Listen mode with the MacBook microphone

The built-in Mac microphone can supply audio while transcription stays on UNO Q.
FFmpeg captures 16 kHz mono WAV into a pipe on the Mac. A loopback-only relay and
ADB reverse tunnel carry it over USB to the existing UNO Q listener. No cloud
transcription is used, and neither audio nor transcripts are written to disk.
The optional laptop **Voice switch** is separate: it selects on a sustained sound,
whereas caregiver listening displays recognized speech without selecting anything.

With FFmpeg installed on both machines, start the relay on the Mac:

```sh
python3 hardware/mac_mic.py --device 'MacBook Pro Microphone'
"$ADB" -s <uno-q-id> reverse tcp:8766 tcp:8766
```

The relay opens the microphone only when the UNO Q listener connects. Allow macOS
microphone access if prompted. To find a different Mac audio device, run
`ffmpeg -f avfoundation -list_devices true -i ''` and supply its audio name or
index with `--device`.

Start the UNO Q backend with the streamed capture source (stop its existing
server first; only one ASGI process should run):

```sh
"$ADB" -s <uno-q-id> shell 'cd /home/arduino/aac-integration/backend && LISTEN_DEVICE=file:tcp://127.0.0.1:8766 .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload'
```

The board's existing environment must have `TRANSCRIBE_PROVIDER=moonshine` and
the Moonshine and Silero model files installed. This setup already does.
The `LISTEN_DEVICE` override above belongs to that server process; restart with
the same override. Recreate both ADB tunnels after reconnecting the UNO Q.

On the frontend, use **Input settings → Start caregiver listening**, press `L`,
or hold PREV+NEXT together. Wait for **Listening**, speak a short phrase, and pause.
The latest phrase appears above the board, usually several seconds after its end.
Use **Stop listening**, `L`, or the chord again to stop. Leaving for the caregiver
dashboard also stops capture. Stopping clears the transcript; it never becomes
a sentence, a saved communication event, or input to hosted AI predictions.

The mic closes before speech playback, including browser backup speech, and
reopens afterward if the caregiver still wants listening. Stop during playback
prevents it from reopening. The laptop vocal-selection switch is suspended during
caregiver listening and speech playback to prevent unintended selections.

Live verification: a spoken test phrase from the MacBook mic was displayed by
the frontend after UNO Q transcription. Playback pause/resume and Stop were
verified; after Stop, the Mac capture process was gone and the transcript cleared.
All 17 frontend tests and 10 hardware tests passed, as did frontend build/lint.
The 17 backend listener tests also passed on both Mac and UNO Q, including a
regression for a capture process stuck after SIGTERM. A fresh real start/stop
cycle confirmed no active FFmpeg capture remained on either device after Stop.

## Gemini predictions and local conversation choices

Standard predictions use Google Gemini with time, activity, confirmed recent
speech, and history-ranked phrases. Configure only `backend/.env` on the backend
host:

```dotenv
PREDICT_PROVIDER=gemini
PREDICT_MODEL=gemini-3.5-flash-lite
PREDICT_TIMEOUT_SECONDS=2
GEMINI_API_KEY=<your key, never commit or paste into chat>
```

The UNO Q network on this setup returned a TLS hostname mismatch for Google's
API. Keep certificate verification enabled and use the Mac's working connection
through this Gemini-only CONNECT tunnel:

```sh
python3 hardware/gemini_proxy.py
"$ADB" -s <uno-q-id> reverse tcp:8767 tcp:8767
```

Also set `GEMINI_PROXY_URL=http://127.0.0.1:8767` in the UNO Q's `backend/.env`
and restart the backend while preserving the Mac microphone `LISTEN_DEVICE`
override above. The tunnel binds to Mac loopback and only accepts
`generativelanguage.googleapis.com:443`. It forwards encrypted bytes, with TLS
verified end to end; it never reads/logs credentials, prompts, or responses.
Leave the proxy setting blank when running with working direct HTTPS.

The live UNO Q provider returned six valid phrases in about 1.08 s and 0.64 s;
a request to `/api/aac/predict` reported `source: ai` in about 0.75 s. Errors,
invalid JSON/phrases, exhausted quota, or calls over two seconds retain exactly
six history/default phrases. No retry or automatic model switching occurs.

During caregiver listening, a rolling window of the latest three phrases stays
in browser memory. Reviewed local topic matching supplies six conversation
choices, such as drink replies after a juice offer. This matcher is deterministic;
Gemini is used only for standard predictions, never for raw conversation context.
The child explicitly chooses a suggestion before it is spoken. A chosen and
successfully spoken phrase can then enter normal communication history.
Stopping listening clears context and immediately restores standard suggestions.

Live conversation verification: a juice topic switched the row to six reviewed
drink choices without speaking or adding anything to the sentence strip. Stop
cleared the transcript and restored the regular bedtime suggestions. Frontend
build/lint and 22 tests passed; 12 hardware tests passed. The 32 AI/prediction
backend tests passed on both Mac and UNO Q with mocked providers; separate live
Gemini calls verified the real network and model configuration.

## Favorite items stored with the patient

Open **Input settings → Caregiver dashboard → Favorite items**. Enter one item
per line in foods, drinks, and activities/toys, then choose **Save favorites**.
These lists are stored under `Profile.preferences.favorites` in UNO Q SQLite,
not browser storage. Each group allows 10 unique items of up to 60 characters.
Clear its text box and save to clear a group. Other voice/input preferences are
preserved. Existing profiles work without favorites; no migration is needed.

Relevant favorites contribute at most two of the six regular prediction cards
and personalize local conversation choices. Gemini also receives the explicit
favorites as JSON context; raw conversation transcripts remain local. Spoken
history is still collected separately and does not automatically become an
explicit favorite. Return to the board after saving to refresh both modes.

Verification: 174 backend tests passed on Mac and UNO Q, and 26 frontend tests,
build, and lint passed. A temporary synthetic patient was created with favorite
food/drink items; separate API requests read them from SQLite, duplicate updates
were rejected without changing stored data, and a live Gemini result returned
two relevant favorites among six choices in about 0.86 seconds. Slower calls
retained personalized fallback choices. Temporary test patients were deleted;
no favorite items were invented for the demo profile.

## Verification on this setup

- Updated `main` and `codex/device-integration` to merged commit `594f992`.
- UNO Q: all 165 backend tests passed; migrations were current.
- Mac: all 17 frontend tests, build, and lint passed; 8 bridge tests passed.
- Live predictions returned six phrases through Vite and the USB tunnel.
- A relayed DELETE changed the browser's sentence, and a spoken demo event was
  readable from SQLite on UNO Q.
- All five physical button actions reached the bridge. D3 initially produced no
  NEXT events; a temporary raw-pin diagnostic confirmed D3 goes LOW when grounded
  and HIGH on release. The normal AAC firmware was restored and verified afterward.

After the wiring check and firmware restore, the actual NEXT button produced
multiple NEXT events through the normal bridge. All five inputs are verified.

Full sentence check: keyboard scanning built `I want juice`; DELETE removed
`juice`, scanning reselected it, and SPEAK played the browser backup voice.
The user confirmed clear audio, the strip cleared, and the sentence appeared as
the newest caregiver history entry. Dashboard navigation now closes the settings
dialog before changing routes, so the hidden modal cannot trap keyboard access.
