# MVP implementation phase plan

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

**Already complete:** OpenAPI 3.1 contracts, offline Swagger UI, and 22 HTTP business-operation scaffolds with transport checks and explicit JSON 501 responses. Documentation endpoints work. Business features, models/migrations, frontend, and WebSocket relay are not implemented. Transcription benchmarking is a separate parallel workstream; its presence is not proof of target-device performance.

References:

- [API contracts](api-contracts.md): source/export, statuses and precise HTTP behavior.
- [Data outline](data-outline.md): storage, event correlation and local conversation boundaries.
- [Label vocabulary](label-vocabulary.md): definitions, assignments and review rules.
- `backend/aac/openapi.py`: executable request/response contract source.

This is the implementation sequence going forward. It supersedes the ordering in the historical [backend MVP plan](backend-mvp-plan.md), not the agreed API contracts.

## Priorities and sequencing

| Phase | Feature | Depends on | Priority |
| --- | --- | --- | --- |
| 0 | Contracts, Swagger, HTTP scaffolds | — | Complete |
| 1 | Runtime configuration, validation, frontend shell | 0 | Core |
| 2 | Profiles and patient setup | 1 | Core |
| 3 | SQLite event history and retry safety | 2 | Core |
| 4 | Deterministic predictions | 3 | Core |
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

**Build:**

- Load backend configuration from ignored `backend/.env`; commit placeholders only in `.env.example`. Configure SQLite/media paths, public backend URL, allowed hosts and development CORS for `http://localhost:5173`.
- Add dependencies only when used. Configure Channels/ASGI and Daphne first in installed apps for the input workstream; use one server process and an in-memory channel layer.
- Refactor transport helpers as needed so real views can read validated data rather than discard it. Implement small shared checks for UUIDs, strings, timestamp offsets, IANA timezones, unknown fields and query limits. Do not create a generic schema framework.
- Start the React/Vite/TypeScript frontend: API/WebSocket base URL configuration, visible loading/error states, symbol/sentence layout and a single keyboard/scanning input path.
- Keep Django bound to local/trusted access. Environment-based portability is enough now; do not add a public server or Caddy deployment in this phase.

**Done when:** a clean setup boots backend and frontend, Swagger still works offline, development cross-origin requests work, malformed requests return safe JSON, and keyboard scanning can operate a small local symbol board without working business endpoints.

## Phase 2 — Profiles and patient setup

**Operations (6):**

- `POST /api/profile/caregivers`
- `POST /api/profile/patients`
- `GET /api/profile/caregivers/{id}/patients`
- `GET`, `PATCH`, `DELETE /api/profile/patients/{id}`

**Build:** `Profile` and `CaregiverPatient` models/migrations; create caregiver first, then patient/link atomically. Validate roles, preferences, timezone and ownership relationships. Implement bounded patient lists and cursor validation. Frontend selects a patient and loads scan/input preferences.

Use a repeatable seed command for a synthetic caregiver/patient with stable IDs and one fixed configured legacy demo patient. Add only tables this slice needs. Deletion initially covers owned records that exist; extend deletion tests whenever later models are added.

**Done when:** setup survives a restart; patient update works; role/ID mutation and invalid links are rejected; listing is stable; deleting a patient does not delete another patient's records or the caregiver. Changing active patient clears the sentence, transient recent context and pending prediction results.

## Phase 3 — Communication history and retry safety

**Operations (3):** `POST /api/aac/events`, `GET /api/aac/patients/{id}/events`, `POST /api/log`.

**Build:** `CommunicationEvent` storage, indexes and pagination, plus the minimal `PredictionRecord` model needed for event attribution. Preserve event IDs as retry keys and use utterance IDs to correlate selection, completed speech and feedback. Validate one patient per utterance, explicit kinds/sources, completed-speech uniqueness, prediction ownership/index and exact candidate text. Test attribution with synthetic stored predictions; until Phase 4 generates real records, unknown prediction references return 404, never silent acceptance.

Implement `/api/log` using the fixed demo patient and the same persistence logic, without inventing idempotency guarantees absent from its contract. Add seeded confirmed history and explicit persistence failures; no DynamoDB or dual writes.

**Done when:** identical event retry returns 200 without duplication, new event returns 201, changed retry/conflicting second spoken event returns 409, and intentional repeated speech with new IDs is preserved. UTC timestamps and patient-local time buckets are correct. Cross-patient data is isolated; history survives restart; selection/feedback is not counted as completed speech.

## Phase 4 — Deterministic predictions

**Operations (2):** `POST /api/aac/predict`, `POST /api/predict`.

**Build:** prediction-record creation using Phase 3's model and patient-scoped ranking in `predictions.py`. First use confirmed spoken history matching activity/time bucket, then broader history, seed data and curated defaults. Weight each occurrence by `0.5 ** (max(0, age_days) / 7)`, counting completed utterances once. Define time-bucket boundaries and stable tie ordering in one place.

Trim and case-insensitively deduplicate; return exactly six nonempty phrases even with no usable history. Save ordinary prediction provenance, not raw prompts/recent buffers. Legacy response remains exactly `{ "phrases": [...] }`; new route includes prediction ID/source/configuration version. No automated prediction expiry during the hackathon.

Integrate Phase 3 attribution checks with actual prediction responses: prediction belongs to patient, index is 0–5 and text exactly matches that candidate; edited/composed phrases omit attribution. Display suggestions in the frontend without selecting them automatically.

**Done when:** empty/sparse/unavailable history still produces six safe defaults; newer confirmed speech outweighs equally frequent older speech; repeated requests rank deterministically; invalid attribution is rejected; no cloud access is necessary for predictions.

## Phase 5 — Speech and the first complete keyboard demo

**Operations (2):** `POST /api/aac/speak`, `POST /api/speak`.

**Build:** Polly neural speech in `speech.py`, temporary MP3 files with server-generated names and absolute playable URLs. Create clients lazily, bound calls and close audio streams. No database audio blobs or credentials in frontend/source/logs.

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

## Parallel work and handoff rules

- **Backend lane:** 1 → 2 → 3 → 4; integrate speech (5), then labels (7), bounded AI (8), optional 9–10.
- **Frontend lane:** shell/scanning in 1; setup in 2; integrate suggestions/speech/events through 3–5; caregiver labels after 7. Use the agreed schema, not fabricated production behavior.
- **Hardware lane:** build 6 against the fixed serial/WS contract, then integrate on UNO Q. No benchmark work needed for buttons.
- **Benchmark lane:** Codex works only in its assigned transcription benchmark directory; findings inform S1, not core database/API work.
- Every handoff identifies changed operations, examples to run in Swagger, tests/manual checks completed, dependency/config additions and remaining scaffolds. Do not claim a feature is complete because its endpoint exists.

**Next concrete task:** Phase 1, followed by Phase 2 profiles/SQLite migrations. Start hardware and frontend shell work in parallel; do not start with AI analysis or Conversation Mode.
