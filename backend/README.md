# AAC backend scaffold

Django project: `config`. Application: `aac` (augmentative and alternative communication).

Django scaffolding, HTTP routes, OpenAPI contracts and offline Swagger UI are present. Business routes return JSON 501 pending feature implementation; models/migrations, WebSockets, AWS integrations, CORS, environment loading, and casting are not implemented yet. See [API contracts](../docs/api-contracts.md) and the current [data outline](../docs/data-outline.md); the older MVP plan has superseded storage/hardware assumptions.

## Local setup

Python 3.12.12 is selected by `backend/.python-version` using pyenv.

```sh
cd backend
pyenv install -s 3.12.12
pyenv exec python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py check
python manage.py migrate
python manage.py runserver 8000
```

The server runs on `http://localhost:8000`:

- `/api/docs`: offline Swagger UI (no CDN); scaffold operations are clearly marked and Try it out is enabled.
- `/api/openapi.json`: OpenAPI 3.1 source for frontend tooling.
- `/api/profile/*`, `/api/aac/*`, `/api/learn/*`, and legacy HTTP routes: wired scaffolds return JSON 501, with 400 for malformed JSON transport and 405 for wrong methods. No feature side effects or field-level validation yet.
- `/`: 404 expected.

The generated admin route is retained; no application authentication has been added. Export and validate contracts:

```sh
python manage.py export_openapi > /tmp/aac-openapi.json
pip install -r requirements-dev.txt
python manage.py test
```

Tests validate the schema/examples, documentation routes and all 22 HTTP business scaffolds; no AWS, device, or database is required. Settings remain development-only, including the placeholder Django secret key. `.env` loading/server deployment will be added later; never put AWS credentials in source files. SQLite on UNO Q is the chosen future application store, not DynamoDB.

## Layout

```text
config/                     Django settings, root URLs, ASGI and WSGI entrypoints
aac/
  documentation.py          Working schema and Swagger views
  openapi.py                Contract source; business routes marked scaffolded
  static/aac/               Offline Swagger assets and initializer
  templates/aac/            Swagger HTML
  urls.py                   Namespaced HTTP route wiring
  views.py                  CSRF-exempt function views returning JSON 501
  http.py                   Method/JSON transport checks; no feature validation
  consumers.py              Future WebSocket relay
  routing.py                Future WebSocket routes
  speech.py                 Future Polly integration
  predictions.py            Future ranking and Bedrock integration
  history.py                Future SQLite history/ranking helpers
  casting.py                Future optional Google Home integration
  management/commands/      Future seed/cleanup commands
  migrations/               Standard Django app migrations
  tests/                    Contract/documentation tests; future feature tests
seed/                       Future demo persona data
media/audio/                Ignored generated audio
```

Only Django is a direct dependency at this stage. Add Channels, Daphne, CORS, boto3, and dotenv when their setup or integrations are implemented, not for empty placeholders.
