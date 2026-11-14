# API contracts and Swagger UI

## What works now

| Route | Status |
| --- | --- |
| `GET /api/docs` | Implemented: Swagger UI with locally bundled assets |
| `GET /api/openapi.json` | Implemented: OpenAPI 3.1 document |
| Backend runtime configuration | Implemented: `backend/.env`, configurable SQLite/media/static paths, local allowed hosts and development CORS |
| Shared transport/value helpers | Implemented and tested; used by the profile routes |
| Profile routes (6 operations) | Implemented: SQLite persistence, field/query/cursor validation, role scoping, 503 on storage failure |
| Event history: `POST /api/aac/events`, `GET /api/aac/patients/{id}/events`, `POST /api/log` | Implemented: SQLite persistence, retry safety, prediction attribution checks |
| Predictions: `POST /api/aac/predict`, `POST /api/predict` | Implemented: deterministic history ranking with defaults; no cloud access |
| Speech: `POST /api/aac/speak`, `POST /api/speak` | Implemented: provider-neutral TTS (ElevenLabs), cached MP3s under `/media/audio/`, optional Google Home casting |
| Learning (9 operations) | Wired as scaffolds: JSON 501; transport errors use 400/405 |
| `WS /ws/input/` | Message contract documented; consumer not implemented |
| Conversation Mode/topic timeline | Stretch design only; no endpoint contract yet |

The **contract/documentation layer, HTTP route scaffolds, profile operations and event history** deterministic predictions and speech are implemented; AI integration is not. Each operation carries `x-implementation-status` (`implemented` or `scaffolded`); scaffolds also have `[SCAFFOLD]` in their Swagger summary. Swagger's Try it out is enabled. Scaffold success examples describe target behavior; they are never returned as fake successes.

### Profile operations (implemented)

- `POST /api/profile/caregivers`, `POST /api/profile/patients` (creates the patient and its caregiver link atomically), `GET /api/profile/caregivers/{id}/patients`, and `GET`/`PATCH`/`DELETE /api/profile/patients/{id}`.
- Request and normal success shapes match the original contract. Unknown/missing fields, blank or oversized strings, invalid IANA timezones, `language` other than `en`, and invalid `preferences` return 400. `PATCH` replaces `preferences` as a whole object. Role, ID and caregiver link are not editable.
- A caregiver ID used as a patient ID (or the reverse) is 404, like an unknown ID.
- Patient lists use ascending UUID order with a signed opaque cursor bound to the caregiver; a tampered, repeated or other-caregiver cursor is 400. The last page returns `next_cursor: null` (no empty terminal page).
- **Additive 503:** all six profile operations may return `503 { "error": { "code": "unavailable", "message": "Profile storage is unavailable." } }` when SQLite is unavailable (for example, an unmigrated or unwritable database). Writes roll back; database details are never included.
- Demo setup: `python manage.py seed_demo` idempotently creates the caregiver `11111111-1111-4111-8111-111111111111` and the patient set by `LEGACY_DEMO_PATIENT_ID` (default `22222222-2222-4222-8222-222222222222`), linked. Reruns keep edits. It fails without writing if either ID is already used by the wrong role or the two IDs are equal. An invalid `LEGACY_DEMO_PATIENT_ID` fails Django startup. `/api/log` uses this fixed patient. `seed_demo` also adds 20 synthetic spoken events from `backend/seed/demo_history.json` with deterministic IDs; a rerun restores missing seed rows and leaves the rest alone.

### Event history (implemented)

- `POST /api/aac/events` follows the event lifecycle below. 201 new; 200 identical retry (compared after normalization: trimmed text, UTC timestamp); 409 changed retry, second spoken event for an utterance, or an `utterance_id` already used by another patient; 404 unknown/caregiver patient or a `prediction_id` not saved for that patient; 400 for invalid fields, a lone `prediction_id`/`candidate_index`, `outcome` on non-feedback events, or text that differs from the referenced candidate; 503 storage failure.
- Each event stores a patient-local time bucket computed from the patient's timezone at event time: `night` [0,5), `morning` [5,11), `midday` [11,14), `afternoon` [14,17), `evening` [17,21), `night` [21,24). Defined once in `backend/aac/history.py` for Phase 4 ranking.
- `GET /api/aac/patients/{id}/events` returns newest first by `(timestamp, event_id)` with a signed cursor bound to the patient; 404 for unknown/caregiver IDs.
- `POST /api/log` keeps its legacy request shape and returns `200 {"ok": true}`. It saves a spoken event for `LEGACY_DEMO_PATIENT_ID` with fresh server IDs. No retry safety: repeated calls add repeated speech. 503 when storage is unavailable or the demo patient is not seeded.
- **Schema change (additive):** `Event.input_source` is now nullable. It is `null` only for events saved through `/api/log`, which carries no input source.
- `POST /api/aac/predict` creates the `PredictionRecord` that attributed events reference.
- Deleting a patient also deletes their events and prediction records.

### Predictions (implemented)

Ranking lives in `backend/aac/predictions.py` and needs no network access.

- Evidence is the patient's confirmed `spoken` events only (latest 1,000); selections, feedback, displayed suggestions and `recent` are not evidence. Other patients' history is never used.
- Each event adds `0.5 ** (max(0, age_days) / 7)` to its phrase, with age measured from the request `time`. Phrases merge after trim/case-fold; the newest spelling is shown.
- Tiers fill the six slots in order: same activity and time bucket, same activity, same time bucket, all history, then curated defaults (`I want water`, `More please`, `I am hungry`, `All done`, `Help me`, `Thank you`, then `Yes`, `No`, `I need a break`, `Bathroom please`). Activity matching ignores case and surrounding spaces.
- Ties: higher score, then more recent last use, then case-folded phrase alphabetically. Identical requests return identical phrases.
- `source` is `history` when any phrase came from history, otherwise `default`. `artifact_version` is always null for now.
- `POST /api/aac/predict` saves activity, time bucket, phrases and source (never `recent`). Unreadable history falls back to defaults with 200; **additive 503** only when the prediction record itself cannot be saved, since returning an unsaved `prediction_id` would break attribution. Unknown/caregiver patient is 404.
- `POST /api/predict` keeps `{"phrases": [...]}`, uses `LEGACY_DEMO_PATIENT_ID`, saves nothing, and returns defaults (200) if that patient is missing or storage fails.

### Speech (implemented)

- **Provider change:** speech now uses a provider-neutral module (`SPEECH_PROVIDER`, currently ElevenLabs) instead of Polly. Request and response shapes are unchanged.
- Both routes return `200 {"audio_url": "<BACKEND_PUBLIC_BASE_URL>/media/audio/<hash or random>.mp3"}`. File names never contain the submitted text.
- Voice: `preferences.voice_id` of the patient (or the fixed demo patient for `/api/speak`), else `SPEECH_VOICE_ID`. Voice IDs are provider-specific.
- `503 unavailable` when the provider is unconfigured (no key or voice), fails or times out, returns empty/oversized audio, or the file cannot be saved. No fake URLs and no provider error text. `/api/aac/speak` returns 404 for an unknown or caregiver patient.
- Identical provider/model/voice/text reuses the cached file (`SPEECH_CACHE`, default on). `cleanup_audio` removes files unused for 24 hours.
- Speaking never records an event; the frontend records `spoken` after playback completes.
- With `GOOGLE_HOME_HOST` set, audio is also cast in the background; the response is unaffected and cast failures are only logged. The frontend should not also play audio locally in that mode.

### Scaffold operations

Current behavior of the 9 remaining business operations:

- Expected methods with an acceptable transport return `501 { "error": { "code": "not_implemented", "message": "<operationId> is scaffolded; feature implementation is pending." } }`, with `Cache-Control: no-store`.
- POST/PATCH require `Content-Type: application/json` and a UTF-8 JSON object no larger than 64 KiB; invalid bodies (including non-finite numbers) return JSON 400. Field/query/schema/relationship validation on business routes is **not implemented**; even `{}` reaches 501. Reusable value validators and parsed-body access now exist for upcoming feature handlers; scaffolds do not apply them.
- Unsupported methods return JSON 405 with `Allow`. Non-CORS OPTIONS returns empty 204 with `Allow`; HEAD follows GET without a response body. Browser CORS preflight is handled separately by middleware (200), allowing only `http://localhost:5173` for `/api/` routes without credentials. This does not implement business behavior or authentication.
- UUID path converters reject invalid UUID strings with Django's ordinary 404. Valid UUIDs reach the scaffold without checking record existence. Unknown paths/trailing slashes also return ordinary 404, not the future resource-error contract.
- No database, AWS/provider calls, audio generation, or device side effects from scaffolds. API views are CSRF-exempt as required by the local demo conventions.

## Run and inspect

```sh
cd backend
source .venv/bin/activate
pip install -r requirements.txt
# First setup only; leave an existing .env intact.
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 8000
```

Open:

- http://localhost:8000/api/docs
- http://localhost:8000/api/openapi.json

The single source of truth is [`backend/aac/openapi.py`](../backend/aac/openapi.py). It explicitly defines request/response schemas, required fields, enums, limits, examples, status codes and behavioral rules. No DRF, serializers, npm installation, or cloud connection is required to serve documentation.

Export the same schema for frontend tooling or contract review:

```sh
python manage.py export_openapi > /tmp/aac-openapi.json
```

Do not maintain a second hand-edited schema. Update the contract, outline and tests together. Defining a schema does not add runtime request validation to future views: implement those checks and response contract tests when adding each handler.

## Contract groups

- `profile`: create caregivers/patients, link on patient creation, read/update setup, delete patient data.
- `aac`: patient-scoped speech, exactly six predictions, explicit events, paginated history.
- `learn`: vocabulary definitions, caregiver assignments/review, bounded analysis, learning summary/configuration activation.
- `legacy`: existing `/api/speak`, `/api/predict`, `/api/log` shapes for a fixed demo patient.
- `documentation`: the two working routes above.

### Target feature rules

The following behavior remains the implementation contract, not functionality supplied by the scaffolds:

- JSON bodies; UUID identifiers; timezone-aware ISO timestamps, normalized to UTC. Reject malformed JSON, unsupported types, unknown fields, blank text and oversized values.
- IDs establish relationships, not identity. The demo has no authentication. Synthetic data and trusted local access only; CORS/HTTPS/Caddy do not make it safe for public patient use.
- New HTTP paths have no trailing slash. OpenAPI uses a relative same-origin server URL for portability through a reverse proxy.
- Error body: `{ "error": { "code": "invalid_request", "message": "..." } }`. Codes used by the contract: `invalid_request` (400), `not_found` (404), `method_not_allowed` (405), `conflict` (409), `not_implemented` (501 during scaffolding), `unavailable` (503). Include `Allow` on 405. Do not expose stack traces or provider payloads.
- Prediction fallback is successful `200`, not `503`. Required speech/persistence/analysis failure must not pretend success.
- Paginated patient/event/definition lists return a named array plus `next_cursor` (string or null), default 50/max 100 records. Event order is descending `(timestamp,event_id)`; patient/definition lists use stable ascending UUID order. Cursors are opaque, bound to patient/filter/order; malformed or mismatched cursors are 400.
- Review operations require current `revision`; stale revisions and invalid transitions are 409. Clients cannot set origin, approval status, immutable IDs, categories or scoped codes through creation/edit requests.
- Profile creation, prediction and analysis have no general idempotency key; do not blindly retry writes. Only event writes and duplicate effective assignments have the explicit retry behavior below.

### Event lifecycle and feedback

1. A prediction returns six phrases and a `prediction_id`; merely displaying it is not an event.
2. Client creates an `utterance_id` for one intended utterance and distinct `event_id` values for selection, completed speech and optional feedback.
3. Reuse `event_id` only to retry the identical normalized event: first write 201, identical retry 200, changed payload 409. Do not silently merge repeated intentional speech.
4. Only completed playback creates `kind=spoken`. Cancellation, playback error, or unconfirmed Google Home dispatch does not. There is at most one spoken event per patient/utterance; a second distinct spoken event returns 409. A changed or intentionally repeated utterance gets a new utterance ID.
5. Prediction attribution supplies both `prediction_id` and zero-based `candidate_index`, with an exact text match for that patient's prediction. Omit both for composed/edited phrases. Feedback always supplies both plus text and `outcome`.
6. Count confirmed spoken utterances once, not selections plus speech plus accepted feedback. Ignored suggestions are neither positive examples nor explicit rejections.

Current event input sources are `button` and `keyboard`. Space advances scanning; Enter selects. Touch hardware is not present. No automated prediction expiry during the hackathon; aging changes relevance, not record existence. Weight confirmed spoken occurrences by `0.5 ** (max(0, age_days) / 7)` for history ranking, first within matching activity/time bucket, then broader history/defaults. Case-insensitive deduplication and stable tie ordering must be implemented in ranking.

### Label and analysis lifecycle

See [label-vocabulary.md](label-vocabulary.md) for fixed starter categories/values and patient custom definitions. Definition approval and assignment confirmation are separate. AI proposals never become effective solely because their confidence is high. Caregiver corrections take precedence; archive/correction invalidates derived context.

`DefinitionReview.action=edit` requires at least one display field. Approval may also edit display fields. Mapping a proposal requires an existing active target in the same category/allowed scope. `AssignmentReview.action=correct` supersedes the old assignment and returns a new confirmed assignment; it does not rewrite history.

Analysis is synchronous and bounded: `[from,to)` at most 30 days, latest 1,000 events, at most 10 new definitions/3 assignment proposals per event. Results report count, cutoff and truncation. Empty history returns empty proposals and null candidate version. Configure a finite provider deadline in implementation; failure returns 503 without changing effective labels or active configuration. External ordinary-history analysis requires explicit caregiver consent, with consent storage/UX deferred before real-data use. Conversation tables/context are excluded.

Activation requires the expected active version (null initially) and current vocabulary revision. A learning artifact is application configuration/context, not trained Jev weights. Generation of new labels is optional; ordinary caregiver labeling works without AI.

## Storage and deployment decision

SQLite on UNO Q replaces the original DynamoDB history plan. Use Django ORM/migrations, JSON fields for small flexible payloads, and local filesystem storage for generated audio/model files. No object database or second storage service is needed. Automated retention and backup infrastructure are out of hackathon scope; use synthetic fixtures, gitignored local data and manual reset.

UNO R4 WiFi handles buttons; UNO Q is the default Django/database host. Future server deployment should change environment configuration, not API paths. Local runtime settings now load from `backend/.env`; see [backend setup](../backend/README.md) for path, host and public-URL configuration. Profile migrations exist (`aac/migrations/0001_initial.py`); target/server deployment and a Caddyfile remain unimplemented. Run an ASGI server behind Caddy for HTTP/WebSockets; retain one process with the in-memory Channels layer. Do not use `runserver` as the public server or expose the unauthenticated API to the internet.

Conversation Mode remains a separate local-only stretch feature. Raw audio/transcripts stay in memory. Approved scope permits device-local saved suggestion batches and categorical topic segments, not transcript persistence. Do not migrate those tables to a remote server or expose them through public proxy routes. See [data-outline.md](data-outline.md) for the timeline design and unresolved split-deployment boundary.

## WebSocket contract (not an OpenAPI HTTP operation)

`WS /ws/input/` uses a single Channels group, `input`, with messages:

```json
{ "action": "NEXT", "source": "button" }
```

- `action`: `PREV | NEXT | SELECT | DELETE | SPEAK`.
- `source`: `button | touch | voice`. Buttons send any action; `voice` (optional sound-sensor switch) and `touch` (legacy, no current hardware) always send `SELECT`.
- Serial input is plain text at 9600 baud, one token per line, mapped by `hardware/bridge.py`:

| Input | Serial line | WebSocket message |
| --- | --- | --- |
| D2 PREV | `PREV` | `{"action": "PREV", "source": "button"}` |
| D3 NEXT | `NEXT` | `{"action": "NEXT", "source": "button"}` |
| D4 WORD | `SELECT` | `{"action": "SELECT", "source": "button"}` |
| D5 DEL | `DELETE` | `{"action": "DELETE", "source": "button"}` |
| D6 SAY | `SPEAK` | `{"action": "SPEAK", "source": "button"}` |
| A0 sound | `VOICE` | `{"action": "SELECT", "source": "voice"}` |
| legacy | `TOUCH` | `{"action": "SELECT", "source": "touch"}` |

- The bridge drops presses while the WebSocket is down; it never replays them.
- Keyboard is local frontend input, not a new WebSocket source.
- No conversation audio/transcripts on this broadcast group.

The schema includes `InputMessage` and an `x-websocket` extension for reference. Swagger does not test a WebSocket handshake or streaming behavior.

## Validate and test

```sh
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py check
python manage.py test
```

Runtime tests cover dotenv precedence, paths, invalid configuration, allowed hosts and restricted CORS/preflight. Shared-helper tests cover required/unknown fields, strict strings/UUIDs/integers, offset timestamps/UTC overflow, IANA timezones, bounded query limits, transport size boundaries and safe error envelopes via a test-only view. Contract tests validate OpenAPI 3.1, every explicit JSON example, refs, unique operation IDs, path parameters, invalid event/review payloads, legacy field shapes, six-phrase constraints, documentation routes, schema export and offline asset discovery. Route tests exercise the 9 remaining scaffolds with documented example bodies, validate actual 501 envelopes, verify method/CSRF behavior, JSON transport errors and request size limits, and forbid database access. Profile tests use the migrated test database and validate responses against the OpenAPI schemas, plus validation, role scoping, pagination/cursors, deletion, atomic rollback, 503 handling, database constraints and `seed_demo`; runtime tests cover valid and invalid `LEGACY_DEMO_PATIENT_ID`. Event tests cover retries, conflicts, attribution scope and exact text, validation, time buckets, pagination/cursors, legacy log, cascade deletion, 503 handling and seeded history. Prediction tests cover defaults, decay, context tiers, case-insensitive merging, deterministic ties, patient isolation, the event attribution round trip and fallbacks. Speech tests use a mocked provider and speaker: voice selection, caching, file naming, failures, ElevenLabs request shape, cleanup and casting dispatch. Test validators are development dependencies only.

Swagger UI 5.31.0 assets are vendored with Apache-2.0 LICENSE/NOTICE; see [`vendor/README.md`](../backend/aac/static/aac/vendor/swagger-ui/README.md). The UI uses no CDN and disables the online validator/query overrides. On a server with `DEBUG=False`, collect static files and have Caddy serve the collected static directory; this deployment configuration remains future work.

## Next implementation slices

Use [mvp-phase-plan.md](mvp-phase-plan.md) for the detailed sequence, dependencies, core/optional priorities, endpoint ownership, parallel workstreams and acceptance checks. Summary:

1. ~~Profiles, SQLite models/migrations, and validation shared by plain function views.~~ Backend done; frontend use pending.
2. ~~Idempotent event recording and deterministic time-decayed predictions with contract tests.~~ Done.
3. Speech generation/playback integration and existing input relay.
4. Caregiver label creation/assignment/review.
5. Optional bounded AI analysis/Jev integration; Conversation Mode only after the core demo and benchmarks.

For each slice: replace the scaffold with real handlers, add field/query/relationship validation and response/persistence tests, remove that operation's temporary 501 response, and mark it implemented. Swagger execution is already enabled; success must never be advertised until the feature actually works.
