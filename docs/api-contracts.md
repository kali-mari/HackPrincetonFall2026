# API contracts and Swagger UI

## What works now

| Route | Status |
| --- | --- |
| `GET /api/docs` | Implemented: Swagger UI with locally bundled assets |
| `GET /api/openapi.json` | Implemented: OpenAPI 3.1 document |
| Backend runtime configuration | Implemented: `backend/.env`, configurable SQLite/media/static paths, local allowed hosts and development CORS |
| Shared transport/value helpers | Implemented and tested; business-route field validation remains pending |
| Profile, AAC, learning and legacy business routes | Wired as scaffolds: JSON 501; transport errors use 400/405 |
| `WS /ws/input/` | Message contract documented; consumer not implemented |
| Conversation Mode/topic timeline | Stretch design only; no endpoint contract yet |

The **contract/documentation layer and HTTP route scaffolds** are implemented, not profile CRUD, persistence, prediction, audio synthesis or AI integration. Every business operation has `[SCAFFOLD]` in its Swagger summary and `x-implementation-status: scaffolded` in the schema. Swagger's Try it out is enabled to inspect real scaffold responses. Success examples describe target behavior; they are never returned as fake successes.

Current behavior of all 22 business operations:

- Expected methods with an acceptable transport return `501 { "error": { "code": "not_implemented", "message": "<operationId> is scaffolded; feature implementation is pending." } }`, with `Cache-Control: no-store`.
- POST/PATCH require `Content-Type: application/json` and a UTF-8 JSON object no larger than 64 KiB; invalid bodies (including non-finite numbers) return JSON 400. Field/query/schema/relationship validation on business routes is **not implemented**; even `{}` reaches 501. Reusable value validators and parsed-body access now exist for upcoming feature handlers; scaffolds do not apply them.
- Unsupported methods return JSON 405 with `Allow`. Non-CORS OPTIONS returns empty 204 with `Allow`; HEAD follows GET without a response body. Browser CORS preflight is handled separately by middleware (200), allowing only `http://localhost:5173` for `/api/` routes without credentials. This does not implement business behavior or authentication.
- UUID path converters reject invalid UUID strings with Django's ordinary 404. Valid UUIDs reach the scaffold without checking record existence. Unknown paths/trailing slashes also return ordinary 404, not the future resource-error contract.
- No database, AWS/provider calls, audio generation, or device side effects. API views are CSRF-exempt as required by the local demo conventions.

## Run and inspect

```sh
cd backend
source .venv/bin/activate
pip install -r requirements.txt
# First setup only; leave an existing .env intact.
cp .env.example .env
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

UNO R4 WiFi handles buttons; UNO Q is the default Django/database host. Future server deployment should change environment configuration, not API paths. Local runtime settings now load from `backend/.env`; see [backend setup](../backend/README.md) for path, host and public-URL configuration. Target/server deployment, application migrations and a Caddyfile remain unimplemented. Run an ASGI server behind Caddy for HTTP/WebSockets; retain one process with the in-memory Channels layer. Do not use `runserver` as the public server or expose the unauthenticated API to the internet.

Conversation Mode remains a separate local-only stretch feature. Raw audio/transcripts stay in memory. Approved scope permits device-local saved suggestion batches and categorical topic segments, not transcript persistence. Do not migrate those tables to a remote server or expose them through public proxy routes. See [data-outline.md](data-outline.md) for the timeline design and unresolved split-deployment boundary.

## WebSocket contract (not an OpenAPI HTTP operation)

`WS /ws/input/` uses a single Channels group, `input`, with messages:

```json
{ "action": "NEXT", "source": "button" }
```

- `action`: `NEXT | SELECT`.
- `source`: `button | touch | voice` (legacy compatibility vocabulary; demo uses buttons).
- Serial input protocol remains plain text at 9600 baud, `NEXT`, `SELECT`, `TOUCH`, `VOICE`; no hardware/protocol change in this task.
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

Runtime tests cover dotenv precedence, paths, invalid configuration, allowed hosts and restricted CORS/preflight. Shared-helper tests cover required/unknown fields, strict strings/UUIDs/integers, offset timestamps/UTC overflow, IANA timezones, bounded query limits, transport size boundaries and safe error envelopes via a test-only view. They do not claim business-route field validation is implemented. Contract tests validate OpenAPI 3.1, every explicit JSON example, refs, unique operation IDs, path parameters, invalid event/review payloads, legacy field shapes, six-phrase constraints, documentation routes, schema export and offline asset discovery. Route tests exercise all 22 business operations with documented example bodies, validate actual 501 envelopes, verify method/CSRF behavior, JSON transport errors and request size limits, and forbid database access. They do not substitute for future feature/persistence tests. Test validators are development dependencies only.

Swagger UI 5.31.0 assets are vendored with Apache-2.0 LICENSE/NOTICE; see [`vendor/README.md`](../backend/aac/static/aac/vendor/swagger-ui/README.md). The UI uses no CDN and disables the online validator/query overrides. On a server with `DEBUG=False`, collect static files and have Caddy serve the collected static directory; this deployment configuration remains future work.

## Next implementation slices

Use [mvp-phase-plan.md](mvp-phase-plan.md) for the detailed sequence, dependencies, core/optional priorities, endpoint ownership, parallel workstreams and acceptance checks. Summary:

1. Profiles, SQLite models/migrations, and validation shared by plain function views.
2. Idempotent event recording and deterministic time-decayed predictions with contract tests.
3. Speech generation/playback integration and existing input relay.
4. Caregiver label creation/assignment/review.
5. Optional bounded AI analysis/Jev integration; Conversation Mode only after the core demo and benchmarks.

For each slice: replace the scaffold with real handlers, add field/query/relationship validation and response/persistence tests, remove that operation's temporary 501 response, and mark it implemented. Swagger execution is already enabled; success must never be advertised until the feature actually works.
