# AAC backend scaffold

Django project: `config`. Application: `aac` (augmentative and alternative communication).

Only Django scaffolding and empty feature modules are present. API routes, WebSockets, AWS integrations, CORS, environment loading, and casting are not implemented or configured yet. See [the MVP plan](../docs/backend-mvp-plan.md).

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

The server runs on `http://localhost:8000`. There are no API endpoints yet; `/` returning 404 is expected. The generated Django admin route is retained, but no application authentication has been added.

```sh
python manage.py test
```

The test package is empty for now. Settings are development-only, including the placeholder Django secret key. `.env` loading will be added with configuration work; never put AWS credentials in source files.

## Layout

```text
config/                     Django settings, root URLs, ASGI and WSGI entrypoints
aac/
  views.py                  Future HTTP handlers
  consumers.py              Future WebSocket relay
  routing.py                Future WebSocket routes
  speech.py                 Future Polly integration
  predictions.py            Future ranking and Bedrock integration
  history.py                Future DynamoDB history
  casting.py                Future optional Google Home integration
  management/commands/      Future seed/cleanup commands
  migrations/               Standard Django app migrations
  tests/                    Future feature tests
seed/                       Future demo persona data
media/audio/                Ignored generated audio
```

Only Django is a direct dependency at this stage. Add Channels, Daphne, CORS, boto3, and dotenv when their setup or integrations are implemented, not for empty placeholders.
