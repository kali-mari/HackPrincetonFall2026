# Data model and API outline

## Status and scope

**Data/API design, not implemented business behavior.** The executable contract definition is `backend/aac/openapi.py`; see [api-contracts.md](api-contracts.md) for Swagger UI, export, validation, and implementation status. This outline describes caregiver/patient profiles, local data storage, AAC prediction, and learning from labeled inputs.

Keep the current `profile` / `aac` / `learn` design. [Label vocabulary and creation workflow](label-vocabulary.md) specifies the agreed labeling direction: fixed starter categories/values, patient-specific caregiver extensions, and AI proposals requiring caregiver approval. The sections below incorporate that refinement without redesigning the system.

The agreed direction supersedes storage/hardware assumptions in the historical [backend MVP plan](backend-mvp-plan.md):

- Preserve existing `/api/speak`, `/api/predict`, `/api/log` request shapes and `/ws/input/` messages. Specify `/api/log` success as `200 { "ok": true }`; its persistence changes to SQLite, not DynamoDB.
- Add the namespaced profile/AAC/learning contracts described below; routes are scaffolded (JSON 501), while feature implementation is still planned.
- UNO R4 WiFi handles physical buttons. UNO Q 4GB hosts Django and the SQLite application database, with local transcription as a benchmark-dependent stretch goal. No touchscreen or touch sensor; keyboard fallback remains required.
- Keep one Django app (`aac`) with plain function views. Namespaces describe responsibilities, not separate services or Django apps.
- Use one relational database plus JSON fields and local files; no object database, object storage service, or dual-write synchronization for the hackathon. The same application may later run on a server behind Caddy via deployment settings; do not share a SQLite file over the network.

## 1. User types and relationships

Use a shared `Profile` record with `role: caregiver | patient`. These are application profiles, not authenticated accounts; no passwords or login system are proposed for the local demo.

| Type | Responsibilities | Stored setup |
| --- | --- | --- |
| Caregiver | Create/manage patient profiles, configure input settings, review history, correct labels, request analysis | Display name, role |
| Patient | Build sentences, select suggestions, request speech, provide explicit feedback | Display name, role, timezone, language, communication/input preferences |

Use a `CaregiverPatient` link so a caregiver can support several patients and a patient can have several caregivers. Require an existing caregiver when creating a patient; create the patient and relationship in one transaction. Initial setup creates the caregiver first, then the patient. Only patient profiles may own communication history or learned artifacts.

Minimum patient preferences: scan interval, enabled input modes, speech voice preference, and default activity. Validate these server-side; the frontend still owns scanning and sentence construction.

**No auth means no enforced role security.** A submitted caregiver ID is context, not proof of identity. Use synthetic demo profiles on a trusted local machine/network only. Authentication and relationship-based authorization are prerequisites for deployment with real patient data.

## 2. API namespaces

Base URL: `http://localhost:8000`. Proposed new routes use no trailing slash, matching existing HTTP contracts. IDs are opaque UUID strings; timestamps are timezone-aware ISO 8601 strings, stored as UTC.

### `/api/profile`: identity and setup

| Method and route | Purpose |
| --- | --- |
| `POST /api/profile/caregivers` | Create caregiver profile; return `201` with profile |
| `POST /api/profile/patients` | Create patient and caregiver link; return `201` with patient |
| `GET /api/profile/caregivers/{id}/patients` | List linked patient profiles |
| `GET /api/profile/patients/{id}` | Fetch patient setup |
| `PATCH /api/profile/patients/{id}` | Update display/setup fields; role and ID are immutable |
| `DELETE /api/profile/patients/{id}` | Delete patient, links, history, labels, prediction records, and derived artifacts; return `204` |

Example patient creation:

```json
{
  "caregiver_id": "<caregiver-uuid>",
  "display_name": "Demo patient",
  "timezone": "America/New_York",
  "language": "en",
  "preferences": {
    "scan_interval_ms": 1500,
    "input_modes": ["button", "keyboard"],
    "default_activity": "play"
  }
}
```

Return the created profile with `id`, `role: "patient"`, submitted setup, `created_at`, and `updated_at`. Patient deletion must also invalidate cached/active learning artifacts. Define caregiver deletion and link-management endpoints later if needed; do not expand the demo just for CRUD completeness.

### `/api/aac`: interactive communication

| Method and route | Purpose and result |
| --- | --- |
| `POST /api/aac/predict` | Patient-scoped suggestions; `200` with exactly six phrases and prediction provenance |
| `POST /api/aac/speak` | Generate speech using `{ "patient_id", "text" }`; `200` with `{ "audio_url" }`; does not record successful playback |
| `POST /api/aac/events` | Explicitly save a selection, confirmed speech, or feedback event; `201` with `{ "event_id" }` |
| `GET /api/aac/patients/{id}/events?limit=50&cursor=...` | Bounded, cursor-paginated history; `200` with `{ "events": [], "next_cursor": null }` |

Prediction request:

```json
{
  "patient_id": "<patient-uuid>",
  "time": "2026-11-14T12:00:00Z",
  "activity": "lunch",
  "recent": ["I want"]
}
```

Prediction response (new route only):

```json
{
  "prediction_id": "<prediction-uuid>",
  "phrases": ["I want water", "More please", "I am hungry", "All done", "Help me", "Thank you"],
  "source": "history",
  "artifact_version": null
}
```

`source` is `jev`, `ai`, `history`, or `default`. Prediction may save a prediction record for later attribution (no automated expiry during the hackathon), but **must not create a communication event or a positive training example** just because a suggestion was displayed. Request `recent` is transient context, not proof a phrase was selected or spoken.

Example explicit event write:

```json
{
  "event_id": "<client-generated-uuid>",
  "utterance_id": "<client-generated-utterance-uuid>",
  "patient_id": "<patient-uuid>",
  "kind": "spoken",
  "text": "I want water",
  "timestamp": "2026-11-14T12:00:04Z",
  "activity": "lunch",
  "input_source": "button",
  "prediction_id": "<prediction-uuid>",
  "candidate_index": 0
}
```

- `kind`: `selection`, `spoken`, or `feedback`; all require nonempty `text`. Feedback also requires `outcome: accepted | rejected`, `prediction_id`, and `candidate_index` (0–5), identifying an actual phrase for that patient/prediction.
- `input_source`: `button` or `keyboard`. No touch input is configured; legacy WebSocket source values remain unchanged for compatibility.
- `prediction_id` and `candidate_index` are optional as a pair for manually composed/edited phrases. When supplied, validate patient ownership, index, and exact phrase match.
- The client generates a new `event_id` for each event. Identical normalized retries return the existing ID with `200`; reuse with different content returns `409`.
- Required `utterance_id` links selection, speech and feedback for one intended utterance. Repeated intentional speech uses a new utterance/event ID. Reject a second distinct spoken event for the same utterance with `409`; count completed utterances once in ranking.
- The frontend records `spoken` only after completed playback. Cancelled/failed playback creates no spoken event; generation or Cast dispatch alone is not completion. Unconfirmed Cast playback must not be labeled as spoken.
- A selection and its later speech are two distinct events, not two spoken outcomes. An unchosen suggestion is not an explicit rejection.

### `/api/learn`: analysis and labeled learning

Choose **`learn`**, rather than `ai`, as the public namespace: it describes the operation independently of whether AI, deterministic rules, or Jev performs it.

| Method and route | Purpose and result |
| --- | --- |
| `POST /api/learn/analyze` | Analyze a bounded patient history window; return `200` with analysis ID, proposed labels, and candidate artifact version |
| `GET /api/learn/patients/{id}/summary` | Read latest analysis status, label counts, active artifact version, and last analyzed event cutoff |
| `PATCH /api/learn/labels/{id}` | Caregiver confirms, corrects, or rejects an event-label assignment; return updated assignment |
| `GET /api/learn/patients/{id}/label-definitions` | List global starter definitions plus that patient's custom definitions; bounded and paginated |
| `POST /api/learn/patients/{id}/label-definitions` | Caregiver creates an active patient-specific definition |
| `PATCH /api/learn/label-definitions/{id}` | Edit/review a custom definition, including approval, rejection, mapping, or archive |
| `POST /api/learn/events/{event_id}/labels` | Caregiver assigns an active definition to a saved event |
| `GET /api/learn/events/{event_id}/labels` | Read assignments and review status for a saved event |
| `POST /api/learn/activate` | Activate a validated candidate for the same patient; return active artifact version |

Example analysis request:

```json
{
  "patient_id": "<patient-uuid>",
  "requested_by": "<caregiver-uuid>",
  "from": "2026-11-07T00:00:00Z",
  "to": "2026-11-14T00:00:00Z"
}
```

For the demo, run analysis synchronously with bounded history size and a configured deadline; no queue/worker infrastructure. Return `503` on provider timeout/unavailability and leave the active artifact unchanged. Do not return `202` unless a real background execution and polling mechanism is implemented. Review does not trigger analysis on every keystroke or prediction request.

Definition creation and event assignment are separate operations; their request shapes, revision checks, status transitions, and limits are specified in [label-vocabulary.md](label-vocabulary.md). Caregiver-created definitions are active immediately. AI-created definitions and assignments start as proposals and require separate caregiver approvals. Ordinary labeling does not require Claude; capture known context directly and reuse the fixed vocabulary.

**Jev integration is not implemented.** Jev is TypeSafe's structured decision model: it evaluates supplied state against typed questions, including choices and scores, rather than generating new label names or phrases. The intended role is classification against approved definitions or ranking supplied phrase candidates. A generative model may optionally propose new definitions during analysis. Confirm the SDK/service, latency, confidence handling, and external-data policy before integration. See [TypeSafe's introduction](https://docs.typesafe.ai/introduction).

A `LearningArtifact` is versioned application configuration/context derived from approved labels and observations, **not trained Jev weights**. Saving labels or calling Jev does not automatically train a patient-specific model.

## 3. Local storage and deployment

Use SQLite and Django ORM for application records on UNO Q. This replaces the original DynamoDB plan; no DynamoDB implementation exists to migrate in the current scaffold. Keep one source of truth, not dual writes. Store preferences/configuration as bounded JSON and generated speech/model files on the local filesystem.

Keep deployment portable through database/media paths, allowed hosts, public backend URL, and frontend API/WebSocket URL settings. These settings and server deployment are not configured by the contract work. A later server can host the same Django ASGI application behind Caddy; choose one database host and migrate explicitly, with PostgreSQL an option only if write concurrency requires it. Start with one ASGI process while Channels uses an in-memory layer. Caddy HTTPS does not supply authentication; do not expose this unauthenticated demo to the public internet. Device-local Conversation Mode history stays on UNO Q, not in a server database migration.

| Record | Minimum fields and relationships |
| --- | --- |
| `Profile` | UUID `id`, `role`, `display_name`, patient-only timezone/language/preferences, created/updated timestamps |
| `CaregiverPatient` | Caregiver FK, patient FK; unique pair; validate both roles |
| `CommunicationEvent` | UUID `id` (API `event_id`, client retry key), `utterance_id`, patient FK, kind, text/outcome, occurred/received timestamps, activity, local time bucket, input source, nullable prediction FK/candidate index |
| `PredictionRecord` | UUID `id`, patient FK, context snapshot (activity/time bucket; no copied rolling transcript), six phrases, source, artifact version, created timestamp |
| `LearningAnalysis` | UUID `id`, patient FK, requested-by caregiver FK, window/cutoff, status, provider/version, created timestamp, safe failure code |
| `LabelDefinition` | UUID `id`, nullable patient FK (null only for global system seeds), fixed category, immutable code, display name/description, origin (`system`, `caregiver`, `ai`), status (`proposed`, `active`, `rejected`, `archived`), analysis/supporting event references, creator/reviewer, revisions, timestamps |
| `EventLabel` | UUID `id`, event FK, definition FK, analysis FK when AI-generated, origin (`context`, `rule`, `ai`, `caregiver`), nullable confidence, status (`proposed`, `confirmed`, `rejected`, `superseded`), reviewer FK, supersession reference, revision, timestamps |
| `LearningArtifact` | UUID `id`, patient FK, analysis FK, version, vocabulary revision, validated application configuration/context payload, status (`candidate`, `active`, `retired`), created timestamp |

Store preference and artifact payloads as bounded JSON, not executable code or pickled provider objects. Seed the fixed `intent`, `topic`, and `activity` vocabulary from [label-vocabulary.md](label-vocabulary.md). Caregivers and AI may add patient-specific values within those categories, not new categories. A definition names a concept; an assignment attaches it to an observed event. Do not retroactively assign a new definition to history automatically.

Effective labels are confirmed assignments referencing active definitions available to that patient. AI definition approval does not approve its assignments. Enforce category cardinality, `unknown` exclusion, and scope/duplicate checks as specified in the label document. Preserve original observations, provenance, and caregiver corrections; AI confidence is optional and provider-specific, not a verified probability. Archive/correction invalidates affected prediction context and derived configurations; stale candidates require revalidation. Patient deletion removes custom definitions and assignments but preserves global seeds.

Indexes: events on `(patient_id, occurred_at, id)`, predictions/analyses on `(patient_id, created_at)`, labels on event/review status, artifacts on patient/version. Enforce unique artifact version per patient and at most one active artifact per patient. Activate artifacts transactionally; failed analysis must not replace a working version.

Store generated speech as temporary files, not database blobs. No raw microphone audio, nearby conversation transcripts, credentials, or diagnosis fields in these records. Existing optional Conversation Mode retains its in-memory-only transcript rule.

## 4. Prediction and learning flow

1. Caregiver creates a patient and sets timezone/input preferences.
2. AAC loads that patient's setup and requests six suggestions.
3. Prepare candidates and context using that patient's observed history and effective labels. If integrated, use Jev with the validated active application configuration to rank supplied candidates; otherwise use the bounded AI prediction path, then patient/time-bucket frequency ranking, then safe defaults. Learning/analysis never blocks interactive prediction.
4. Validate every prediction source: exactly six concise, nonempty, unique phrases. Keep a deterministic fallback ready; AI failure or a wait over two seconds must return fallback. Never automatically select or speak a suggestion.
5. Explicit patient actions create local events. Use the patient's timezone at event time to compute the time bucket; keep UTC timestamps for ordering.
6. Caregiver requests analysis over a bounded window. Reuse existing definitions before proposing new ones; save candidate definitions and assignments for separate caregiver review. Explicit caregiver corrections take precedence.
7. Build/activate only a validated configuration containing effective labels and the current vocabulary revision. Pending proposals remain outside it; approval of one definition does not implicitly approve assignments. If Jev is unavailable or unsupported, keep normal history/default predictions; activation must not claim a Jev integration exists.

For deterministic history ranking, weight each confirmed spoken utterance by `0.5 ** (max(0, age_in_days) / 7)` and sum weights by normalized phrase, first in the matching activity/time bucket. A seven-day half-life is the starting default; fill sparse results with broader history and safe defaults. Selections, displayed suggestions, and passive topic observations are not positive evidence. This changes ranking, not storage expiry.

Keep each patient's events, labels, artifacts, and caches isolated. Use only events at or before the analysis cutoff when generating an artifact; evaluate against later confirmed events rather than treating model-generated suggestions as ground truth. No cross-patient learning or external sharing by default.

## 5. Shared contract rules and compatibility

- Proposed error shape: `{ "error": { "code": "invalid_request", "message": "..." } }`. Use `400` validation, `404` missing profile/record, `405` wrong method, `409` idempotency/version conflict, `503` unavailable dependency. Do not return raw provider errors or sentence bodies in logs.
- Require explicit patient IDs on new patient-scoped endpoints. Never fall back to another patient's data if an ID is invalid.
- Proposed limits: text 500 characters; `recent` at most 20 entries of 500 characters; activity 100 characters; history pages at most 100 events; analysis at most 30 days and the latest 1,000 events in that window. Include the actual cutoff/count and whether results were truncated in analysis output. Validate preferences and IANA timezone names.
- Preserve the exact old `/api/predict` response `{ "phrases": [...] }`; extra metadata belongs only on the proposed namespaced endpoint.
- Existing endpoints have no patient ID. Keep them on a fixed configured demo patient during transition, not a mutable “currently selected” patient. After approval, route them through the same internal functions without changing their request/response shapes. `/api/log` still lacks idempotency; do not promise retry safety there.
- Keep `/ws/input/`, its action/source payload, and the single `input` group unchanged. It controls one local active board, not multi-patient session routing. Multiple simultaneous boards require a separate agreed WebSocket change.

## 6. Future Conversation Mode: live listening

**Planned stretch goal, not implemented live-listening support.** Add local conversation-aware suggestions and a topic timeline only after the core demo works end to end and on-device transcription benchmarks are acceptable. Keep the existing profiles, event history, and label workflow.

Target hardware: UNO R4 WiFi handles physical button inputs; UNO Q 4GB hosts Django, SQLite, and local transcription. Conversation audio, transcripts, inferred topics, and generated reply context must not be sent to hosted transcription, Claude, or Jev services. The local speech-to-text engine, topic detector, reply-generation approach, and API/streaming contracts still require validation. This local-only boundary is separate from existing cloud speech output and ordinary non-conversation predictions.

Intended flow:

```text
Caregiver starts Conversation Mode
  → microphone connected to UNO Q captures nearby conversation
  → local speech-to-text produces a short rolling transcript in memory
  → locally classify topic and detect stable topic transitions
  → locally generate/rank exactly six concise words or replies
  → save the suggestion batch and topic segment in device-local SQLite
  → display suggestions
  → patient explicitly selects; Speak still converts selected text to audio
```

Responsibilities and boundaries:

- Require explicit caregiver activation, a visible listening indicator, and an obvious stop control usable by keyboard/buttons. Obtain OS/device microphone access; browser permission is also needed if capture runs in the browser. Never start listening automatically or treat a saved preference as consent to start capture.
- Use a microphone attached to the UNO Q, not an Arduino sound-threshold sensor. `/api/speak` remains text-to-speech output, not speech recognition. No touch sensor or touchscreen is required.
- Keep raw audio and the bounded rolling transcript in memory only. Never persist raw audio, transcripts, narrative conversation summaries, or quoted supporting evidence in databases, files, logs, or learning artifacts. The narrow persistence exception is generated suggestions and categorical topic history described below, not the source conversation.
- Bind temporary context to the active patient and listening session. On stop, patient switch, disconnect, or expiry, close the session/active topic segment, clear transient buffers, release the microphone, stop local inference, and discard late results. Require explicit reactivation to resume; saved topic/suggestion records remain.
- A topic segment describes nearby discussion, not confirmed patient intent or a permanent `EventLabel` assignment. Reuse approved topic definitions; do not automatically create new permanent label definitions or assignments from live listening.
- Save suggestion batches separately from communication events. Only explicit patient selections/confirmed speech create normal communication events; displayed or unchosen suggestions are not positive learning examples, and absence of selection is not rejection.
- Preserve patient control: never automatically select or speak replies. If transcription/topic detection fails or context expires, keep ordinary time/activity/history predictions available. Do not replace an in-progress sentence when suggestions refresh.
- Pause capture while board speech plays (or implement verified echo handling) so the board's own output is not repeatedly interpreted as nearby conversation.
- Make nearby participants aware of listening and obtain appropriate consent. Saved suggestions and topic codes can still reveal sensitive context even without transcripts. Use synthetic conversations for the hackathon; include local records in patient deletion/manual demo reset.

### Stretch: topic timeline and saved suggestions

Minimal future records, stored only on the UNO Q:

| Record | Fields |
| --- | --- |
| `ConversationSession` | UUID, patient FK, started/ended timestamps, end reason |
| `TopicSegment` | UUID, session FK, approved `topic` definition FK (including `unknown`), started/ended timestamps, detector version, optional confidence |
| `SuggestionBatch` | UUID, segment FK, exactly six phrases in stable order, generated timestamp, local generator/ranker version |

An explicit communication event may reference a batch UUID and candidate index (0–5). Validate patient/session ownership, index bounds, and text match. A composed or edited response remains a normal event without falsely attributing it to an unchanged candidate. Keep these links optional so ordinary AAC still works without Conversation Mode.

Example timeline:

```text
12:00–12:03  food
  Batch: ["I am hungry", "More please", ...]  (six suggestions)
  Patient selected: "More please"
12:03–12:05  play
  Batch: ["Can we play?", "My turn", ...]     (six suggestions)
  Patient selected: "My turn"
```

Start with a simple stability rule: open a different topic segment only after two consecutive finalized speech-window evaluations identify the same new topic. Until then, retain the current segment. Use `unknown` when a spoken window cannot be classified; sustained uncertainty follows the same two-evaluation rule. Silence is not a topic transition. This is a tunable heuristic, not a claim of detector accuracy. Segment boundaries mark when a switch is confirmed, not the exact moment the real conversation changed. End the active segment when the session ends; use sequence/timestamps to reject stale evaluations.

Persist only the categorical topic reference, timing, and detector metadata—not a free-text explanation of what people discussed. A return to an earlier topic opens a new segment. Keep topic history separate from patient preference scoring; observing a topic or displaying a phrase does not establish a patient preference. No speaker identification, narrative summaries, or autonomous label creation is needed.

Device-local records must be excluded from server migration, cloud synchronization, hosted AI context, and public Caddy routes. If ordinary Django moves to a server, keep the conversation component and its storage on the UNO Q; resolve that split explicitly rather than uploading local conversation tables with a whole-database migration. Foreign-key relationships above describe the default single-device deployment; a future split requires explicit identity/link handling.

These are documentation proposals, not migrations or new endpoints. A future contract must cover start/stop, patient/session isolation, bounded context duration/size, partial/final transcript handling, stale-result rejection, local history access, and cleanup. Choose a separate session-scoped transport if streaming is needed; **do not repurpose `/ws/input/` or broadcast transcripts to its shared `input` group**. Existing request/response shapes remain unchanged.

Acceptance before enabling the stretch feature:

- Verify local transcription plus topic/reply processing under actual UNO Q application load; do not assume transcription benchmarks prove the entire pipeline works.
- A scripted `food → play → food` conversation creates separate segments, while a single ambiguous window or silence does not cause topic flicker.
- Each saved batch contains exactly six replies; unselected replies do not become communication events or training positives.
- Stop/patient switch closes the current session and discards late results without mixing patients.
- No raw audio/transcripts are persisted, no conversation context is sent to hosted services, and local history is excluded from public routes/server migration.
- Failure leaves ordinary predictions, keyboard/buttons, and explicit Speak controls usable.

## 7. Privacy, retention, and open decisions

Communication history can reveal sensitive needs. Minimize identifying fields, avoid raw prompt/event logging, exclude the SQLite file and generated audio from git, and provide patient deletion before using real data. SQLite does not provide access control or encryption by itself.

Before business-handler implementation, review:

1. The concrete namespaced contracts in Swagger/OpenAPI with the frontend/backend team; all business routes are wired as explicit 501 scaffolds; business features remain planned.
2. Deployment settings for the chosen SQLite-on-UNO-Q architecture; preserve the server migration boundary and do not add database synchronization.
3. Jev's exact SDK/service and whether any patient-derived data leaves the machine. External AI analysis requires explicit caregiver consent and minimal payloads; deleting local data cannot guarantee provider-side deletion.
4. Implement the labeling direction in [label-vocabulary.md](label-vocabulary.md): fixed categories/starter values, caregiver extensions, separate AI proposal review, and artifact validation. Finalize UI details and acceptable fast-decision behavior.
5. Use synthetic data, ignored databases/audio, and manual demo reset. Automated retention, prediction expiry, and backup/deletion infrastructure are deferred beyond the hackathon; define them before real patient data.
6. Confirm how browser/Cast playback completion is reported. Cancelled/failed/unconfirmed playback must not create a spoken event. The chosen namespace is `learn`.
7. When Conversation Mode is prioritized: validate local transcription/topic/reply processing on UNO Q, participant consent, session-scoped transport, memory bounds, and device-local history access. Topic timeline/saved suggestions remain stretch scope, not required for the core demo.

Implementation order after agreement: profiles and local event writes → deterministic patient-scoped predictions → feedback/labels → bounded analysis → optional Jev integration. This is a data/API outline, not authorization to expand the core demo before it works end to end.
