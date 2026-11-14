# MVP implementation plan

## Goal and current state

Deliver this demo on the target hardware:

```text
Caregiver sets up a patient
  → patient scans/selects symbols or suggested phrases with buttons/keyboard
  → patient explicitly activates Speak
  → board plays generated speech
  → completed speech is saved locally
  → exactly six suggestions reflect activity, time, and confirmed history
```

UNO R4 WiFi handles buttons; UNO Q 4GB hosts Django and SQLite. Keyboard fallback is always Space = NEXT, Enter = SELECT. No touchscreen or touch sensor is required.

**Already complete:** OpenAPI 3.1 contracts, offline Swagger UI, and 22 HTTP business-operation scaffolds with transport checks and explicit JSON 501 responses. Phase 1's backend runtime slice now provides `.env` loading, configurable SQLite/media/static paths, public backend URL, local allowed hosts and restricted development CORS, with configuration/preflight tests. Shared transport helpers now expose parsed JSON, and tested value validators cover fields, strings, UUIDs, timestamps/timezones, integers and page limits. Documentation endpoints work. Phase 2's backend is implemented: the six profile operations, `Profile`/`CaregiverPatient` models and migration, and `seed_demo`. Phase 3's backend is implemented: event recording, patient history, legacy `/api/log`, `CommunicationEvent`/`PredictionRecord` and seeded spoken history. Phase 4's deterministic predictions (new and legacy routes) are implemented. The other 11 business operations, frontend, and WebSocket relay are not implemented. Transcription benchmarking is a separate parallel workstream; its presence is not proof of target-device performance.

References:

- [API contracts](api-contracts.md): source/export, statuses and precise HTTP behavior.
- [Data outline](data-outline.md): storage, event correlation and local conversation boundaries.
- [Label vocabulary](label-vocabulary.md): definitions, assignments and review rules.
- `backend/aac/openapi.py`: executable request/response contract source.

This is the single implementation plan for backend, frontend and hardware. It combines the current phase sequence with the compatible implementation guidance from the former backend MVP plan. The old standalone plan has been retired; its DynamoDB, single-persona-only scope and speech-first ordering do not apply.

This document governs implementation sequence, not API definitions. Exact request/response shapes, limits and statuses remain in `backend/aac/openapi.py`, explained by the references above. Resolve discrepancies against those agreed contracts; do not revive older proposals or maintain a second hand-edited schema.

## Architecture and ownership

```text
Frontend -- HTTP --> Django function views --> Django ORM --> SQLite on UNO Q
                              |--> Polly --> local audio files
                              |--> optional bounded Bedrock predictions/analysis
Frontend <-- WS --> Channels input group <-- WS --> serial bridge <-- R4 WiFi
Google Home <-- LAN audio URL + optional Cast command -- backend
```

- **Frontend:** symbols, sentence construction, scanning, keyboard fallback, setup/input settings, explicit Speak, playback and completed-playback event submission. Use readable targets of at least 120px, high contrast and an unmistakable scanning highlight.
- **Backend:** field/relationship validation, profiles, speech generation, event persistence, prediction ranking, caregiver labels and optional casting/AI. No implicit success event inside speech generation.
- **Bridge:** serial-to-WebSocket translation and bounded reconnect behavior.
- **R4 WiFi:** button debounce and the fixed serial protocol. Optional sustained-sound detection is an input switch, not transcription. Do not transfer R4 shield/voltage assumptions to UNO Q GPIO.
- **UNO Q:** default Django/SQLite host. Conversation processing is local-only stretch scope, not part of the input relay.

The single `input` group controls one active board; it is not multi-patient session routing. Run one ASGI process with the in-memory channel layer. Keep synchronous cloud SDK calls out of the WebSocket event loop.

## Dependencies and focused modules

Own small application functions for validation, ranking, fallback, prompts and file handling. Use libraries for protocols, AWS signing and speech/model engines; do not reinvent them.

| Direct runtime dependency | Purpose |
| --- | --- |
| Django | HTTP, ORM/migrations, settings, commands and tests |
| channels | Existing WebSocket group relay |
| daphne | ASGI server; first in `INSTALLED_APPS` for WebSocket-capable `runserver` |
| django-cors-headers | Development CORS for `http://localhost:5173` |
| python-dotenv | Load ignored `backend/.env` without a custom parser |
| boto3 | Polly and Bedrock when those phases are implemented; no DynamoDB |

Pin compatible versions and add dependencies only when used. Keep optional `pychromecast` isolated, for example in `requirements-cast.txt`. Development schema validators/test tooling belong in development requirements.

Use built-ins: `json`, `datetime`/`zoneinfo`, collections, `pathlib`, `uuid`, optional `hashlib`, `logging`, `unittest.mock`, `concurrent.futures` and `time.monotonic`. No DRF, Pydantic, LangChain, Celery, Redis, vector database, cloud-emulation stack, repository framework or autonomous agent framework.

Evolve the existing project rather than recreating it. Keep one `aac` app with focused modules as needed:

```text
backend/
  config/                    # settings, HTTP URLs and ASGI
  aac/
    openapi.py               # existing executable contract source
    models.py                # ORM records introduced by each slice
    migrations/
    views.py                 # thin handlers and small transport/validation helpers
    consumers.py, routing.py # input relay only
    speech.py                # Polly and temporary audio files
    predictions.py           # deterministic ranking, bounded AI and fallback
    history.py               # shared ORM event persistence/query logic, if needed
    casting.py               # optional isolated speaker integration
    management/commands/     # repeatable seeds; audio cleanup when needed
    tests/                   # contract, feature, persistence and relay tests
  seed/                      # synthetic demo fixtures
  media/audio/               # generated files; ignored by git
```

These are modules, not new services or mandatory abstractions. Create files only when a phase needs them. Create cloud clients lazily and reuse them; startup and tests must not require working AWS access.

## Priorities and sequencing

| Phase | Feature | Depends on | Priority |
| --- | --- | --- | --- |
| 0 | Contracts, Swagger, HTTP scaffolds | — | Complete |
| 1 | Runtime configuration, validation, frontend shell | 0 | Core |
| 2 | Profiles and patient setup | 1 | Core; backend done, frontend pending |
| 3 | SQLite event history and retry safety | 2 | Core; backend done |
| 4 | Deterministic predictions | 3 | Core; backend done |
| 5 | Speech and first keyboard-driven demo loop | 2–4 | Core |
| 6 | R4 WiFi buttons and WebSocket relay | 1; integrate with 5 | Core; build in parallel |
| 7 | Fixed/custom labels and caregiver review | 2–3; connect to 4 | Next agreed product workflow |
| 8 | Bounded Bedrock prediction enhancement | 4–5 | Demo AI target; fallback must always work |
| 9 | Analysis, AI label proposals, configuration activation | 7 | After the core loop works |
| 10 | Jev classification/ranking | 7; 9 if using activated configurations | Optional enhancement |
| 11 | UNO Q deployment and end-to-end rehearsal | Core phases; rerun after additions | Mandatory integration gate |
| S1 | Local Conversation Mode | Core rehearsal + successful benchmarks | Stretch |
| S2 | Local topic timeline and saved suggestions | S1 | Stretch |
| S3 | Server/Caddy deployment | Core deployment | Deferred portability work |

**Hackathon rule:** contracts define the destination, not a requirement to finish all 22 features before rehearsing. First reach the core gate (1–6 + 11), then add labels and bounded AI. Analysis/Jev and Conversation Mode must not delay a working communication loop. Reserve at least the final quarter of remaining time for integration and rehearsal; skip optional phases before cutting tests, playback or input reliability.

## Definition of done for every phase

- Implement the assigned feature only, using one Django app, plain function views, Django ORM and focused modules. No DRF, extra database, repository framework, worker queue or autonomous agent framework.
- Add field/query/relationship validation; scaffold JSON parsing alone is insufficient. Preserve the existing error envelope, status codes and legacy request/response shapes.
- Add feature tests with actual response-schema checks. Keep AWS, speakers and boards mocked in automated tests; separately record manual hardware/cloud smoke results.
- Remove that operation's temporary 501 response and mark it `implemented` only after success/error behavior actually works. Keep all unfinished operations explicitly scaffolded. Adjust scaffold-only tests as operations graduate; never make success tests accept 501.
- Update Swagger descriptions/examples, implementation-status documentation and setup instructions in the same change. No undocumented contract changes.
- Run `python manage.py check` and `python manage.py test` with development requirements installed. Test database constraints/migrations with Django TestCase where needed; keep no-database scaffold tests for remaining scaffolds.
- Do not change Codex's `hardware/benchmarks/transcription/` work unless explicitly assigned. Use synthetic demo data and keep databases, generated audio and secrets out of git/logs.

## Phase 1 — Runtime foundation and frontend shell

**Status:** backend runtime configuration and shared transport/value-validation slices implemented; Phase 1 is not yet complete. Setup, variables and validator usage are documented in [backend/README.md](../backend/README.md). Frontend shell and Channels/Daphne/input setup remain pending. Business operations still validate transport only and remain scaffolded; endpoint-specific fields/relationships/cursors are implemented with each feature, not by the shared helpers. No API schema/status changes were introduced by these foundation slices.

**Build:**

- Load backend configuration from ignored `backend/.env`; commit placeholders only in `.env.example`. Configure SQLite/media paths, public backend URL, allowed hosts and development CORS for `http://localhost:5173`.
- Add dependencies only when used. Configure Channels/ASGI and Daphne first in installed apps for the input workstream; use one server process and an in-memory channel layer.
- Refactor transport helpers as needed so real views can read validated data rather than discard it. Implement small shared checks for UUIDs, strings, timestamp offsets, IANA timezones, unknown fields and query limits. Do not create a generic schema framework.
- Start the React/Vite/TypeScript frontend: API/WebSocket base URL configuration, visible loading/error states, symbol/sentence layout and a single keyboard/scanning input path.
- Keep Django bound to local/trusted access. Environment-based portability is enough now; do not add a public server or Caddy deployment in this phase.

**Done when:** a clean setup boots backend and frontend, Swagger still works offline, development cross-origin requests work, malformed requests return safe JSON, and keyboard scanning can operate a small local symbol board without working business endpoints.

## Phase 2 — Profiles and patient setup

**Status:** backend implemented and tested; see [api-contracts.md](api-contracts.md#profile-operations-implemented). Setup survives a restart (manual smoke test on a temporary database). Not yet done end to end: no frontend patient selection, preference loading or patient switching. The "changing active patient clears the sentence…" criterion belongs to that frontend work.

**Operations (6):**

- `POST /api/profile/caregivers`
- `POST /api/profile/patients`
- `GET /api/profile/caregivers/{id}/patients`
- `GET`, `PATCH`, `DELETE /api/profile/patients/{id}`

**Build:** `Profile` and `CaregiverPatient` models/migrations; create caregiver first, then patient/link atomically. Validate roles, preferences, timezone and ownership relationships. Implement bounded patient lists and cursor validation. Frontend selects a patient and loads scan/input preferences.

Use a repeatable seed command for a synthetic caregiver/patient with stable IDs and one fixed configured legacy demo patient. Add only tables this slice needs. Deletion initially covers owned records that exist; extend deletion tests whenever later models are added.

**Done when:** setup survives a restart; patient update works; role/ID mutation and invalid links are rejected; listing is stable; deleting a patient does not delete another patient's records or the caregiver. Changing active patient clears the sentence, transient recent context and pending prediction results.

## Phase 3 — Communication history and retry safety

**Status:** implemented and tested; see [api-contracts.md](api-contracts.md#event-history-implemented). Every "done when" item below is covered by automated tests, and a restart smoke test confirmed history persists. `Event.input_source` became nullable for legacy `/api/log` entries. Frontend event recording (after completed playback) arrives with Phase 5.

**Operations (3):** `POST /api/aac/events`, `GET /api/aac/patients/{id}/events`, `POST /api/log`.

**Build:** `CommunicationEvent` storage, indexes and pagination, plus the minimal `PredictionRecord` model needed for event attribution. Preserve event IDs as retry keys and use utterance IDs to correlate selection, completed speech and feedback. Validate one patient per utterance, explicit kinds/sources, completed-speech uniqueness, prediction ownership/index and exact candidate text. Test attribution with synthetic stored predictions; until Phase 4 generates real records, unknown prediction references return 404, never silent acceptance.

Implement `/api/log` using the fixed demo patient and the same persistence logic, without inventing idempotency guarantees absent from its contract. Add seeded confirmed history and explicit persistence failures; no DynamoDB or dual writes.

**Done when:** identical event retry returns 200 without duplication, new event returns 201, changed retry/conflicting second spoken event returns 409, and intentional repeated speech with new IDs is preserved. UTC timestamps and patient-local time buckets are correct. Cross-patient data is isolated; history survives restart; selection/feedback is not counted as completed speech.

## Phase 4 — Deterministic predictions

**Status:** implemented and tested; see [api-contracts.md](api-contracts.md#predictions-implemented). The "done when" items are covered by automated tests. `/api/aac/predict` gained an additive 503 for a failed prediction-record save. Displaying suggestions in the frontend remains with the frontend lane.

**Operations (2):** `POST /api/aac/predict`, `POST /api/predict`.

**Build:** prediction-record creation using Phase 3's model and patient-scoped ranking in `predictions.py`. First use confirmed spoken history matching activity/time bucket, then broader history, seed data and curated defaults. Weight each occurrence by `0.5 ** (max(0, age_days) / 7)`, counting completed utterances once. Define time-bucket boundaries and stable tie ordering in one place.

Trim and case-insensitively deduplicate; return exactly six nonempty phrases even with no usable history. Save ordinary prediction provenance, not raw prompts/recent buffers. Legacy response remains exactly `{ "phrases": [...] }`; new route includes prediction ID/source/configuration version. No automated prediction expiry during the hackathon.

Integrate Phase 3 attribution checks with actual prediction responses: prediction belongs to patient, index is 0–5 and text exactly matches that candidate; edited/composed phrases omit attribution. Display suggestions in the frontend without selecting them automatically.

**Done when:** empty/sparse/unavailable history still produces six safe defaults; newer confirmed speech outweighs equally frequent older speech; repeated requests rank deterministically; invalid attribution is rejected; no cloud access is necessary for predictions.

## Phase 5 — Speech and the first complete keyboard demo

**Operations (2):** `POST /api/aac/speak`, `POST /api/speak`.

**Build:** Polly neural speech in `speech.py`, temporary MP3 files with server-generated names and absolute playable URLs. Create clients lazily, bound calls and close audio streams. No database audio blobs or credentials in frontend/source/logs.

Confirm the configured child-sounding voice supports Polly neural synthesis in the chosen region. Never derive filenames from submitted text; do not return provider payloads on failure. Serve media locally for development, with a documented target-device serving setup in Phase 11. Keep files long enough for playback; add a small cleanup command when needed, not a worker system. Optional caching by text/voice/engine hash is lower priority than reliable playback and bounded disk usage.

Frontend owns sentence construction, explicit Speak, playback and event submission. Generate one utterance ID for the intended phrase; record `spoken` only when playback completes. Cancellation/failure records no spoken success. Surface network/write errors without blind legacy retries; retain keyboard control and the current sentence.

Optional configured Google Home casting belongs in an isolated helper: when enabled, use LAN-reachable URLs and bounded dispatch, preserve the normal audio response, and avoid duplicate browser/speaker playback via an explicit output-mode choice. An unconfigured speaker never blocks the browser demo. If casting is not ready, leave it disabled; do not advertise support or log completion based only on dispatch.

**Done when:** the patient can use Space/Enter to compose/select, explicitly speak, hear audio, save one completed utterance and receive the next six suggestions. Invalid requests and Polly failures never return fake playable URLs. Failed/cancelled playback creates no spoken event. Speech generation failure leaves sentence/scanning usable.

## Phase 6 — Physical switches and live input relay

**Transport:** `WS /ws/input/`; no new HTTP operation.

**Build in parallel with Phases 2–5:** R4 WiFi sketch for NEXT D2/SELECT D3 buttons, debounce and existing 9600-baud line protocol. Serial bridge translates accepted lines to existing action/source messages and reconnects with bounded retries. Close Arduino Serial Monitor while the bridge owns the port.

Implement Channels group join/leave, message validation and single broadcast without echo loops. Frontend feeds WS actions into the same scanning/selection path as Space/Enter. Validate origins for browser clients while supporting the intended non-browser bridge. Preserve legacy protocol values without requiring absent touch hardware or optional sound hardware.

**Done when:** one socket's valid event reaches another once; malformed messages never broadcast. Real buttons scan/select the same way as keyboard, held/bouncing buttons do not produce unintended rapid selection, and unplugging R4/losing the socket does not break keyboard operation. Test R4 → bridge on UNO Q → Django → frontend, not just laptop simulation.

**Core demo gate:** complete Phases 1–6 and rehearse Phase 11 before adding richer features.

## Phase 7 — Fixed/custom labels and caregiver workflow

**Operations (6):**

- `GET`, `POST /api/learn/patients/{id}/label-definitions`
- `PATCH /api/learn/label-definitions/{id}`
- `GET`, `POST /api/learn/events/{event_id}/labels`
- `PATCH /api/learn/labels/{id}`

**Build:** `LabelDefinition`/`EventLabel` models, idempotent starter seeds and a minimal keyboard-accessible caregiver panel. Support active caregiver-created patient-specific definitions, assignment, corrections, archive and review transitions, without AI dependency. Keep categories fixed; reject duplicate/shadowed codes and cross-patient links. System seeds are read-only.

Implement single effective intent/activity, multi-topic assignments and unknown exclusion. Preserve supersession/provenance and caregiver precedence. Use transactional revision checks. Add vocabulary revision/invalidation handling as derived configurations become available. Only effective labels enter prediction context; no implicit historical backfill.

**Done when:** a caregiver can add a custom label and attach/correct it on a real saved event. Seed reruns are safe, stale edits return 409, archived labels stop influencing current prediction context, and patient deletion covers custom definitions/assignments. Tests exercise AI proposal review using synthetic records even before the provider is implemented; definition approval does not approve assignments.

## Phase 8 — Bounded AI prediction enhancement

**Existing operations:** both prediction routes; no contract expansion.

**Build:** fast Claude Haiku prediction via Bedrock using minimal ordinary time/activity/history context, validated JSON and the same six-phrase rules. Verify model/region/account access before relying on it. Prepare deterministic fallback first; enforce the two-second AI wait deadline with bounded concurrency and retries, not just network timeouts.

Use Bedrock Runtime Converse directly, with a configured model/inference profile and a small output-token limit. Treat all submitted text as data, not instructions. Reject wrong shapes/counts, excessive lengths, blanks and case-insensitive duplicates; never make a second repair call or log raw prompts/responses.

Prepare fallback before waiting. Use a monotonic deadline, disable SDK retries for the latency-sensitive call and set short connect/read timeouts as secondary safeguards. If using futures, use a shared bounded executor with bounded outstanding submissions; a request-scoped executor context manager can wait on exit and defeat the deadline. Timing out a future does not stop its in-flight network call. Return fallback immediately when capacity is exhausted.

**Done when:** real Bedrock can improve ordinary suggestions, while unavailable access, malformed/duplicate output, timeout or saturated capacity returns deterministic suggestions with 200. Automated delayed-call tests prove the response does not wait for eventual upstream completion. New response identifies source `ai` or fallback correctly; legacy response shape stays unchanged. No conversation audio/transcripts/context is sent to Bedrock.

## Phase 9 — Analysis, AI label proposals and activation

**Operations (3):** `POST /api/learn/analyze`, `GET /api/learn/patients/{id}/summary`, `POST /api/learn/activate`.

**Build:** `LearningAnalysis`/`LearningArtifact` models and caregiver-triggered synchronous bounded analysis. Reuse active definitions first; propose at most 10 new definitions and three assignments per event over at most 30 days/latest 1,000 observed events. No queue, 202 response or autonomous agent loop.

Return actual cutoff/count/truncation; store only validated proposals with provenance. Obtain explicit consent before external ordinary-history analysis; use synthetic data for the demo. Exclude Conversation Mode tables/context. Provider choice is optional architecture detail, not a new namespace.

Build versioned application configuration from effective approved labels, never trained Jev weights. Activate transactionally against expected active version/current vocabulary revision; invalidate stale configurations after corrections/archive. Empty history yields empty proposals/null candidate, not invented discoveries.

**Done when:** caregiver requests analysis, reviews definitions and assignments separately, reads summary and activates a valid candidate. Unreviewed labels never enter active configuration. Provider failures return 503 without changing effective labels/active configuration; stale activation returns 409. The patient-facing demo works even while this feature is unavailable.

## Phase 10 — Optional Jev fast decisions

**Existing operations:** prediction/ranking and approved-label classification; no new HTTP endpoint.

**Build only if time permits:** evaluate Jev with supplied candidates or approved vocabulary plus bounded ordinary context. Confirm SDK/service access, latency and confidence interpretation; do not assume automatic training or local inference. If using learned configurations, complete Phase 9 first.

**Done when:** structured output is validated, uncertain/unavailable decisions fall back without blocking AAC, and measured behavior is useful compared with deterministic ranking. No automatic speech/selection and no conversation context leaves UNO Q. High confidence is not automatic approval of permanent AI label assignments. Leave disabled if no measurable demo benefit.

## Phase 11 — Target deployment and rehearsal

**Always run, regardless of optional-phase completion.**

- Install only needed runtime dependencies on UNO Q, apply migrations/seed fixtures, verify writable SQLite/media locations and frontend API/WS configuration. Keep generated files/database outside git.
- Run one Django ASGI process with the in-memory channel layer; verify UI/device connectivity and microphone-free core operation. Collect/serve frontend/static assets as appropriate; offline Swagger assets must remain accessible.
- Verify browser audio/autoplay interaction, optional speaker LAN access, and no doubled playback/logging. Keep a known demo output mode.
- Rehearse setup → scan/select → speak → save → predict → restart → retained history, with actual R4 buttons and keyboard fallback.
- Test unavailable AWS, unavailable history, bridge disconnect, malformed requests, repeated retries, wrong patient references and a failed write. Show clear errors rather than fabricated success; defaults/keyboard remain available where applicable.
- Record the manual setup commands, exact implemented features and remaining scaffolds in README/API docs. Check that no 501 operation is on the rehearsed demo path.

**Demo acceptance:** a teammate can start it from instructions; the patient can communicate without touch hardware; one completed utterance creates one history outcome; six suggestions always remain available; patient switching does not mix data/context; restart retains SQLite data. Optional AI/transcription failure cannot remove the core communication path.

## Stretch phases — explicitly not MVP blockers

### S1: local Conversation Mode

Wait for Codex's actual UNO Q transcription findings; select local engine/settings based on measured memory, sustained throughput, accuracy and application responsiveness. Implement caregiver activation, listening indicator, keyboard/button stop, local microphone capture, bounded in-memory transcript, local topic/reply processing and normal-prediction fallback. Pause/handle board-audio echo. Stop/patient switch releases capture and rejects late results. No raw audio/transcripts/context in cloud calls or persistent logs/storage. Agree the separate session-scoped contract before implementation; never reuse the input broadcast group.

**Gate:** target device sustains the whole local pipeline, not merely file transcription. Raw buffers clear on stop; no autonomous selection/speech. If performance fails, leave this mode disabled rather than silently offloading transcription.

### S2: device-local topic timeline and suggestions

Add `ConversationSession`, `TopicSegment`, `SuggestionBatch` and explicit selection references per the data outline. Reuse approved categorical topic definitions; require two consecutive finalized evaluations for a change and do not treat silence as a switch. Store exactly six generated suggestions separately from communication events; topic observations/unselected suggestions are not patient preferences or positive training evidence. No narrative summaries or transcript evidence.

**Gate:** scripted `food → play → food` creates stable segments, selections link to the right batch/patient and local history stays excluded from hosted AI, public routes and server migrations. Include local records in patient deletion/manual reset.

### S3: server/Caddy portability

Deploy the same ASGI application behind Caddy using configuration, with HTTP/WebSocket/static routing and an explicit single-database migration. Do not add device/server synchronization or network-shared SQLite. Real public/patient use requires authentication/access controls beyond this unauthenticated hackathon scope. If a server hosts ordinary features, keep Conversation Mode computation/history on UNO Q and explicitly design the identity boundary before splitting storage.

## Configuration and operational safety

Use environment configuration, with placeholder-only `.env.example`; the names below are settings to wire in the relevant phase, not claims of implemented configuration:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`.
- SQLite/media paths, static output path and the configured fixed legacy demo patient ID.
- `BACKEND_PUBLIC_BASE_URL` and frontend API/WebSocket base URLs.
- `AWS_REGION`, `POLLY_VOICE_ID`, `BEDROCK_MODEL_ID`; required credentials/session values only in ignored `backend/.env`.
- A legacy demo timezone; namespaced requests use the selected patient's validated timezone/preferences.
- `GOOGLE_HOME_ENABLED`, `GOOGLE_HOME_HOST` only if casting is implemented.

There is no `DYNAMODB_TABLE_NAME` or separate history database. Never put credentials in frontend bundles, fixtures, documentation, responses or logs. Avoid SDK wire-level debug logging and raw sentence/prompt logging. Ignore local databases, generated audio, environments and caches. Use synthetic records and manual demo reset; automated retention/backup infrastructure is deferred.

A configured speaker cannot fetch `localhost` on another device: use an explicitly allowed LAN-reachable backend URL, verify binding/firewall/shared Wi-Fi, and prefer a configured device over discovery per request. Bound Cast operations and preserve browser fallback. CORS, HTTPS and submitted caregiver IDs are not authentication; this demo is trusted-local-access only.

Before rehearsal, confirm the demo timezone/activity, voice/model access, output mode, playback-completion behavior and LAN URLs with the relevant owners. Legacy TOUCH/VOICE mappings matter only if those optional inputs are enabled; do not change their protocol silently. Existing API limits, error shapes and `/api/log` success are already agreed, not open proposals.

## Test and rehearsal checklist

Use `python manage.py test`, Django's client/TestCase, `unittest.mock`, schema validators and Channels test utilities. Mock narrow provider/device boundaries rather than reimplementing AWS. No real cloud, speaker or Arduino is required in automated tests.

As each operation graduates from scaffolding, cover:

- **HTTP:** real success response schema, malformed JSON, missing/unknown fields, wrong types, oversized input, wrong methods and dependency failures; retain agreed error/status behavior.
- **Profiles/storage:** migrations/constraints, atomic links, patient isolation/deletion, timestamp normalization, stable pagination/cursors, simultaneous writes, repeatable seeds and explicit write failures.
- **Events:** identical/changed retries, second-spoken conflicts, intentional repetition, ownership/index/text attribution, and no counting selection/feedback as completed speech.
- **Speech/playback:** safe file names/absolute playable URLs, closed audio streams, no fabricated URL on failure, no spoken event after cancellation/failure or mere Cast dispatch.
- **Predictions:** six unique nonempty phrases, deterministic ties/decay, timezone boundaries, sparse/unavailable history, invalid AI output, delayed upstream calls and saturated worker capacity.
- **WebSocket/input:** two-client single broadcast, invalid/oversized messages, disconnect and no echo loops; keyboard stays usable when hardware disconnects.
- **Labels/analysis:** revisions, review transitions, category limits, caregiver precedence, proposal exclusion, stale activation and provider failure without changing effective state.
- **Optional Cast:** disabled, successful dispatch and unreachable speaker without losing normal speech response/browser fallback.

Run separate manual smoke tests against real Polly, Bedrock and optional Google Home only for features being advertised. Record actual R4 → bridge → UNO Q → browser results and restart/failure-path rehearsal under Phase 11. A mock passing or a scaffold existing is not evidence of a working device/cloud integration.

## Parallel work and handoff rules

- **Backend lane:** 1 → 2 → 3 → 4; integrate speech (5), then labels (7), bounded AI (8), optional 9–10.
- **Frontend lane:** shell/scanning in 1; setup in 2; integrate suggestions/speech/events through 3–5; caregiver labels after 7. Use the agreed schema, not fabricated production behavior.
- **Hardware lane:** build 6 against the fixed serial/WS contract, then integrate on UNO Q. No benchmark work needed for buttons.
- **Benchmark lane:** Codex works only in its assigned transcription benchmark directory; findings inform S1, not core database/API work.
- Every handoff identifies changed operations, examples to run in Swagger, tests/manual checks completed, dependency/config additions and remaining scaffolds. Do not claim a feature is complete because its endpoint exists.

**Next concrete backend task:** Phase 5 Polly speech (`/api/aac/speak`, `/api/speak`); it needs AWS credentials in `backend/.env`. Profile, event-history and prediction backends are implemented; finish the Phase 1 frontend shell, Phase 2 frontend patient setup, and hardware/input setup in parallel. Do not start with AI analysis or Conversation Mode.
