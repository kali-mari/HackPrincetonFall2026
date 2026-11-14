# Label vocabulary and creation workflow

## Status and decisions

Design specification extending [data-outline.md](data-outline.md); label HTTP routes are scaffolded with JSON 501, while label features/models are not implemented yet. Concrete request/response contracts are in `backend/aac/openapi.py`, served by Swagger at `/api/docs`; see [api-contracts.md](api-contracts.md). SQLite on UNO Q is the chosen application store. Existing legacy request shapes and WebSocket messages remain compatible.

Agreed direction:

- Ship a fixed starter vocabulary so labeling works without an AI call.
- Let caregivers create patient-specific labels and assign labels to events.
- Let an AI agent propose new labels and event assignments, subject to caregiver approval before use in predictions.
- Keep label categories fixed initially; custom labels add values within those categories, not new categories.
- Do not require Claude for ordinary labeling. A generative model may propose new labels; Jev can classify against existing approved choices.

## 1. Starter vocabulary

Seed these global definitions with stable IDs/codes. System definitions are read-only in the caregiver UI; applications may add future seed values without renaming existing codes.

| Category | Starter values | Assignment limit per event |
| --- | --- | --- |
| `intent` | `request`, `refusal`, `greeting`, `feeling`, `question`, `response`, `unknown` | One effective value |
| `topic` | `food`, `drink`, `play`, `comfort`, `people`, `hygiene`, `movement`, `unknown` | Multiple distinct values |
| `activity` | `meal`, `lunch`, `school`, `play`, `bedtime`, `unknown` | One effective value |

Definitions need a short description to distinguish similar values. For example, `activity=meal` means a meal whose specific type is unspecified; `activity=lunch` means explicitly known lunch context. `intent=feeling` means expressing an emotional or physical state, not a diagnosis.

`unknown` is category-specific. Do not pair it with a known value in the same category. Missing assignment means “not labeled yet”; `unknown` means “evaluated, but could not determine.” Do not force every event into every category.

Example:

```text
Event: "I want water", activity explicitly set to lunch
intent=request
topic=drink
activity=lunch
```

Known activity comes directly from explicit context, not an AI guess. No microphone transcription is required.

## 2. Definitions versus assignments

**Label definition:** a reusable concept, such as `topic=quiet_space`, with a description explaining what it means.

**Label assignment:** attaching that definition to an observed event, such as labeling “I need somewhere quiet” with `topic=quiet_space`.

Creating a definition does not retroactively label history. Approving a definition does not approve every AI-proposed assignment that references it. The caregiver reviews each separately; batch approval can be added later with an explicit event list.

Custom definitions are patient-scoped. Two patients may have different definitions with the same code; neither patient receives the other's labels or history. Global starter definitions are shared vocabulary only, not shared patient data.

## 3. Caregiver workflow

1. Open the selected patient's **Labels** settings and browse starter/custom definitions.
2. Choose **Add label**, select a category, enter a display name and a short description/example.
3. The backend normalizes a stable code, checks duplicates, and creates an `active` definition with `origin=caregiver`.
4. Open a saved event and assign an active label, correct an existing assignment, or mark it `unknown`.
5. Save a confirmed caregiver assignment. A correction supersedes the previous effective assignment where the category is single-valued.

Caregiver-created definitions are active immediately because the caregiver is explicitly approving them. Custom display names and descriptions can be edited, but IDs, scope, category, and codes are immutable. A materially different meaning requires a new definition; do not silently reinterpret old assignments.

Archive a custom definition to stop future assignment/prediction use while preserving history. Starter definitions cannot be archived through this workflow. Archive does not delete its historical assignments.

## 4. AI agent workflow

1. Caregiver explicitly requests bounded analysis of that patient's saved events.
2. The agent receives the existing active vocabulary and only the minimal relevant event/context data.
3. It first reuses existing definitions. If a meaningful concept is missing, it may propose a new value under one of the fixed categories.
4. The backend validates the structured output and saves a `proposed` definition with description, short rationale, analysis ID, and supporting event IDs. Do not store chain-of-thought.
5. The caregiver accepts it, edits and accepts it, rejects it, or maps it to an existing definition.
6. Only an accepted definition becomes `active`. Associated proposed event assignments still require separate review.

Agent-origin assignments always start as `proposed`, even when they reference an already active definition. AI must not override caregiver corrections or reactivate rejected definitions automatically. Limit each analysis to at most 10 new definition proposals; deduplicate against active, proposed, rejected, and archived definitions before creating more.

The provider is not fixed here. Claude is an optional generator of new names/descriptions; Jev's Choice primitive selects among supplied options rather than inventing open-ended label names. Calling either provider does not automatically train a personalized model.

## 5. Storage model

This refines the `EventLabel` concept in the data outline by separating reusable definitions from assignments. Definitions and assignments use the same SQLite database on UNO Q; DynamoDB is no longer planned.

| Record | Minimum fields |
| --- | --- |
| `LabelDefinition` | UUID `id`, nullable patient FK (null only for system seeds), category, immutable code, display name, description, origin (`system`, `caregiver`, `ai`), status (`proposed`, `active`, `rejected`, `archived`), creator/reviewer caregiver FK where applicable, analysis FK for AI proposals, supporting event references, record revision, vocabulary revision, created/updated timestamps |
| `EventLabel` | UUID `id`, event FK, definition FK, origin (`context`, `rule`, `caregiver`, `ai`), status (`proposed`, `confirmed`, `rejected`, `superseded`), optional confidence, analysis/provider version where applicable, reviewer FK, superseded-assignment reference, record revision, created/updated timestamps |

Validation and invariants:

- Code: lowercase snake case, at most 50 characters; display name: 80 characters; description: 300 characters. Preserve readable Unicode display names.
- Enforce uniqueness of `(scope, category, code)`, including global seed scope explicitly; nullable patient IDs must not permit duplicate global codes. Prevent patient definitions from shadowing global codes. Check normalized names for likely duplicates, but do not automatically merge semantic near-matches.
- Patient references, analysis IDs, supporting events, and assignment events must belong to the same patient. Only system seeds may have global scope.
- Confirm assignments only against active definitions available to that patient. For AI assignments, both definition approval and assignment approval must pass.
- Transactionally enforce single effective `intent`/`activity`, unique effective topic assignments, and the `unknown` exclusion rule.
- Keep provenance/review history. Provider confidence is optional and not proof of correctness.
- Explicit caregiver corrections take precedence over inferred labels. Never replace them during reanalysis; present conflicting inferences as review suggestions.
- Explicit activity context and deterministic mappings to known symbols may produce confirmed non-AI assignments. Rule inferences beyond those known mappings stay proposed until reviewed.

Effective labels are confirmed assignments whose definitions are active. On archive, correction, or rejection, invalidate affected cached prediction context and derived artifacts. Increment the patient's effective vocabulary revision for relevant active-definition changes and record the revision used by each derived configuration. Candidate configurations based on an old revision require revalidation before activation.

Deletion of a patient deletes custom definitions, assignments, proposals, supporting references, and derived artifacts; global seeds remain. For the synthetic-data hackathon, use manual reset; automated retention/backup cleanup is deferred until before real patient use.

## 6. Proposed API additions

Use `/api/learn` for definitions and assignments. The existing proposed `PATCH /api/learn/labels/{id}` continues to mean **event assignment review**, not definition editing.

| Method and route | Contract |
| --- | --- |
| `GET /api/learn/patients/{id}/label-definitions?status=active&limit=50&cursor=...` | `200` with `{ "definitions": [], "next_cursor": null }`; include system definitions and only this patient's custom definitions |
| `POST /api/learn/patients/{id}/label-definitions` | Caregiver creation; body `{ "caregiver_id", "category", "display_name", "description" }`; `201` with active definition and server-normalized code |
| `PATCH /api/learn/label-definitions/{id}` | Body includes `caregiver_id`, expected `revision`, and an action (`edit`, `approve`, `reject`, `archive`, `map_existing`); `edit` requires a display name or description change; `200` with resulting definition and optional canonical definition ID |
| `POST /api/learn/events/{event_id}/labels` | Body `{ "caregiver_id", "definition_id" }`; `201` with confirmed assignment; identical existing effective assignment returns `200` |
| `GET /api/learn/events/{event_id}/labels` | `200` with `{ "labels": [] }`, including assignment status and definition metadata for review |
| `PATCH /api/learn/labels/{id}` | Body includes `caregiver_id`, expected `revision`, and review action (`confirm`, `reject`, `correct`); `correct` also requires replacement `definition_id` and returns the new confirmed assignment after superseding the old one; `200` with result |
| `POST /api/learn/analyze` | Existing proposed route; adds bounded definition/assignment proposals to its analysis result, not a second analysis endpoint |

Every mutable definition/assignment response includes its `revision`; stale review/edit requests return `409`. Validate allowed status transitions: proposed definitions may be approved, rejected, or mapped; active custom definitions may be archived. Invalid transitions return `409`. Mapping requires a different active definition in the same category and allowed scope; mark the proposal rejected with its canonical reference and retarget pending assignments for separate review, without auto-confirming them.

The AI agent uses a backend-owned analysis function to persist validated proposals. It does **not** call the caregiver creation route, set `origin=caregiver`, approve its own work, or receive unrestricted database tools. The backend determines origin/status; clients cannot override them.

List endpoints are bounded (maximum page size 100). Invalid input returns `400`, absent/inaccessible records `404`, duplicates or stale revisions `409`, and unavailable analysis providers `503`, using the error shape in the data outline. Validate linked caregiver/patient profiles; without authentication, submitted caregiver IDs still provide attribution only, not secure authorization. Real patient use requires authentication and relationship checks; the unauthenticated demo uses synthetic data.

## 7. Prediction behavior and safety

- Retrieve only this patient's effective labels and relevant observed history. Proposed/rejected labels never enter prediction context.
- Jev may classify against the approved vocabulary or rank supplied phrase candidates. Our application prepares context and candidates; Jev is not the label database or an automatically trained local model.
- A stored learning “artifact” means versioned application configuration/context, not Jev model weights. Archiving a label must remove it from active use even if an older artifact contains it.
- AI analysis is separate from interactive prediction. Labels/providers being unavailable must not prevent history/default suggestions.
- Return exactly six usable phrases, preserve the two-second AI fallback behavior, and never automatically select or speak them.
- Treat custom descriptions and event text as untrusted data, not agent instructions. Validate outputs against categories, scope, limits, and existing definitions.
- Do not infer diagnoses or store raw microphone audio/conversation transcripts. External analysis requires explicit caregiver consent and minimal payloads, as described in the data outline.

## 8. Acceptance checks

- Seed reruns do not duplicate or rename starter definitions.
- A caregiver can create a custom definition and assign it without AI access.
- Duplicate normalized codes, invalid categories, cross-patient references, and invalid status transitions are rejected.
- AI proposals are visible for review but excluded from predictions until both definition and assignment approvals succeed.
- Approving a definition does not silently confirm assignments or label historical events.
- Known activity context is retained without an AI call; caregiver corrections survive repeated analysis.
- Single-value categories and `unknown` exclusions hold under concurrent writes.
- Archived definitions disappear from active prediction context while review history remains readable.
- Provider failures leave the vocabulary and existing confirmed labels unchanged; patient deletion removes patient-scoped label data and derived artifacts.

Implement after the core demo: seed vocabulary → caregiver create/assign/review UI and APIs → optional AI proposals → optional Jev classification/ranking. No new framework, autonomous agent loop, or background queue is required.
