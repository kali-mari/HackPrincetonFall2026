# AAC backend

Django project: `config`. Application: `aac` (augmentative and alternative communication).

**Implemented:** runtime environment loading, SQLite/media/static path settings, local allowed hosts, restricted development CORS, reusable transport/value validators, OpenAPI contracts and offline Swagger UI, the six profile operations (caregiver/patient models, setup/preferences validation, caregiver-scoped patient pagination, the `seed_demo` command), and Phase 3 communication history: `POST /api/aac/events`, `GET /api/aac/patients/{id}/events` and legacy `POST /api/log`, with `CommunicationEvent` and a minimal `PredictionRecord` for attribution, and Phase 4 deterministic predictions: `POST /api/aac/predict` and legacy `POST /api/predict`.

**Still scaffolded:** the other 11 HTTP business operations (speech, learning, legacy speak) return JSON 501. Channels/WebSocket relay, AWS integrations and casting are not implemented. No frontend uses the profile routes yet and there is no patient switching, so Phase 2 is not complete end to end. The ASGI entrypoint currently serves HTTP only; Channels/Daphne arrive with input relay work.

Follow the consolidated [MVP implementation plan](../docs/mvp-phase-plan.md), [API contracts/status](../docs/api-contracts.md) and [data outline](../docs/data-outline.md).

## Local setup

Python 3.12.12 is selected by `backend/.python-version` using pyenv.

```sh
cd backend
pyenv install -s 3.12.12
pyenv exec python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # first setup only; do not overwrite an existing .env
python manage.py check
python manage.py migrate
python manage.py seed_demo  # safe to rerun; keeps profile edits, restores missing seed history
python manage.py runserver 8000
```

Django reads `backend/.env` regardless of the shell's working directory. Existing process environment values take precedence. Restart Django after changing configuration. `.env` is ignored by git; never print or commit secrets, and never put backend credentials in frontend settings.

The server runs on `http://localhost:8000`:

- `/api/docs`: offline Swagger UI; implemented and scaffold operations are marked and Try it out is enabled.
- `/api/openapi.json`: OpenAPI 3.1 source for frontend tooling.
- `/api/profile/*`: implemented. Create caregivers and patients, list a caregiver's patients (`limit`, opaque `cursor`), and read, patch or delete a patient. Errors: 400 invalid fields/query/cursor, 404 unknown or wrong-role profile, 405 wrong method, 503 when SQLite storage is unavailable (no partial writes; the message never includes database details).
- `POST /api/aac/events`: saves a selection, spoken or feedback event. New event 201; identical retry (same `event_id`, same normalized content) 200; changed retry, a second spoken event for one utterance, or an utterance reused for another patient 409; unknown patient or prediction 404; text that does not match the referenced prediction candidate 400; storage failure 503.
- `GET /api/aac/patients/{id}/events`: newest first, `limit` and signed `cursor` like the patient list.
- `POST /api/log`: unchanged legacy shape; saves a spoken event for `LEGACY_DEMO_PATIENT_ID` and returns `{"ok": true}`. No retry safety; 503 if the demo patient has not been seeded.
- `POST /api/aac/predict`: six phrases ranked from the patient's confirmed spoken history, saved as a `PredictionRecord` whose ID the client sends back on attributed events. 404 unknown patient; 503 only if the record cannot be saved (unreadable history falls back to defaults).
- `POST /api/predict`: same ranking for `LEGACY_DEMO_PATIENT_ID`, legacy `{"phrases": [...]}` shape, no saved record. Always 200 for a valid request; defaults if the demo patient is missing or storage fails.
- Other `/api/aac/*`, `/api/learn/*`, and legacy speak routes: JSON 501, with 400 for malformed JSON transport and 405 for wrong methods.
- `/`: 404 expected.

The generated admin route remains; no application authentication has been added. Migrations create Django's internal tables plus `Profile`, `CaregiverPatient` (0001), `PredictionRecord` and `CommunicationEvent` (0002). Each event stores a patient-local `time_bucket` (`night` 0–5, `morning` 5–11, `midday` 11–14, `afternoon` 14–17, `evening` 17–21, `night` 21–24, defined in `aac/history.py`) computed from the patient's timezone when it is saved. Role-specific setup and link roles are checked by model validation on every `save()`; SQLite check constraints back the per-row rules, but bulk ORM writes skip the cross-row caregiver/patient role check. SQLite is also the chosen application store on UNO Q; no DynamoDB or second database.

## Runtime settings

| Variable | Default | Behavior |
| --- | --- | --- |
| `DJANGO_DEBUG` | `true` | Accepts true/false, 1/0, yes/no, on/off (case-insensitive); other values fail startup |
| `DJANGO_SECRET_KEY` | Local development key when debug is true | Set a private key for non-debug use; missing/blank or the built-in development key fails startup when debug is false |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Comma-separated hostnames/IPs, without schemes or ports |
| `SQLITE_PATH` | `db.sqlite3` | Database file; absolute or relative to `backend/` |
| `MEDIA_ROOT` | `media` | Future generated files; absolute or relative to `backend/` |
| `STATIC_ROOT` | `staticfiles` | `collectstatic` output; absolute or relative to `backend/` |
| `BACKEND_PUBLIC_BASE_URL` | `http://localhost:8000` | Absolute HTTP(S) base for future audio URLs; trailing slash removed; credentials/query/fragment rejected |
| `LEGACY_DEMO_PATIENT_ID` | `22222222-2222-4222-8222-222222222222` | Fixed synthetic patient created by `seed_demo` and used by `/api/log` (and later legacy speak/predict); must be a UUID (startup fails otherwise) and must differ from the demo caregiver `11111111-1111-4111-8111-111111111111`. Not a "currently selected patient" setting |

Create parent directories for custom SQLite paths before `migrate`, and ensure database/media locations are writable on UNO Q. Settings do not create application records (`seed_demo` does, including 20 synthetic spoken events from `seed/demo_history.json`), synthesize audio, or implement media serving. Public/static/media server deployment remains a later integration task. Keep custom generated-file paths outside version control; default SQLite files, `data/`, media and collected static files are ignored.

Development CORS permits **only `http://localhost:5173`**, for `/api/` routes, without credentials. JSON preflight requests are handled by CORS middleware; unfinished business calls still return 501. Other origins do not receive CORS permission. Non-CORS OPTIONS retains the documented method-discovery behavior.

This is an unauthenticated trusted-local-network demo, not a public deployment. CORS and allowed hosts are not authentication. Bind locally by default. For a later LAN demo, explicitly add the device IP/hostname to allowed hosts and configure reachable frontend/backend URLs. A speaker cannot fetch another device's `localhost`; casting and its LAN setup are not implemented in this slice.

## Shared request validation

`aac/http.py` exposes `check_method(request, methods)` (returns an OPTIONS/405 response or `None`) and `read_json_object(request)` (returns the parsed object). This preserves the existing UTF-8/64 KiB/finite-number checks while making parsed data available to real views.

`aac/validation.py` provides focused functions for required/unknown fields, bounded nonblank Unicode strings, hyphenated UUIDs, timestamps with explicit offsets (normalized to UTC), IANA timezones, strict JSON integers and page limits (default 50, range 1–100; repeated limits rejected). Strings trim by default; use `trim=False` where exact text must be preserved. Length limits apply before trimming.

Future plain views should check methods first, parse JSON, call explicit field validators and catch `InvalidRequest`, returning `error_response('invalid_request', str(error), 400)`. Validators do not echo submitted values. Record existence, roles/ownership, preferences, cursor decoding and other feature-specific rules still belong to their implementation slices. These are small functions, not automatic OpenAPI validation or a new schema framework.

Profile views use these helpers plus `profile_validation.py` (patient setup/preferences) and `profiles.py` (serialization and signed, caregiver-scoped keyset cursors). Event views use `history.py` (event validation, retry comparison, time buckets, serialization and patient-scoped cursors). Prediction views use `predictions.py` (request validation, ranking tiers, decay weights, tie ordering and curated defaults). The 11 remaining scaffolds still validate transport only and return 501 even for `{}` or invalid field/query values.

## Checks and tests

```sh
pip install -r requirements-dev.txt
python manage.py check
python manage.py test
python manage.py export_openapi > /tmp/aac-openapi.json
```

Tests cover isolated runtime settings/dotenv precedence (including `LEGACY_DEMO_PATIENT_ID`), paths, invalid configuration, allowed hosts, browser preflight/origin restrictions, value validators, parsed JSON access and helper composition in a test-only plain view, contracts/examples, offline documentation assets, the 11 remaining scaffolds, the profile feature, event history (retries, conflicts, attribution, pagination, legacy log, cascade deletion, seeded history) and predictions (defaults, decay, context tiers, case-insensitive merging, deterministic ties, patient isolation, attribution round trip, fallbacks). Profile tests run against Django's migrated test database: response schemas, validation, role scoping, pagination/cursors, deletion, atomic rollback, 503 handling, database constraints and `seed_demo`. Configuration tests substitute a temporary dotenv file and a cleared environment rather than reading a developer's secrets. No AWS or device is required.

Manual HTTP smoke checks after starting Django:

```sh
curl -i http://localhost:8000/api/docs
curl -i -X OPTIONS http://localhost:8000/api/predict \
  -H 'Origin: http://localhost:5173' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
curl -i http://localhost:8000/api/predict \
  -H 'Origin: http://localhost:5173' \
  -H 'Content-Type: application/json' --data '{}'
```

Expected: Swagger 200, preflight 200 with the permitted origin, business request JSON 501 with the same CORS header. After `seed_demo`, `curl http://localhost:8000/api/profile/caregivers/11111111-1111-4111-8111-111111111111/patients` lists the demo patient.

Runtime-slice verification: `manage.py check` and all 29 tests passed on Python 3.12.12. A live local HTTP smoke test verified Swagger, permitted preflight, JSON 501 with CORS headers and omission of permission for an untrusted origin. Migrations and `collectstatic` succeeded with temporary configured paths, including the offline Swagger bundle; the existing database was untouched. UNO Q, browser UI, hardware and cloud smoke tests remain pending.

Validation-slice verification: `manage.py check` and all 43 tests passed on Python 3.12.12. Tests cover wrong types/booleans, unknown/missing fields, offset normalization and UTC overflow, invalid IANA names, ambiguous page limits, exact body-size boundaries and the existing error envelope. No database, board or cloud service was used.

Profile-slice verification: `manage.py check`, all 64 tests and `makemigrations --check` passed on Python 3.12.12. A manual smoke test against a temporary `SQLITE_PATH` ran migrate, `seed_demo` twice, caregiver/patient create, patch, delete and a 400 case, then restarted Django and confirmed the changes persisted; the developer database was untouched. No frontend, UNO Q or hardware test yet.

Event-history verification: `manage.py check`, all 79 tests and `makemigrations --check` passed. Manual smoke test on a temporary database: seed, event 201 → identical retry 200 → changed retry 409, `/api/log` 200, then a restart with all 22 events still listed newest first.

Prediction verification: all 93 tests passed. Manual smoke test on a seeded temporary database returned activity-appropriate suggestions (breakfast, lunch, bedtime), time-of-day history for an unknown activity, and the legacy shape.

## Layout

```text
config/                     Runtime settings, URLs, HTTP ASGI and WSGI entrypoints
.env.example                Placeholder-only runtime configuration
requirements.txt            Django, CORS middleware and dotenv (pinned)
aac/
  documentation.py          Working schema and Swagger views
  openapi.py                Contract source; each operation marked implemented or scaffolded
  static/aac/               Offline Swagger assets and initializer
  templates/aac/            Swagger HTML
  urls.py                   Namespaced HTTP route wiring
  models.py                 Profiles, links, prediction records and events (SQLite)
  profile_validation.py     Patient setup/preferences validation
  profiles.py               Profile JSON and signed patient-list cursors
  history.py                Event validation, time buckets, event JSON and cursors
  views.py                  CSRF-exempt function views: profiles, events, log, plus JSON 501 scaffolds
  http.py                   Reusable method/JSON transport checks and scaffolds
  validation.py             Explicit value/field/query helpers; no ORM access
  consumers.py, routing.py  Future WebSocket relay
  speech.py                 Future Polly integration
  predictions.py            Deterministic ranking and defaults (Bedrock later)
  casting.py                Future optional Google Home integration
  management/commands/      Schema export and seed_demo
  migrations/               Application migrations (0001 profiles, 0002 history)
  tests/                    Runtime, contract/documentation, scaffold and profile tests
seed/                       Synthetic demo history loaded by seed_demo
media/audio/                Ignored generated audio
```

Add Channels/Daphne, boto3 and optional casting dependencies when their integrations are implemented, not for empty placeholders. Next backend slice: Phase 5 Polly speech (`/api/aac/speak`, legacy `/api/speak`).
