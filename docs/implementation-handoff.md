# Implementation handoff

Stopped at the user's request to switch model providers.

## Completed commits

- `2b059e3`: consolidated MVP plan and recorded foundation progress.
- `777848d`: runtime configuration, restricted CORS, shared transport/value validators and tests.

## Profile feature — WIP, not ready to call complete

Current work adds Profile/CaregiverPatient models and initial migration, six working profile operations, explicit setup/preferences validation, caregiver-scoped signed keyset cursors, a repeatable `seed_demo` command and fixed `LEGACY_DEMO_PATIENT_ID` configuration. OpenAPI and Swagger distinguish implemented profiles from 16 remaining scaffolds. Tests cover response schemas, atomic rollback, isolation, deletion, pagination, validation, constraints and seeds.

Latest checks: Django check passed; all 62 tests passed; makemigrations --check --dry-run reports no changes; git diff --check passed. The local application database has NOT been migrated or seeded. No target-device/manual persistence smoke test has been run for profiles.

Before completing the profile feature:

1. Review the implementation, especially model validation/constraints, cursor scope and database error handling. Cross-row caregiver/patient roles are enforced by model validation, not SQL joins/check constraints; bulk ORM writes bypass that validation.
2. Update backend/README.md, docs/api-contracts.md, docs/data-outline.md and docs/mvp-phase-plan.md: they still describe all 22 business operations as scaffolded. Six profile operations now work; 16 AAC/learning/legacy operations remain 501. Frontend/patient switching is still absent, so Phase 2 is not end-to-end complete.
3. Document the additive profile 503 error responses for unavailable SQLite storage and LEGACY_DEMO_PATIENT_ID/seed_demo setup. Requests/normal success shapes are unchanged.
4. Simplify the status expectation logic in test_invalid_patient_fields_and_relationships if useful; it passes but could be clearer. Add runtime coverage for invalid/configured LEGACY_DEMO_PATIENT_ID.
5. Run a temporary-database migration/seed/restart/CRUD smoke test (do not overwrite the developer's database), rerun tests and commit the completion separately.

Next backend feature after profile completion is Phase 3: communication event history and retry safety, including minimal PredictionRecord attribution storage. Follow docs/mvp-phase-plan.md; do not jump to cloud AI.

Do not modify or stage the unrelated untracked hardware/benchmarks/ directory. No AWS credentials have been read or configured. No Channels/input relay, frontend or cloud feature has been implemented.
