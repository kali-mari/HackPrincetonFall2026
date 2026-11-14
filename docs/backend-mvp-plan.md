# Backend MVP plan

## Goal and constraints

Deliver one complete demo loop:

1. A child selects symbols and builds a sentence in the frontend.
2. The backend generates speech; the frontend plays it.
3. The frontend records the spoken sentence through the backend.
4. The backend suggests exactly six phrases using time, activity, and history.
5. Arduino switches control frontend scanning through a WebSocket relay.

The backend is currently an empty directory. This document is a plan, not a claim that these features exist.

Keep the 36-hour demo first: one Django app, one demo persona, one server process, no auth, and no general-purpose framework of our own. Existing contracts in `AGENTS.md` remain unchanged. Proposals below about limits, errors, data layout, and playback ownership need team agreement before implementation.

## Dependency philosophy

Build application behavior in house: validation, phrase ranking, fallback rules, prompt construction, audio file handling, and orchestration should be small functions we own.

Do not implement networking protocols, AWS request signing, or speech/model engines ourselves. In-house application logic does not mean self-hosting Polly, Bedrock, or DynamoDB; those remain the project's agreed services. Replacing them would be a separate scope decision.

### Direct runtime dependencies

| Dependency | Why it earns its place |
| --- | --- |
| Django | Existing project framework; HTTP, settings, URLs, responses, commands, tests. |
| channels | Existing WebSocket contract and group broadcast. |
| daphne | ASGI server; put first in `INSTALLED_APPS` so `runserver` supports WebSockets. |
| django-cors-headers | Existing project convention; correct browser CORS handling without custom middleware. |
| boto3 | One SDK for Polly, Bedrock, and DynamoDB; avoid hand-written AWS authentication/retries. |
| python-dotenv | Small, deliberate convenience for loading the required `backend/.env`. Avoid a home-grown dotenv parser or requiring shell exports on every launch. |

Pin versions after confirming a compatible Python/Django/Channels stack. Dependencies will bring transitive packages; list direct dependencies deliberately rather than pretending everything is dependency-free.

### Optional dependency

- `pychromecast`, only when implementing Google Home casting. Keep it separate from core requirements if possible. Cast discovery and protocol handling are not a useful hackathon reinvention.

### Use built-ins instead

- `json`: request and model-output parsing.
- `datetime` and `zoneinfo`: timestamp validation and local time buckets.
- `collections.Counter`: fallback phrase frequency ranking.
- `pathlib`, `uuid`, `hashlib`: audio files, safe names, optional repeat-speech cache.
- `logging`: operational diagnostics without sentence/credential logging.
- `unittest.mock`, Django tests, Channels test utilities: tests; no pytest or cloud-emulation stack initially.
- `concurrent.futures` and `time.monotonic`: bounded model wait/deadline coordination if required.

Do not add DRF, serializers, Pydantic, LangChain, Celery, Redis, requests, an ORM for DynamoDB, a vector database, or an agent framework. No repositories/interfaces/plugin systems until a real requirement needs them.

## Architecture and ownership

```text
Frontend -- HTTP --> Django views --> Polly / Bedrock / DynamoDB
Frontend <-- WS --> Channels input group <-- WS --> serial bridge <-- Arduino
Google Home <-- audio URL + optional Cast command -- backend
```

- Frontend owns symbols, sentence construction, scanning, playback controls, keyboard fallback, and input settings.
- Backend owns API validation, speech generation, history persistence, predictions, and optional casting.
- Bridge owns serial-to-WebSocket translation and reconnect behavior.
- Hardware owns button debounce and sustained-sound detection; do not confuse the sound switch with speech transcription.
- Keyboard fallback remains Space = NEXT and Enter = SELECT, even without hardware.
- UI team retains large targets (at least 120px), high contrast, and an unmistakable scanning highlight.

### Suggested file layout

```text
backend/
  manage.py
  requirements.txt
  requirements-cast.txt        # optional, only if casting is implemented
  .env.example                # placeholders only
  config/
    settings.py
    urls.py
    asgi.py
  aac/
    views.py                  # thin HTTP handlers and small shared validation helpers
    consumers.py              # input relay only
    routing.py
    speech.py                 # Polly and local audio files
    predictions.py            # ranking, prompt, model-output validation, fallback
    history.py                # direct DynamoDB operations
    casting.py                # optional, isolated Google Home integration
    management/commands/
      seed_history.py
      cleanup_audio.py        # add when generated files need cleanup
    tests/
      test_views.py
      test_predictions.py
      test_history.py
      test_input.py
  seed/
    demo_history.json
  media/audio/                # generated files, ignored by git
```

Start with the files a milestone actually needs. These are focused modules, not separate services. AWS clients should be created lazily and reused, not constructed on every request; startup and tests should not need working AWS access. Keep synchronous boto3 operations out of the WebSocket event loop.

## Build order and acceptance criteria

### 1. Foundation

Tasks:
- Create the Django project and one `aac` app.
- Configure Channels, Daphne, and the in-memory channel layer.
- Allow CORS from `http://localhost:5173`, not every origin.
- Load environment configuration and provide a placeholder-only `.env.example`.
- Ignore `.env`, virtual environments, generated audio, and Python caches.
- Keep SQLite for Django internals only.
- Use plain function views and `JsonResponse`; API views are `@csrf_exempt` with no auth.
- Reject unsupported methods and malformed JSON cleanly.

Suggested error shape to agree with frontend:

```json
{ "error": { "code": "invalid_request", "message": "text must be a nonempty string" } }
```

Suggested statuses: 400 invalid input, 405 unsupported method, 503 required upstream unavailable. Prediction fallback is a successful 200 response, not an error. Do not expose stack traces, SDK payloads, or credentials in responses.

Done when: Django runs at `http://localhost:8000`, frontend requests pass CORS, and invalid requests receive useful JSON errors.

### 2. Speech: first working vertical slice

Contract:

```http
POST /api/speak
Content-Type: application/json

{ "text": "I want water" }
```

```json
{ "audio_url": "http://localhost:8000/media/audio/generated-id.mp3" }
```

Implementation:
- Validate and trim text; proposed limit: 500 characters. Require an actual string, not a coerced number/object.
- Use Polly neural speech and a child-sounding voice. Confirm that the chosen voice supports neural synthesis in the configured region before the demo.
- Request MP3 and save it under a server-generated filename. Never derive a path from submitted text.
- Close the returned audio stream after writing. Expose audio through Django's development media serving for the local demo only.
- Use local files rather than S3 for this demo: one less service and no extra storage integration.
- Return an absolute URL built from a configured public backend base URL where needed.
- Keep files around long enough for playback; clean old files with a small management command, not a scheduled worker system.
- Return a clear failure when Polly is unavailable. Do not fabricate a successful URL or silently substitute speech without team agreement.
- Optional after the basic path works: hash text + voice + engine to reuse audio. Bound disk usage; do not prioritize cache machinery over playback.

Done when: frontend submits a sentence and the browser plays the returned audio.

### 3. Hardware input relay

Contract: `WS /ws/input/`

```json
{ "action": "NEXT", "source": "button" }
```

- Accept only `NEXT` or `SELECT`, and `button`, `touch`, or `voice`.
- Join every connection to the single `input` Channels group; leave on disconnect.
- Validate JSON shape and reject malformed/oversized messages without broadcasting them.
- Broadcast only the agreed action/source fields. Group callbacks send to clients; they must not re-broadcast and create loops.
- Bridge translates serial `NEXT`, `SELECT`, `TOUCH`, `VOICE` into the agreed action/source combinations. Agree which action touch and voice trigger with the hardware/frontend team.
- Frontend clients consume broadcasts; they should not echo received messages back into the socket.
- Use origin validation for local browser connections while testing that the non-browser bridge can connect.
- Run one backend process: the in-memory channel layer does not work across multiple server processes.

Done when: a message from one WebSocket client reaches another, then a real bridge event advances/selects the frontend highlight.

### 4. Phrase history

Contract:

```http
POST /api/log
Content-Type: application/json

{ "text": "I want water", "timestamp": "2026-11-14T12:00:00Z" }
```

The success response is not specified by the shared contract. Propose `200` with `{ "ok": true }` and agree with the frontend first.

Implementation:
- Validate text and an ISO timestamp with a timezone; normalize storage timestamps to UTC.
- Use one DynamoDB table and a fixed demo-persona partition; no user management.
- Proposed partition key: `persona_id`; sort key: canonical UTC timestamp plus UUID to prevent simultaneous events overwriting each other.
- Store `text`, UTC timestamp, and the time-of-day bucket computed in a configured demo timezone. No raw audio, transcripts, or credentials.
- Query a bounded recent history window for the persona rather than scanning the whole table. Handle pagination within the chosen bound.
- Keep ranking in Python for this small demo; no indexes or aggregate tables initially.
- Add a management command to load `backend/seed/demo_history.json`. Use stable seed IDs so rerunning the seed does not duplicate it. Never delete live history during seeding.
- Return an explicit error if persistence fails. Predictions may still use seed/default data; failed writes must not pretend they were stored.

Suggested ownership: the frontend calls `/api/log` after successful playback, not the backend inside `/api/speak`. Do not log mere speech generation. Agree how Cast playback affects this; Cast command acceptance is not proof the sentence finished playing.

The existing contract has no idempotency key. Avoid automatic blind retries and document that duplicate submissions can create duplicate history. Do not silently deduplicate repeated intentional speech.

Done when: a spoken sentence is stored and internal history retrieval supplies prediction ranking.

### 5. Contextual predictions

Contract:

```http
POST /api/predict
Content-Type: application/json

{
  "time": "2026-11-14T12:00:00Z",
  "activity": "lunch",
  "recent": ["I want water"]
}
```

```json
{
  "phrases": ["I want water", "More please", "I am hungry", "All done", "Help me", "Thank you"]
}
```

Every successful response contains exactly six concise, nonempty phrases. Never automatically select or speak them.

#### Implement deterministic suggestions first

1. Validate input types and timezone-aware time. Proposed bounds: activity 100 characters, recent at most 20 entries, each at most 500 characters.
2. Compute a local time bucket, with boundaries defined once and covered by tests.
3. Rank frequent phrases for that time of day using `Counter` over the bounded history window.
4. Fill gaps with all-time frequent phrases, matching seed phrases, then a curated default list of at least six unique phrases.
5. Trim and deduplicate case-insensitively while preserving stable order; return the first six.

This path must work before adding AI. History failure should fall through to seed/default phrases, not break suggestions.

#### Add Bedrock as a bounded enhancement

- Use the existing boto3 dependency and Bedrock Runtime Converse API directly; no AI framework.
- Configure a fast Claude Haiku model or supported inference profile via environment configuration. Verify access and regional availability before integration; do not assume a model ID works in every account.
- Set an explicit small output-token limit.
- Ask for JSON with exactly six short AAC phrases. Send only time bucket, activity, and bounded relevant history/recent phrases.
- Treat submitted context as data, not instructions. Validate parsed output rather than trusting the prompt.
- Reject malformed JSON, wrong shapes/counts, empty or excessive-length phrases, and duplicates; use the deterministic fallback. Do not run another model call to repair output.
- Avoid raw prompt/response logging; sentence history may reveal sensitive needs.

#### Make the two-second fallback real

The contract requires fallback when Bedrock fails or exceeds two seconds. Network read/connect timeouts alone are not an end-to-end deadline, and retries can multiply wait time.

- Prepare a fallback before waiting on the model. Keep history reads bounded and allow seed/default fallback when history is unavailable.
- Use a monotonic deadline for the model wait and disable SDK retries for this latency-sensitive call.
- Set short connection/read timeouts as an additional safeguard.
- If using a worker future, use a shared, bounded executor and return fallback when the deadline expires. Do not use a request-scoped executor context manager that waits for completion on exit.
- A timed-out future does not stop an in-flight network call. Bound worker count and outstanding submissions; if capacity is exhausted, return fallback immediately. No unbounded request queue.
- Test delayed upstream calls to verify the HTTP response does not wait for their eventual completion.
- Keep this helper local to prediction logic; it is not a new task queue service.

Done when: valid input always yields six usable suggestions, including with empty history, missing AWS access, malformed model output, timeouts, or exhausted model-call capacity.

### 6. Optional Google Home integration

The speech contract requires casting when a device is configured; absence of a configured device should not block the browser demo.

- Isolate Cast code and its optional dependency.
- Prefer a configured device/address for the demo over repeated discovery on every sentence.
- A Google Home cannot fetch `localhost` on the laptop. Configure a LAN-reachable backend base URL, bind Django appropriately, and allow the required host explicitly. Test firewall and shared Wi-Fi access.
- Keep discovery and Cast operations bounded. Failures must not turn otherwise successful `/api/speak` responses into errors or delay playback indefinitely.
- Always return the normal `audio_url`; do not add response fields without agreement.
- Decide with frontend how to prevent duplicate browser + speaker audio. The current response cannot report whether casting actually succeeded. For MVP, agree on a manual output-mode setting and a browser fallback control rather than silently changing the API.
- Playback-completion-aware logging for Cast needs an agreed behavior; do not claim successful playback based only on dispatching a command.

Done when: configured speaker playback works, and disconnecting the device does not break speech generation or the browser fallback.

## Configuration and security

Proposed configuration names, not committed secrets:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- `AWS_REGION` and required local AWS credential/session values in ignored `backend/.env` only
- `DYNAMODB_TABLE_NAME`
- `BEDROCK_MODEL_ID`
- `POLLY_VOICE_ID`
- `DEMO_TIMEZONE`
- `BACKEND_PUBLIC_BASE_URL`
- `GOOGLE_HOME_ENABLED`, `GOOGLE_HOME_HOST` if casting is implemented

Keep AWS credentials out of frontend bundles, seed data, docs, responses, and logs. Do not enable SDK wire-level debug logging. Treat an unauthenticated local demo as a trusted-network tool, not an internet-ready service; CORS is not authentication. Avoid logging raw sentence bodies and clean up generated speech files after the demo.

## Testing with minimal tooling

Run tests with `python manage.py test`; use Django's client, `unittest.mock`, and Channels WebSocket test utilities. Do not require real AWS, a real speaker, or Arduino in automated tests. Add a test-only dependency only if the selected Channels tooling requires it.

Required cases:
- Every HTTP route: valid request, malformed JSON, wrong type, missing field, oversized input, wrong method, upstream failure.
- Speech: valid audio file/URL, closed stream, safe filename, failure without fabricated success.
- WebSocket: two-client broadcast, invalid action/source, malformed messages, disconnect, no rebroadcast loop.
- History: timestamp normalization, simultaneous events, bounded reads, seed rerun, persistence failure.
- Predictions: exactly six unique phrases, stable fallback ranking, timezone boundaries, sparse history, unavailable history, invalid model output, timeout, bounded-worker saturation.
- Cast: disabled mode, successful dispatch, unreachable speaker without failed speech response.

Mock at narrow module boundaries. Unit tests should exercise our logic, not reimplement AWS behavior. Run separate manual smoke tests against real Polly, Bedrock, and DynamoDB before demo day.

## Team decisions to settle early

1. Frontend owns playback and `/api/log`; what counts as spoken in browser and Cast modes?
2. Agree error JSON, `/api/log` success JSON, and validation limits.
3. Agree touch/voice action mappings with bridge and UI owners.
4. Pick demo timezone, activity labels, voice, verified model configuration, and seed persona.
5. Agree output-mode behavior without changing `/api/speak` silently.
6. Confirm LAN audio access if Google Home is in the demo.

## Out of scope

- Authentication, multiple profiles/users, caregiver analytics endpoints.
- Redis, Celery, multi-process deployment, cloud deployment infrastructure.
- RAG, embeddings, agents, custom training, complicated personalization.
- Conversation transcription or topic detection.

Conversation Mode remains a stretch goal only after the core demo works: explicit caregiver activation, visible listening indicator, stop control, in-memory rolling transcript cleared on stop, no persisted raw audio/transcripts, six suggestions, and no automatic selection/speech. If it fails, ordinary predictions remain available. Any new API contract or transcription provider needs team agreement first. The Arduino sound sensor remains only an input switch.

## Suggested execution checklist

- [ ] Foundation, placeholder environment file, validation conventions.
- [ ] Polly speech through real browser playback.
- [ ] WebSocket relay through two clients, then the real bridge.
- [ ] DynamoDB history and repeatable demo seed.
- [ ] Deterministic six-phrase suggestions.
- [ ] Bounded Bedrock enhancement and failure tests.
- [ ] Optional configured Google Home casting and browser fallback.
- [ ] End-to-end rehearsal and setup instructions.

Leave at least the final quarter of backend time for integration, AWS access issues, LAN/speaker problems, and failure-path rehearsal. Cut optional caching or Cast discovery polish before cutting reliable speech, switch input, or prediction fallback.

## Final demo acceptance

A child can build a sentence, hear it, and receive six relevant suggestions. A physical switch advances/selects the board. Spoken history persists. Bedrock failure does not remove suggestions; a disconnected speaker does not break browser speech. A teammate can start the backend from documented commands without seeing or sharing credentials.
