# Implementation handoff

## Completed commits

- `2b059e3`: consolidated MVP plan and recorded foundation progress.
- `777848d`: runtime configuration, restricted CORS, shared transport/value validators and tests.
- `e745169` + the following commit: Phase 2 profile backend (models, migration, six operations, `seed_demo`), reviewed, documented and smoke-tested.

## Profile feature: backend complete

Six profile operations work; 16 AAC/learning/legacy operations remain 501. Docs (backend/README.md, api-contracts.md, data-outline.md, mvp-phase-plan.md) describe this split, the additive profile 503 response and `LEGACY_DEMO_PATIENT_ID`/`seed_demo` setup.

Checks: Django check passed; all 64 tests passed; makemigrations --check reports no changes. Manual smoke test on a temporary SQLITE_PATH: migrate, seed_demo twice, caregiver/patient create, patch, delete, 400 case, server restart with data persisted; the developer's db.sqlite3 was untouched (checksum verified). The developer's database itself has not been migrated or seeded; run `python manage.py migrate && python manage.py seed_demo` once.

Known limits: caregiver/patient roles on links are enforced by model validation, not SQL, so bulk ORM writes bypass them. IntegrityError from a race would surface as 503 rather than 409; no API path can currently trigger one. Frontend patient selection/switching is absent, so Phase 2 is not end-to-end complete.

## Next

Phase 3: communication event history and retry safety, including minimal PredictionRecord attribution storage. Follow docs/mvp-phase-plan.md; do not jump to cloud AI.

Do not modify or stage the unrelated untracked hardware/benchmarks/ directory. No AWS credentials have been read or configured. No Channels/input relay, frontend or cloud feature has been implemented.
