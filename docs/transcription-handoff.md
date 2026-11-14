# Transcription handoff (branch `feat/transcription-gpu-support-unoq`)

Written 2026-11-14. Picks up from the UNO Q transcription benchmarks.

## Where things stand

- **Decision:** on-device transcription uses **Moonshine tiny on the CPU**, one
  thread. The GPU is not used.
- **Why not the GPU:** whisper.cpp Vulkan fails at first decode on the Adreno 702,
  the board's OpenCL driver lacks a feature the OpenCL backend needs, and
  Moonshine's runtime (ONNX Runtime) has no GPU path for this GPU on Linux. Details
  in `hardware/benchmarks/transcription/GPU_OFFDEVICE.md` and `GPU_NEWBACKEND.md`.
- **Why it no longer matters:** Moonshine measured about 0.38 of one core on the
  5-minute session, against about three cores for Whisper. That leaves the other
  cores for Django and the frontend.
- **Listen mode is built:** `aac/listen.py` records the board's microphone with
  `arecord`, cuts phrases with the Silero voice detector (sherpa-onnx), and
  transcribes them; `WS /ws/conversation/` streams them to one connection. It
  was measured beside the frontend on the board (below). Only a real-microphone
  test is left.
- **Committed and in review:** everything below is on this branch, in PR
  [kali-mari/HackPrincetonFall2026#4](https://github.com/kali-mari/HackPrincetonFall2026/pull/4)
  against `main`. The repo has no CI checks.

## Listen mode, measured beside the app (UNO Q, 2026-11-14)

The 5-minute caregiver session (`natural_long`) was played in real time as the
microphone (`LISTEN_DEVICE=file:...`) into the real Django server, through
`WS /ws/conversation/`. In the second run the frontend from `origin/Nirmal` was open
in headless Chromium on the board, getting a simulated button press every second.

| | Server alone | Beside the frontend |
|---|---|---|
| Word accuracy | 94.3% (51 errors / 889 words) | 94.3% (same text) |
| Phrases / dropped | 36 / 0 | 36 / 0 |
| Text after a phrase ends (median / p95 / max) | 4.2 / 5.8 / 8.5 s | 4.2 / 5.9 / 8.7 s |
| Server process CPU (avg / max) | 0.52 / 1.08 cores | 0.53 / 1.11 cores |
| Chromium CPU (avg / max) | - | 0.30 / 0.52 cores |
| Whole board busy (avg / max, of 4 cores) | 0.63 / 1.24 | 0.96 / 1.51 |
| Server peak memory | 428 MiB | 425 MiB |
| Time from `start` to listening (model load) | 5.6 s | 5.9 s |

Accuracy is higher than the benchmark's Moonshine + WebRTC VAD (90.7%) because the
Silero detector cuts phrases more cleanly. Headless Chromium had no GPU, so a kiosk
browser on the board's display may cost more or less. Another Django server (from
`/home/arduino/aac-integration`) was idle on port 8000 during both runs; the
measurement used port 8010. Scripts are on the board in `/home/arduino/listen-measure/`. The delay is from the end
of a phrase in the audio to its text being ready: half a second of silence to end the
phrase, then decoding at about 0.4 s per second of speech, so long phrases wait longer.

Side finding for the frontend owner: with the `origin/Nirmal` frontend, `/api/predict`
returned 400 (the backend rejects a blank `activity` and a `time` without a timezone
offset), and `/api/speak` returned 503 because the board has no speech keys.

## Measured on the UNO Q (one CPU thread, clean recordings)

| 5-minute session | Zipformer (streaming) | Moonshine + VAD | Whisper q5_1, 3 threads |
|---|---|---|---|
| Word accuracy | 91.0% | 90.7% | 89.9% |
| CPU while audio plays | 0.35 core | 0.38 core | about 3 cores |
| Text delay (median) | 0.01 s per chunk | 3.9 s after a pause | 8.3 s |
| Peak memory | 140 MiB | 312 MiB | 188 MiB |

Moonshine's delay on short phrases is lower: 0.5 s for a 2-word reply, 1.9 s for a
6-second sentence. Both new models produce no text on silence. Full tables and
caveats: `hardware/benchmarks/transcription/SHERPA.md`.

Zipformer is the alternative if live word-by-word text is wanted. It was not chosen
because its output is upper case without punctuation and it dropped the first two
words of one short clip.

## What changed on this branch

Backend (listen mode):

- `backend/aac/listen.py`: `Listener` (capture, voice detection, transcription
  thread, drops the oldest phrase if the model falls behind).
- `backend/aac/consumers.py`, `routing.py`, `config/asgi.py`: `ConversationConsumer`
  at `WS /ws/conversation/`.
- `backend/aac/management/commands/listen.py`: prints each phrase and its delay.
- Settings `LISTEN_DEVICE` and `LISTEN_VAD_MODEL`; `fetch_transcription_model` also
  downloads the voice detector.
- `backend/aac/tests/test_listen.py` (14 tests, no model, mic or network).
- Contract in `docs/api-contracts.md` and `CLAUDE.md`.

Backend (transcription):

- `backend/aac/transcription.py`: `transcribe(pcm)` for one speech segment
  (16 kHz mono 16-bit PCM, at most 30 s). Loaders are registered in `PROVIDERS`.
- `backend/config/settings.py`, `backend/.env.example`: `TRANSCRIBE_PROVIDER`
  (blank = off, default), `TRANSCRIBE_MODEL_DIR`, `TRANSCRIBE_THREADS`,
  `TRANSCRIBE_DEVICE`.
- `backend/aac/management/commands/fetch_transcription_model.py` and
  `transcribe_file.py`.
- `backend/aac/tests/test_transcription.py` (7 tests, no model or network).
- `backend/requirements.txt`: adds `sherpa-onnx==2.0.1`.
- `backend/.gitignore`: ignores `models/`.
- `backend/README.md` and `CLAUDE.md`: transcription section and rule.

Benchmarks (`hardware/benchmarks/transcription/`):

- `setup_sherpa.py`, `sherpa_bench.py`, `test_sherpa.py`, `SHERPA.md`, and four new
  allow-lines in that folder's `.gitignore`.

## How to extend it

- **Another model:** add a loader `(model_dir, threads, device) -> decode(samples)`
  to `PROVIDERS` in `transcription.py`, add its download to `MODEL_ARCHIVES`, and
  allow its name in the `TRANSCRIBE_PROVIDER` check in `settings.py`.
- **A GPU later:** `TRANSCRIBE_DEVICE` is passed to the runtime as its provider
  name. If a working GPU runtime appears, it is a settings change for a loader that
  supports it, or a new loader.

## Verified

- Mac: all 145 backend tests pass; `fetch_transcription_model` downloaded the model
  and `transcribe_file` returned the correct text for the read clip.
- UNO Q: the backend is installed in a venv and `manage.py transcribe_file` returned
  the correct text for the same clip (5.9 s of audio in 2.08 s). See board state.

## Board state (UNO Q, reached over USB ADB)

ADB binary: `~/Library/Application Support/arduino_applab_workspace/arduino15/data/packages/arduino/tools/adb/32.0.0/adb`

- `/home/arduino/hardware/benchmarks/transcription/`: benchmark scripts, and under
  `local/sherpa/` the wheels, both models and all result folders.
- `/home/arduino/backend/`: a copy of this branch's backend (no `.env` secrets,
  no database copied), with `.venv` created by `python3 -m venv --without-pip` and
  pip 25.1.1 bootstrapped from its wheel.
- **No system packages were installed.** `sudo` on the board asks for a password,
  so the apt route was not used; the venv approach above needs no root.
- **Requirements are installed in that venv, offline.** The board's network
  returned a certificate for the wrong host when pip contacted PyPI, so pip refused
  (TLS checks were left on). The 77 ARM64 / Python 3.13 wheels were downloaded on
  the Mac with `pip download ... --platform manylinux2014_aarch64 --python-version
  3.13 --only-binary=:all:` and installed from `/home/arduino/backend/wheels` with
  `pip install --no-index --find-links wheels -r requirements.txt -r requirements-dev.txt`.
- The model is in `/home/arduino/backend/models/moonshine-tiny-en/`, and
  `/home/arduino/backend/.env` contains only `TRANSCRIBE_PROVIDER=moonshine`. No
  API keys are on the board, so speech and AI predictions are off there.
- `manage.py migrate` ran, and `manage.py transcribe_file` returned the correct text
  on the board through real Django settings (5.9 s of audio in 2.08 s).
- `manage.py test aac` on the board: the first run had 1 failure of 145 that was
  not captured; two reruns passed all 145. Treat one test as possibly flaky on the
  slower board and capture the name if it recurs.
- `runserver` was not started on the board.
- The board copy is a snapshot. After changing backend code on the Mac, push it
  again (exclude `.venv`, `.env`, `models/`, `*.sqlite3`).

## Not done

1. **Real microphone.** Not tested: no USB mic was plugged into the board. Plug one
   in, find its card with `arecord -l`, set `LISTEN_DEVICE=plughw:<card>,0` in
   `/home/arduino/backend/.env`, and run `.venv/bin/python manage.py listen`. Try
   short everyday caregiver phrases with room noise.
2. **Frontend wiring** (owner of the frontend): on `LISTEN`, send `start`/`stop` on
   `/ws/conversation/` and show the latest transcripts. Contract in
   `docs/api-contracts.md`.
3. **Backup voice pause** (frontend): the backend now blanks the mic while its own
   clips play, but the frontend's browser backup voice bypasses the backend; send
   `stop` before it and `start` after.
4. **Merge PR #4** once it is reviewed.

## Pick-up commands

Mac:

```sh
cd backend && source .venv/bin/activate
python manage.py test aac
TRANSCRIBE_PROVIDER=moonshine python manage.py transcribe_file <16k-mono.wav>
```

Board (after `adb shell`):

```sh
cd /home/arduino/backend
.venv/bin/python manage.py transcribe_file /home/arduino/hardware/benchmarks/transcription/local/sherpa/backend-check/read16.wav
.venv/bin/python manage.py listen --device file:/home/arduino/hardware/benchmarks/transcription/local/experiment2/fixtures/read_short.wav
.venv/bin/python manage.py listen                     # real mic, once LISTEN_DEVICE is set
sh /home/arduino/listen-measure/measure.sh alone      # repeat the 5-minute measurement (port 8010)
.venv/bin/python manage.py runserver 0.0.0.0:8000     # port 8000 may already be taken by aac-integration
```
