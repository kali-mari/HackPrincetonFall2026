# AAC backend

Django project: `config`. Application: `aac` (augmentative and alternative communication).

**Implemented:** runtime environment loading, SQLite/media/static path settings, local allowed hosts, restricted development CORS, reusable transport/value validators, HTTP scaffolds, OpenAPI contracts and offline Swagger UI.

**Still scaffolded:** all 22 HTTP business operations return JSON 501. Application models/migrations, endpoint-specific field/relationship validation, Channels/WebSocket relay, AWS integrations and casting are not implemented. The ASGI entrypoint currently serves HTTP only; Channels/Daphne arrive with input relay work.

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
python manage.py runserver 8000
```

Django reads `backend/.env` regardless of the shell's working directory. Existing process environment values take precedence. Restart Django after changing configuration. `.env` is ignored by git; never print or commit secrets, and never put backend credentials in frontend settings.

The server runs on `http://localhost:8000`:

- `/api/docs`: offline Swagger UI; scaffold operations are marked and Try it out is enabled.
- `/api/openapi.json`: OpenAPI 3.1 source for frontend tooling.
- `/api/profile/*`, `/api/aac/*`, `/api/learn/*`, and legacy HTTP routes: JSON 501, with 400 for malformed JSON transport and 405 for wrong methods. No business side effects or field validation yet.
- `/`: 404 expected.

The generated admin route remains; no application authentication has been added. Migrations currently initialize Django's internal tables, not future application records. SQLite is also the chosen application store on UNO Q; no DynamoDB or second database.

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

Create parent directories for custom SQLite paths before `migrate`, and ensure database/media locations are writable on UNO Q. Settings do not create application records, synthesize audio, or implement media serving. Public/static/media server deployment remains a later integration task. Keep custom generated-file paths outside version control; default SQLite files, `data/`, media and collected static files are ignored.

Development CORS permits **only `http://localhost:5173`**, for `/api/` routes, without credentials. JSON preflight requests are handled by CORS middleware; real business calls still return 501. Other origins do not receive CORS permission. Non-CORS OPTIONS retains the documented method-discovery behavior.

This is an unauthenticated trusted-local-network demo, not a public deployment. CORS and allowed hosts are not authentication. Bind locally by default. For a later LAN demo, explicitly add the device IP/hostname to allowed hosts and configure reachable frontend/backend URLs. A speaker cannot fetch another device's `localhost`; casting and its LAN setup are not implemented in this slice.

## Shared request validation

`aac/http.py` exposes `check_method(request, methods)` (returns an OPTIONS/405 response or `None`) and `read_json_object(request)` (returns the parsed object). This preserves the existing UTF-8/64 KiB/finite-number checks while making parsed data available to real views.

`aac/validation.py` provides focused functions for required/unknown fields, bounded nonblank Unicode strings, hyphenated UUIDs, timestamps with explicit offsets (normalized to UTC), IANA timezones, strict JSON integers and page limits (default 50, range 1–100; repeated limits rejected). Strings trim by default; use `trim=False` where exact text must be preserved. Length limits apply before trimming.

Future plain views should check methods first, parse JSON, call explicit field validators and catch `InvalidRequest`, returning `error_response('invalid_request', str(error), 400)`. Validators do not echo submitted values. Record existence, roles/ownership, preferences, cursor decoding and other feature-specific rules still belong to their implementation slices. These are small functions, not automatic OpenAPI validation or a new schema framework.

**Scaffold behavior is unchanged:** all 22 operations still validate transport only and return 501 even for `{}` or invalid field/query values. Helpers are available and tested, but routes opt into field validation only when their features are implemented. No new API path, schema or implementation status was introduced.

## Checks and tests

```sh
pip install -r requirements-dev.txt
python manage.py check
python manage.py test
python manage.py export_openapi > /tmp/aac-openapi.json
```

Tests cover isolated runtime settings/dotenv precedence, paths, invalid configuration, allowed hosts, browser preflight/origin restrictions, value validators, parsed JSON access and helper composition in a test-only plain view, contracts/examples, offline documentation assets and all 22 business scaffolds. Configuration tests substitute a temporary dotenv file and a cleared environment rather than reading a developer's secrets. No AWS, device or database is required by the current tests.

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

Expected: Swagger 200, preflight 200 with the permitted origin, business request JSON 501 with the same CORS header. No business feature is advertised as implemented.

Runtime-slice verification: `manage.py check` and all 29 tests passed on Python 3.12.12. A live local HTTP smoke test verified Swagger, permitted preflight, JSON 501 with CORS headers and omission of permission for an untrusted origin. Migrations and `collectstatic` succeeded with temporary configured paths, including the offline Swagger bundle; the existing database was untouched. UNO Q, browser UI, hardware and cloud smoke tests remain pending.

Validation-slice verification: `manage.py check` and all 43 tests passed on Python 3.12.12. Tests cover wrong types/booleans, unknown/missing fields, offset normalization and UTC overflow, invalid IANA names, ambiguous page limits, exact body-size boundaries and the existing error envelope. No database, board or cloud service was used.

## Layout

```text
config/                     Runtime settings, URLs, HTTP ASGI and WSGI entrypoints
.env.example                Placeholder-only runtime configuration
requirements.txt            Django, CORS middleware and dotenv (pinned)
aac/
  documentation.py          Working schema and Swagger views
  openapi.py                Contract source; business routes marked scaffolded
  static/aac/               Offline Swagger assets and initializer
  templates/aac/            Swagger HTML
  urls.py                   Namespaced HTTP route wiring
  views.py                  CSRF-exempt function views returning JSON 501
  http.py                   Reusable method/JSON transport checks and scaffolds
  validation.py             Explicit value/field/query helpers; no ORM access
  consumers.py, routing.py  Future WebSocket relay
  speech.py                 Future Polly integration
  predictions.py            Future ranking and Bedrock integration
  history.py                Future SQLite history/ranking helpers
  casting.py                Future optional Google Home integration
  management/commands/      Schema export; future seed/cleanup commands
  migrations/               Future application migrations
  tests/                    Runtime, contract/documentation and scaffold tests
seed/                       Future synthetic persona data
media/audio/                Ignored generated audio
```

Add Channels/Daphne, boto3 and optional casting dependencies when their integrations are implemented, not for empty placeholders. Next backend slice: caregiver/patient models and setup endpoints, using the shared validators.
