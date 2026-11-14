# Implementation handoff

## Completed commits

- `2b059e3`: consolidated MVP plan and recorded foundation progress.
- `777848d`: runtime configuration, restricted CORS, shared transport/value validators and tests.
- `e745169`, `a29f59e`: Phase 2 profile backend (models, migration, six operations, `seed_demo`), reviewed, documented and smoke-tested.
- Following commit: Phase 3 communication history backend.

## Phase 3: backend complete

`POST /api/aac/events`, `GET /api/aac/patients/{id}/events` and legacy `POST /api/log` work. Migration 0002 adds `CommunicationEvent` (client event ID as primary key, one spoken event per utterance, patient-local time bucket) and a minimal `PredictionRecord`. `seed_demo` adds 20 synthetic spoken events from `backend/seed/demo_history.json`. 13 operations remain 501.

Contract note for the team: `Event.input_source` is now nullable, used only for `/api/log` entries (that route has no source field). Request shapes are unchanged.

Checks: Django check passed; all 79 tests passed; makemigrations --check reports no changes. Temporary-database smoke test: 201 → identical retry 200 → changed retry 409, `/api/log` 200, history persisted across a restart. The developer database has migration 0002 applied and is seeded (2 profiles, 20 events).

Known limits: nothing creates `PredictionRecord` rows until Phase 4, so attributed events 404 outside tests. `/api/log` has no retry safety by contract. Frontend patient switching and event recording after completed playback are still absent.

## Next

Phase 4: deterministic predictions (`/api/aac/predict`, legacy `/api/predict`), creating `PredictionRecord` rows and ranking confirmed spoken history with the time buckets in `aac/history.py`. Follow docs/mvp-phase-plan.md; do not jump to cloud AI.

Do not modify or stage the unrelated untracked hardware/benchmarks/ directory. No AWS credentials have been read or configured. No Channels/input relay, frontend or cloud feature has been implemented.
