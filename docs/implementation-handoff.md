# Implementation handoff

## Completed commits

- `2b059e3`: consolidated MVP plan and recorded foundation progress.
- `777848d`: runtime configuration, restricted CORS, shared transport/value validators and tests.
- `e745169`, `a29f59e`: Phase 2 profile backend.
- `74cec07`: Phase 3 communication history (events, patient history, legacy log, seeded history).
- Following commit: Phase 4 deterministic predictions.

## Phase 4: backend complete

`POST /api/aac/predict` and legacy `POST /api/predict` work without network access. Ranking in `aac/predictions.py`: confirmed spoken history only, weight `0.5 ** (age_days/7)` from the request time, tiers (activity + time bucket, activity, time bucket, all history, curated defaults), case-insensitive merging, ties by recency then phrase. The new route saves a `PredictionRecord` for attribution; legacy saves nothing. 11 operations remain 501.

Contract notes for the team: `/api/aac/predict` gained an additive 503, returned only when the prediction record cannot be saved (unreadable history still returns defaults with 200). Legacy `/api/predict` never errors for a valid request. From Phase 3: `Event.input_source` is nullable for `/api/log` entries.

Checks: all 93 tests passed; makemigrations --check reports no changes (no new migration). Seeded temporary-database smoke test returned activity-appropriate suggestions and the legacy shape.

Known limits: `recent` is validated but unused. `artifact_version` is always null. No Bedrock enhancement (Phase 8). Frontend display of suggestions is not built.

## Next

Phase 5: Polly speech (`/api/aac/speak`, `/api/speak`). Needs AWS credentials in `backend/.env` and a confirmed neural child voice/region. Follow docs/mvp-phase-plan.md.

Do not modify or stage the unrelated untracked hardware/benchmarks/ directory. No AWS credentials have been read or configured. No Channels/input relay, frontend or cloud feature has been implemented.
