# AAC backend

Django project: `config`. Application: `aac` (augmentative and alternative communication).

**Implemented:** runtime environment loading, SQLite/media/static path settings, local allowed hosts, restricted development CORS, reusable transport/value validators, OpenAPI contracts and offline Swagger UI, the six profile operations (caregiver/patient models, setup/preferences validation, caregiver-scoped patient pagination, the `seed_demo` command), and Phase 3 communication history: `POST /api/aac/events`, `GET /api/aac/patients/{id}/events` and legacy `POST /api/log`, with `CommunicationEvent` and a minimal `PredictionRecord` for attribution, Phase 4 deterministic predictions: `POST /api/aac/predict` and legacy `POST /api/predict`, and Phase 5 speech: `POST /api/aac/speak` and legacy `POST /api/speak` through a provider-neutral text-to-speech module (ElevenLabs first), with audio caching, a `cleanup_audio` command and optional Google Home casting.

**Still scaffolded:** the 9 learning operations return JSON 501. No frontend uses the profile routes yet and there is no patient switching, so Phase 2 is not complete end to end. `WS /ws/input/` is served by Channels through Daphne (`runserver` serves ASGI because `daphne` is first in `INSTALLED_APPS`), with the in-memory channel layer: run one process.

Follow the consolidated [MVP implementation plan](../docs/mvp-phase-plan.md), [API contracts/status](../docs/api-contracts.md) and [data outline](../docs/data-outline.md).

## Local setup

Python 3.12.12 is selected by `backend/.python-version` using pyenv.

```sh
cd backend
pyenv install -s 3.12.12
pyenv exec python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # first setup only; do not overwrite an existing .env
python manage.py check
python manage.py migrate
python manage.py seed_demo  # safe to rerun; keeps profile edits, restores missing seed history
python manage.py runserver 8000
```

Django reads `backend/.env` regardless of the shell's working directory. Existing process environment values take precedence. Restart Django after changing configuration. `.env` is ignored by git; never print or commit secrets, and never put backend credentials in frontend settings.

The server runs on `http://localhost:8000`:

- `/api/docs`: offline Swagger UI; implemented and scaffold operations are marked and Try it out is enabled.
- `/api/openapi.json`: OpenAPI 3.1 source for frontend tooling.
- `/api/profile/*`: implemented. Create caregivers and patients, list a caregiver's patients (`limit`, opaque `cursor`), and read, patch or delete a patient. Errors: 400 invalid fields/query/cursor, 404 unknown or wrong-role profile, 405 wrong method, 503 when SQLite storage is unavailable (no partial writes; the message never includes database details).
- `POST /api/aac/events`: saves a selection, spoken or feedback event. New event 201; identical retry (same `event_id`, same normalized content) 200; changed retry, a second spoken event for one utterance, or an utterance reused for another patient 409; unknown patient or prediction 404; text that does not match the referenced prediction candidate 400; storage failure 503.
- `GET /api/aac/patients/{id}/events`: newest first, `limit` and signed `cursor` like the patient list.
- `POST /api/log`: unchanged legacy shape; saves a spoken event for `LEGACY_DEMO_PATIENT_ID` and returns `{"ok": true}`. No retry safety; 503 if the demo patient has not been seeded.
- `POST /api/aac/predict`: six phrases ranked from the patient's confirmed spoken history, saved as a `PredictionRecord` whose ID the client sends back on attributed events. 404 unknown patient; 503 only if the record cannot be saved (unreadable history falls back to defaults).
- `POST /api/predict`: same ranking for `LEGACY_DEMO_PATIENT_ID`, legacy `{"phrases": [...]}` shape, no saved record. Always 200 for a valid request; defaults if the demo patient is missing or storage fails.
- `POST /api/aac/speak` and `POST /api/speak`: return `{"audio_url": ...}` for an MP3 under `/media/audio/`. Voice: the patient's `preferences.voice_id` (demo patient for legacy), else `SPEECH_VOICE_ID`. 503 when the provider is unconfigured or fails, or audio cannot be saved; never a fake URL. Speaking records no event. If `GOOGLE_HOME_HOST` is set, the audio is also cast in the background. Listen mode hears silence while the clip plays. Optional `"prefetch": true` only makes or reuses the cached clip (no cast, no listen pause), so the frontend can prepare the six predicted phrases.
- `/media/audio/<file>.mp3`: generated audio, served by Django in development (`DJANGO_DEBUG=true`).
- `/api/learn/*`: JSON 501, with 400 for malformed JSON transport and 405 for wrong methods.
- `/`: 404 expected.

The generated admin route remains; no application authentication has been added. Migrations create Django's internal tables plus `Profile`, `CaregiverPatient` (0001), `PredictionRecord` and `CommunicationEvent` (0002). Each event stores a patient-local `time_bucket` (`night` 0–5, `morning` 5–11, `midday` 11–14, `afternoon` 14–17, `evening` 17–21, `night` 21–24, defined in `aac/history.py`) computed from the patient's timezone when it is saved. Role-specific setup and link roles are checked by model validation on every `save()`; SQLite check constraints back the per-row rules, but bulk ORM writes skip the cross-row caregiver/patient role check. SQLite is also the chosen application store on UNO Q; no DynamoDB or second database.

## Runtime settings

| Variable | Default | Behavior |
| --- | --- | --- |
| `DJANGO_DEBUG` | `true` | Accepts true/false, 1/0, yes/no, on/off (case-insensitive); other values fail startup |
| `DJANGO_SECRET_KEY` | Local development key when debug is true | Set a private key for non-debug use; missing/blank or the built-in development key fails startup when debug is false |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Comma-separated hostnames/IPs, without schemes or ports |
| `SQLITE_PATH` | `db.sqlite3` | Database file; absolute or relative to `backend/` |
| `MEDIA_ROOT` | `media` | Future generated files; absolute or relative to `backend/` |
| `STATIC_ROOT` | `staticfiles` | `collectstatic` output; absolute or relative to `backend/` |
| `BACKEND_PUBLIC_BASE_URL` | `http://localhost:8000` | Absolute HTTP(S) base for future audio URLs; trailing slash removed; credentials/query/fragment rejected |
| `SPEECH_PROVIDER` | `elevenlabs` | Text-to-speech provider name registered in `aac/speech.py` |
| `SPEECH_VOICE_ID` | blank | Default provider voice ID (choose a child-sounding voice); blank makes speech 503 unless the patient sets `voice_id` |
| `SPEECH_MODEL_ID` | blank | Provider model; blank uses the provider default (`eleven_flash_v2_5` for ElevenLabs) |
| `SPEECH_CACHE` | `true` | Reuse audio for identical provider/model/voice/text instead of calling the provider again |
| `ELEVENLABS_API_KEY` | blank | Secret; `.env` only. Blank makes speech 503 |
| `TRANSCRIBE_PROVIDER` | blank | On-device speech-to-text loader registered in `aac/transcription.py` (`moonshine`); blank turns it off |
| `TRANSCRIBE_MODEL_DIR` | `models/moonshine-tiny-en` | Model files; absolute or relative to `backend/`. Filled by `manage.py fetch_transcription_model` |
| `TRANSCRIBE_THREADS` | `1` | CPU threads for decoding, 1 to 4 |
| `TRANSCRIBE_DEVICE` | `cpu` | Device passed to the model runtime; only `cpu` works on the UNO Q today |
| `LISTEN_DEVICE` | `default` | ALSA device listen mode records from with `arecord` (for example `plughw:1,0` for a USB mic; see `arecord -l`), or `file:<path>` to play an audio file in real time instead |
| `LISTEN_VAD_MODEL` | `models/silero_vad.onnx` | Silero voice detector that cuts the recording into phrases. Downloaded by `fetch_transcription_model` |
| `GOOGLE_HOME_HOST` | blank | Speaker IP; blank disables casting. Startup fails if set while `BACKEND_PUBLIC_BASE_URL` is localhost |
| `LEGACY_DEMO_PATIENT_ID` | `22222222-2222-4222-8222-222222222222` | Fixed synthetic patient created by `seed_demo` and used by `/api/log` (and later legacy speak/predict); must be a UUID (startup fails otherwise) and must differ from the demo caregiver `11111111-1111-4111-8111-111111111111`. Not a "currently selected patient" setting |

Create parent directories for custom SQLite paths before `migrate`, and ensure database/media locations are writable on UNO Q. Settings do not create application records (`seed_demo` does, including 20 synthetic spoken events from `seed/demo_history.json`), synthesize audio, or implement media serving. Public/static/media server deployment remains a later integration task. Keep custom generated-file paths outside version control; default SQLite files, `data/`, media and collected static files are ignored.

Development CORS permits **only `http://localhost:5173`**, for `/api/` routes, without credentials. JSON preflight requests are handled by CORS middleware; unfinished business calls still return 501. Other origins do not receive CORS permission. Non-CORS OPTIONS retains the documented method-discovery behavior.

This is an unauthenticated trusted-local-network demo, not a public deployment. CORS and allowed hosts are not authentication. Bind locally by default. For a later LAN demo, explicitly add the device IP/hostname to allowed hosts and configure reachable frontend/backend URLs. A speaker cannot fetch another device's `localhost`; casting and its LAN setup are not implemented in this slice.

## Shared request validation

`aac/http.py` exposes `check_method(request, methods)` (returns an OPTIONS/405 response or `None`) and `read_json_object(request)` (returns the parsed object). This preserves the existing UTF-8/64 KiB/finite-number checks while making parsed data available to real views.

`aac/validation.py` provides focused functions for required/unknown fields, bounded nonblank Unicode strings, hyphenated UUIDs, timestamps with explicit offsets (normalized to UTC), IANA timezones, strict JSON integers and page limits (default 50, range 1–100; repeated limits rejected). Strings trim by default; use `trim=False` where exact text must be preserved. Length limits apply before trimming.

Future plain views should check methods first, parse JSON, call explicit field validators and catch `InvalidRequest`, returning `error_response('invalid_request', str(error), 400)`. Validators do not echo submitted values. Record existence, roles/ownership, preferences, cursor decoding and other feature-specific rules still belong to their implementation slices. These are small functions, not automatic OpenAPI validation or a new schema framework.

Profile views use these helpers plus `profile_validation.py` (patient setup/preferences) and `profiles.py` (serialization and signed, caregiver-scoped keyset cursors). Event views use `history.py` (event validation, retry comparison, time buckets, serialization and patient-scoped cursors). Prediction views use `predictions.py` (request validation, ranking tiers, decay weights, tie ordering and curated defaults).

## Speech providers, caching and casting

`aac/speech.py` keeps providers separate from storage. A provider is a function `(text, voice_id, model_id) -> MP3 bytes` that raises `SpeechUnavailable` on failure; register it in `PROVIDERS` and set `SPEECH_PROVIDER`. Caching, file names, URLs, size limits and casting work the same for every provider. ElevenLabs is called with the standard library (`urllib`), a 10-second timeout and the voice ID URL-encoded.

With `SPEECH_CACHE=true`, the file name is a SHA-256 hash of provider, model, voice and text (never the text itself), so a repeated phrase is served from disk without a provider call. Files are written to a temporary name and renamed, so a concurrent request never sees a partial MP3. A cache hit refreshes the file's age.

`python manage.py cleanup_audio [--hours 24]` deletes MP3s (and leftover `.tmp` files) not used within the given hours. Run it manually or from cron; there is no worker.

Casting (`aac/casting.py`, PyChromecast) connects straight to `GOOGLE_HOME_HOST` without network discovery, in a background thread with 5-second bounds, after the audio URL is ready. It never delays or changes the HTTP response, and failures are logged without the URL or sentence. The speaker must reach `BACKEND_PUBLIC_BASE_URL` (a LAN address in `DJANGO_ALLOWED_HOSTS`). When casting is on, configure the frontend not to also play locally, to avoid double playback. Casting has not been tested against a real speaker yet. The 11 remaining scaffolds still validate transport only and return 501 even for `{}` or invalid field/query values.

## AI predictions

`aac/llm.py` adds optional AI phrases to both prediction routes. Set in `backend/.env`:

| Provider | `PREDICT_PROVIDER` | Credentials | `PREDICT_MODEL` |
| --- | --- | --- | --- |
| OpenAI, or any OpenAI-compatible API | `openai` | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` for OpenRouter, Groq, xAI, Mistral, Ollama, ...) | required |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | optional, defaults to `claude-haiku-5-5` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | optional, defaults to `gemini-3.5-flash-lite` |
| Amazon Bedrock (any Converse text model) | `bedrock` | standard AWS credentials (`aws login`, `AWS_PROFILE`, keys) and `AWS_REGION` | required: model or inference profile ID |

Blank `PREDICT_PROVIDER` turns AI off. Pick a fast model ID from your provider's model list: answers slower than `PREDICT_TIMEOUT_SECONDS` (default 2) are dropped, and reasoning-heavy models often miss that. Only the selected provider's SDK is imported.

Gemini requests use a JSON schema requiring exactly six phrases and minimal
thinking on Gemini 3 models, with SDK retries disabled. Google documents
[Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) as a
low-latency model with structured output support. The parser still checks length,
uniqueness, and printable text before accepting a response.
If UNO Q cannot reach Google over verified HTTPS, the USB demo can set
`GEMINI_PROXY_URL=http://127.0.0.1:8767` with the restricted local tunnel in
`hardware/gemini_proxy.py`; see [device testing](../docs/device-testing.md).
This does not disable TLS verification or send conversation transcripts to Gemini.

A provider is a function `(system, prompt, model) -> text` that raises on failure; register it in `PROVIDERS`. The rest is shared: the history/default phrases are computed first and sent with `activity`, time bucket and `recent` as JSON data; the call runs on a small thread pool and the view waits at most the deadline (SDK timeouts are only a 10-second safeguard, and SDK retries are off). Output must be exactly six unique, nonblank, single-line phrases of at most 100 characters, otherwise the fallback is used; there is no repair call. At most 4 calls run at once, so a slow provider can't pile up threads. Prompts, responses and keys are never logged.

Prediction tests force `PREDICT_PROVIDER=''`, so a provider in your `.env` is never called by `manage.py test`.

## On-device transcription

`aac/transcription.py` turns one speech segment into text for caregiver listen mode, on the device, with no cloud call. `transcribe(pcm)` takes 16 kHz mono signed 16-bit PCM (at most 30 seconds) and returns text; it raises `TranscriptionUnavailable` when the provider is blank or its model or runtime is missing. Audio and transcripts stay in memory and are never logged.

A provider is a loader `(model_dir, threads, device) -> decode(samples) -> text`; register it in `PROVIDERS` (and its download in `MODEL_ARCHIVES`) and set `TRANSCRIBE_PROVIDER`. The model loads on first use and stays resident; one decode runs at a time. To try a different model, add a loader. To try a GPU, set `TRANSCRIBE_DEVICE` to a runtime provider the loader's runtime supports; callers do not change.

`moonshine` is Moonshine tiny (English, int8) through sherpa-onnx. On the UNO Q it measured about a third of one CPU core on one thread, which leaves the other cores for Django and the frontend. Numbers and the GPU attempts are in `hardware/benchmarks/transcription/SHERPA.md`.

```sh
# in backend/.env: TRANSCRIBE_PROVIDER=moonshine
python manage.py fetch_transcription_model          # one-time download, about 120 MB, plus the voice detector
python manage.py transcribe_file sample.wav         # prints the text and decode time
python manage.py listen                             # live: prints each phrase from the mic; Ctrl-C stops
python manage.py listen --device file:sample.wav    # the same with a recording played in real time
```

### Listen mode

`aac/listen.py` records from the microphone on the board (`arecord` on `LISTEN_DEVICE`), cuts the audio into phrases with the Silero voice detector in sherpa-onnx (a phrase ends after about half a second of silence, or at 10 seconds), and transcribes each phrase on a second thread. If transcription falls behind, the oldest waiting phrase is dropped. `WS /ws/conversation/` (`ConversationConsumer`) starts and stops it for one connection at a time and sends each phrase back as `{"type": "transcript", "seq": n, "text": ...}`; the contract is in `docs/api-contracts.md`. While the board speaks, the listener hears silence: each successful speak response calls `listen.pause()` for the clip's length (from the MP3 size at 128 kbit/s) plus a start-up margin, so the board's own voice is not transcribed. Audio and text are never written or logged; the server logs only how long after each phrase its text was ready.

`LISTEN_DEVICE=file:<path>` decodes the file with ffmpeg and hands it to the voice detector at real-time speed, so it behaves like a microphone for demos and timing tests.

For a USB microphone, find its card with `arecord -l` and set `LISTEN_DEVICE=plughw:<card>,0`; `plughw` converts the mic's own rate to 16 kHz mono. Check it with `python manage.py listen` before using the frontend.

## Checks and tests

```sh
pip install -r requirements-dev.txt
python manage.py check
python manage.py test
python manage.py export_openapi > /tmp/aac-openapi.json
```

Tests cover isolated runtime settings/dotenv precedence (including `LEGACY_DEMO_PATIENT_ID`), paths, invalid configuration, allowed hosts, browser preflight/origin restrictions, value validators, parsed JSON access and helper composition in a test-only plain view, contracts/examples, offline documentation assets, the 11 remaining scaffolds, the profile feature, event history (retries, conflicts, attribution, pagination, legacy log, cascade deletion, seeded history) predictions (defaults, decay, context tiers, case-insensitive merging, deterministic ties, patient isolation, attribution round trip, fallbacks) and speech (mocked provider, voice selection, caching, file naming, failures, ElevenLabs request shape and errors, cleanup, casting dispatch, prefetch, listen-mode pause) and listen mode (capture pipeline with a fake source and voice detector, pause, backlog, `/ws/conversation/` messages checked against the OpenAPI schemas). No test calls a real provider or speaker. Profile tests run against Django's migrated test database: response schemas, validation, role scoping, pagination/cursors, deletion, atomic rollback, 503 handling, database constraints and `seed_demo`. Configuration tests substitute a temporary dotenv file and a cleared environment rather than reading a developer's secrets. No AWS or device is required.

Manual HTTP smoke checks after starting Django:

```sh
curl -i http://localhost:8000/api/docs
curl -i -X OPTIONS http://localhost:8000/api/predict \
  -H 'Origin: http://localhost:5173' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
curl -i http://localhost:8000/api/predict \
  -H 'Origin: http://localhost:5173' \
  -H 'Content-Type: application/json' --data '{}'
```

Expected: Swagger 200, preflight 200 with the permitted origin, business request JSON 501 with the same CORS header. After `seed_demo`, `curl http://localhost:8000/api/profile/caregivers/11111111-1111-4111-8111-111111111111/patients` lists the demo patient.

Runtime-slice verification: `manage.py check` and all 29 tests passed on Python 3.12.12. A live local HTTP smoke test verified Swagger, permitted preflight, JSON 501 with CORS headers and omission of permission for an untrusted origin. Migrations and `collectstatic` succeeded with temporary configured paths, including the offline Swagger bundle; the existing database was untouched. UNO Q, browser UI, hardware and cloud smoke tests remain pending.

Validation-slice verification: `manage.py check` and all 43 tests passed on Python 3.12.12. Tests cover wrong types/booleans, unknown/missing fields, offset normalization and UTC overflow, invalid IANA names, ambiguous page limits, exact body-size boundaries and the existing error envelope. No database, board or cloud service was used.

Profile-slice verification: `manage.py check`, all 64 tests and `makemigrations --check` passed on Python 3.12.12. A manual smoke test against a temporary `SQLITE_PATH` ran migrate, `seed_demo` twice, caregiver/patient create, patch, delete and a 400 case, then restarted Django and confirmed the changes persisted; the developer database was untouched. No frontend, UNO Q or hardware test yet.

Event-history verification: `manage.py check`, all 79 tests and `makemigrations --check` passed. Manual smoke test on a temporary database: seed, event 201 → identical retry 200 → changed retry 409, `/api/log` 200, then a restart with all 22 events still listed newest first.

Speech verification: all 114 tests passed. Live server smoke test without an API key: both speak routes returned 503 `Speech is not configured.` with no file written, and `/media/audio/` served an MP3 with `audio/mpeg`. Real ElevenLabs and Google Home calls are untested until a key, voice and speaker are configured.

Prediction verification: all 93 tests passed. Manual smoke test on a seeded temporary database returned activity-appropriate suggestions (breakfast, lunch, bedtime), time-of-day history for an unknown activity, and the legacy shape.

## Layout

```text
config/                     Runtime settings, URLs, HTTP ASGI and WSGI entrypoints
.env.example                Placeholder-only runtime configuration
requirements.txt            Django, CORS middleware and dotenv (pinned)
aac/
  documentation.py          Working schema and Swagger views
  openapi.py                Contract source; each operation marked implemented or scaffolded
  static/aac/               Offline Swagger assets and initializer
  templates/aac/            Swagger HTML
  urls.py                   Namespaced HTTP route wiring
  models.py                 Profiles, links, prediction records and events (SQLite)
  profile_validation.py     Patient setup/preferences validation
  profiles.py               Profile JSON and signed patient-list cursors
  history.py                Event validation, time buckets, event JSON and cursors
  transcription.py          Provider-neutral on-device speech-to-text (Moonshine via sherpa-onnx)
  views.py                  CSRF-exempt function views: profiles, events, log, plus JSON 501 scaffolds
  http.py                   Reusable method/JSON transport checks and scaffolds
  validation.py             Explicit value/field/query helpers; no ORM access
  listen.py                 Listen mode: mic capture, voice detection, phrase transcription
  consumers.py, routing.py  WS /ws/input/ relay (validation, origin check, no echo) and WS /ws/conversation/ listen mode
  speech.py                 Provider-neutral TTS (ElevenLabs), caching and audio files
  predictions.py            Deterministic ranking and defaults
  llm.py                    Optional AI predictions (OpenAI, Anthropic, Gemini, Bedrock) with deadline and fallback
  casting.py                Optional background Google Home casting
  management/commands/      Schema export, seed_demo and cleanup_audio
  migrations/               Application migrations (0001 profiles, 0002 history)
  tests/                    Runtime, contract/documentation, scaffold and profile tests
seed/                       Synthetic demo history loaded by seed_demo
media/audio/                Ignored generated audio
```

Next backend slice: Phase 7 labels; the bridge and buttons are in `hardware/`.
