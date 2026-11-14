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
- **Committed and in review:** everything below is on this branch, in PR
  [kali-mari/HackPrincetonFall2026#4](https://github.com/kali-mari/HackPrincetonFall2026/pull/4)
  against `main`. The repo has no CI checks.

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

Backend:

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

1. **Audio in, text out.** No microphone capture, no voice detection in the
   backend, and no route that sends transcripts to the frontend. Conversation Mode
   has no endpoint contract in `docs/api-contracts.md`; agree that with the team
   before adding a route. The benchmark's `vad_segments.py` (WebRTC VAD policy) is
   the segmenter that was measured and can be reused.
2. **Transcription beside the running app** on the board has not been measured.
3. **Real microphone, room noise** and short everyday caregiver phrases are untested.
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
.venv/bin/python manage.py runserver 0.0.0.0:8000
```
