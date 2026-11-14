# Data model and API outline

## Status and scope

**Proposal for team review, not implemented API behavior.** This document describes caregiver/patient profiles, local data storage, AAC prediction, and learning from labeled inputs.

The current shared contracts in `AGENTS.md` and the demo plan in `backend-mvp-plan.md` remain authoritative until the team agrees to changes. In particular:

- Existing `/api/speak`, `/api/predict`, `/api/log`, and `/ws/input/` contracts stay unchanged.
- Multiple profiles and learning endpoints extend the original single-persona demo scope.
- Using SQLite for application data changes the current rule that SQLite is for Django internals and phrase history lives in DynamoDB. The local-first design below is a proposal requiring team approval, not an instruction to silently replace DynamoDB.
- Keep one Django app (`aac`) with plain function views. Namespaces describe responsibilities, not separate services or Django apps.

## 1. User types and relationships

Use a shared `Profile` record with `role: caregiver | patient`. These are application profiles, not authenticated accounts; no passwords or login system are proposed for the local demo.

| Type | Responsibilities | Stored setup |
| --- | --- | --- |
| Caregiver | Create/manage patient profiles, configure input settings, review history, correct labels, request analysis | Display name, role |
| Patient | Build sentences, select suggestions, request speech, provide explicit feedback | Display name, role, timezone, language, communication/input preferences |

Use a `CaregiverPatient` link so a caregiver can support several patients and a patient can have several caregivers. Require at least one caregiver link when creating a patient; create both records/link in one transaction when setting up the first pair. Only patient profiles may own communication history or learned artifacts.

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
    "input_modes": ["button", "touch"],
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

`source` is `jev`, `ai`, `history`, or `default`. Prediction may save a short-lived prediction record for later attribution, but **must not create a communication event or a positive training example** just because a suggestion was displayed. Request `recent` is transient context, not proof a phrase was selected or spoken.

Example explicit event write:

```json
{
  "event_id": "<client-generated-uuid>",
  "patient_id": "<patient-uuid>",
  "kind": "spoken",
  "text": "I want water",
  "timestamp": "2026-11-14T12:00:04Z",
  "activity": "lunch",
  "input_source": "button",
  "prediction_id": "<prediction-uuid>"
}
```

- `kind`: `selection`, `spoken`, or `feedback`. Selection/spoken require nonempty `text`; feedback requires `outcome: accepted | rejected`. Feedback and prediction-linked selections must reference a phrase actually returned for that patient/prediction.
- `input_source`: `button`, `touch`, `voice`, or `keyboard`. Here `voice` is a switch source, not a transcript.
- `prediction_id` is optional for manually composed phrases. When present, validate that it belongs to the same patient.
- The client generates a new `event_id` for each intentional event. Identical retries return the existing ID with `200`; reuse with different content returns `409`. Intentional repeated speech uses a new ID.
- The frontend records `spoken` only after confirmed playback. Speech generation or Cast dispatch alone is not proof of playback. Unconfirmed Cast playback must not be labeled as spoken.
- Recording a selection and then speech creates two distinct events; learning must not double-count them as two spoken outcomes. An unchosen suggestion is not an explicit rejection.

### `/api/learn`: analysis and labeled learning

Choose **`learn`**, rather than `ai`, as the public namespace: it describes the operation independently of whether AI, deterministic rules, or Jev performs it.

| Method and route | Purpose and result |
| --- | --- |
| `POST /api/learn/analyze` | Analyze a bounded patient history window; return `200` with analysis ID, proposed labels, and candidate artifact version |
| `GET /api/learn/patients/{id}/summary` | Read latest analysis status, label counts, active artifact version, and last analyzed event cutoff |
| `PATCH /api/learn/labels/{id}` | Caregiver confirms, edits, or rejects a proposed label; return updated label |
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

**Jev is an integration placeholder:** confirm its product/library, supported inputs, output shape, local versus hosted execution, and confidence semantics before implementation. This proposal assumes only the intended role: fast decisions using prior inputs and labels. It does not assume Jev trains a model, supports online learning, or has any particular API.

## 3. Proposed local storage

After approval, use the existing Django SQLite database and ORM for application records. Keep a single local source of truth; do not introduce silent SQLite/DynamoDB dual writes or synchronization. Existing DynamoDB history needs an explicit migration/cutover decision before this replaces the current plan.

| Record | Minimum fields and relationships |
| --- | --- |
| `Profile` | UUID `id`, `role`, `display_name`, patient-only timezone/language/preferences, created/updated timestamps |
| `CaregiverPatient` | Caregiver FK, patient FK; unique pair; validate both roles |
| `CommunicationEvent` | UUID `id` (client idempotency key), patient FK, kind, text/outcome, occurred/received timestamps, activity, local time bucket, input source, nullable prediction FK |
| `PredictionRecord` | UUID `id`, patient FK, context snapshot (activity/time bucket; no copied rolling transcript), six phrases, source, artifact version, created timestamp |
| `LearningAnalysis` | UUID `id`, patient FK, requested-by caregiver FK, window/cutoff, status, provider/version, created timestamp, safe failure code |
| `EventLabel` | UUID `id`, event FK, analysis FK when AI-generated, label type/value, origin (`rule`, `ai`, `caregiver`), nullable confidence, review status, reviewer FK, timestamps |
| `LearningArtifact` | UUID `id`, patient FK, analysis FK, version, validated rule/label payload, status (`candidate`, `active`, `retired`), created timestamp |

Store preference and artifact payloads as bounded JSON, not executable code or pickled provider objects. Start with a short controlled label vocabulary, e.g. `intent=request`, `topic=drink`, `activity=lunch`; validate allowable type/value combinations. Keep original observations separate from inferred labels. AI confidence is optional and provider-specific, not a verified probability.

Indexes: events on `(patient_id, occurred_at, id)`, predictions/analyses on `(patient_id, created_at)`, labels on event/review status, artifacts on patient/version. Enforce unique artifact version per patient and at most one active artifact per patient. Activate artifacts transactionally; failed analysis must not replace a working version.

Store generated speech as temporary files, not database blobs. No raw microphone audio, nearby conversation transcripts, credentials, or diagnosis fields in these records. Existing optional Conversation Mode retains its in-memory-only transcript rule.

## 4. Prediction and learning flow

1. Caregiver creates a patient and sets timezone/input preferences.
2. AAC loads that patient's setup and requests six suggestions.
3. Try the patient's validated active Jev artifact if available and supported; otherwise use the existing bounded AI prediction path, then patient/time-bucket frequency ranking, then safe defaults. Learning/analysis never blocks interactive prediction.
4. Validate every prediction source: exactly six concise, nonempty, unique phrases. Keep a deterministic fallback ready; AI failure or a wait over two seconds must return fallback. Never automatically select or speak a suggestion.
5. Explicit patient actions create local events. Use the patient's timezone at event time to compute the time bucket; keep UTC timestamps for ordering.
6. Caregiver requests analysis over a bounded window. Create candidate labels and artifact; AI labels remain proposed until reviewed, and explicit caregiver corrections take precedence.
7. Activate only a validated candidate with no unreviewed AI labels. If Jev is unavailable or unsupported, keep normal history/default predictions; activation must not claim a Jev integration exists.

Keep each patient's events, labels, artifacts, and caches isolated. Use only events at or before the analysis cutoff when generating an artifact; evaluate against later confirmed events rather than treating model-generated suggestions as ground truth. No cross-patient learning or external sharing by default.

## 5. Shared contract rules and compatibility

- Proposed error shape: `{ "error": { "code": "invalid_request", "message": "..." } }`. Use `400` validation, `404` missing profile/record, `405` wrong method, `409` idempotency/version conflict, `503` unavailable dependency. Do not return raw provider errors or sentence bodies in logs.
- Require explicit patient IDs on new patient-scoped endpoints. Never fall back to another patient's data if an ID is invalid.
- Proposed limits: text 500 characters; `recent` at most 20 entries of 500 characters; activity 100 characters; history pages at most 100 events; analysis at most 30 days and the latest 1,000 events in that window. Include the actual cutoff/count and whether results were truncated in analysis output. Validate preferences and IANA timezone names.
- Preserve the exact old `/api/predict` response `{ "phrases": [...] }`; extra metadata belongs only on the proposed namespaced endpoint.
- Existing endpoints have no patient ID. Keep them on a fixed configured demo patient during transition, not a mutable “currently selected” patient. After approval, route them through the same internal functions without changing their request/response shapes. `/api/log` still lacks idempotency; do not promise retry safety there.
- Keep `/ws/input/`, its action/source payload, and the single `input` group unchanged. It controls one local active board, not multi-patient session routing. Multiple simultaneous boards require a separate agreed WebSocket change.

## 6. Privacy, retention, and open decisions

Communication history can reveal sensitive needs. Minimize identifying fields, avoid raw prompt/event logging, exclude the SQLite file and generated audio from git, and provide patient deletion before using real data. SQLite does not provide access control or encryption by itself.

Before implementation, agree on:

1. Approval of profile/learning scope and namespaced contracts with the frontend/backend team.
2. SQLite replacing DynamoDB versus retaining the existing demo persistence; migration and rollback ownership. Do not silently mix both designs.
3. Jev's exact SDK/service and whether any patient-derived data leaves the machine. External AI analysis requires explicit caregiver consent and minimal payloads; deleting local data cannot guarantee provider-side deletion.
4. Label vocabulary, caregiver review UI, artifact validation, and acceptable fast-decision behavior.
5. Finite event/prediction/artifact retention periods, backup/deletion policy, and cleanup of artifacts derived from deleted data. Until agreed, use synthetic data only.
6. How browser/Cast playback completion is reported, and whether the proposed `learn` namespace is accepted.

Implementation order after agreement: profiles and local event writes → deterministic patient-scoped predictions → feedback/labels → bounded analysis → optional Jev integration. This is a data/API outline, not authorization to expand the core demo before it works end to end.
