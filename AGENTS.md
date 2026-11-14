# Smart AAC Board (HackPrinceton 2026)

A low cost AAC (augmentative and alternative communication) board for nonverbal kids. The child builds a sentence from symbols, the board speaks it aloud, and it predicts likely phrases from time of day, activity, and history. Kids with limited motor control use physical switches on an Arduino. The current demo has no touchscreen or touch sensor: use buttons and keyboard (Space = NEXT, Enter = SELECT).

This is a 36 hour hackathon build. The demo path comes first. Keep code simple: no auth, no extra abstraction layers, no features outside the current task.

## Repo layout

- `frontend/`: React + Vite + TypeScript. Symbol grid, sentence strip, prediction row, scanning highlight, input settings, caregiver dashboard.
- `backend/`: Django + Django Channels (Python). One Django app, `aac`, holds views, profiles/events/labels in SQLite, the WebSocket consumer, and Bedrock, Polly, and Google Home integrations. UNO Q 4GB is the default Django/SQLite host; keep deployment configuration portable to a server.
- `hardware/`: UNO R4 WiFi switch controller and serial bridge; UNO Q runs local transcription when the Conversation Mode stretch goal is implemented. Existing sketch/bridge protocol remains unchanged.

## Contracts (shared by all three folders; do not change without telling the team)

Backend runs on `http://localhost:8000`.

- `POST /api/speak` body `{ "text": string }` returns `{ "audio_url": string }`. Also casts the audio to the Google Home if one is configured.
- `POST /api/predict` body `{ "time": ISO string, "activity": string, "recent": string[] }` returns `{ "phrases": string[] }` with exactly 6 phrases.
- `POST /api/log` body `{ "text": string, "timestamp": ISO string }` records a spoken sentence to SQLite. The team decision supersedes the earlier DynamoDB plan; no dual writes. Success is `200 { "ok": true }`.
- `WS /ws/input/` pushes `{ "action": "NEXT" | "SELECT", "source": "button" | "touch" | "voice" }` to the frontend. The bridge sends to the same socket; the consumer broadcasts to a single Channels group, `input`.

Arduino to bridge: plain text lines over serial at 9600 baud, `NEXT`, `SELECT`, `TOUCH`, `VOICE`.

NEXT button D2, SELECT button D3 on the R4 WiFi. No touch sensor or touchscreen in the current demo; sound input is optional. Legacy TOUCH/VOICE serial and touch/voice WebSocket values remain reserved for compatibility, not required hardware. Do not transfer R4 shield/voltage assumptions to UNO Q GPIO.

## Backend conventions

- Plain Django function views returning `JsonResponse`. No Django REST Framework, no serializers.
- API views are `@csrf_exempt`; there is no auth.
- `django-cors-headers` allows `http://localhost:5173`.
- WebSockets through Django Channels with the in-memory channel layer (no Redis). Add `daphne` first in `INSTALLED_APPS` so `runserver` serves ASGI.
- SQLite on UNO Q is the application source of truth as well as Django's internal database. Use Django ORM/migrations; no second database, object database, or device/server synchronization for the hackathon. Store generated files on the filesystem, not as database blobs.
- API contracts live in `backend/aac/openapi.py`, served at `/api/openapi.json`; offline Swagger UI is at `/api/docs`. Business operations marked scaffolded are wired but return JSON 501 without side effects; method/JSON transport checks exist, field/feature validation is still pending. See `docs/api-contracts.md` before changing contracts.

## Commands

- Frontend: `cd frontend && npm install && npm run dev` (port 5173)
- Backend: `cd backend && python -m venv .venv`, activate it, `pip install -r requirements.txt`, `python manage.py migrate`, then `python manage.py runserver 8000`
- Bridge: `python hardware/bridge.py --port <serial port>` (close the Arduino Serial Monitor first; only one program can hold the port)

## Stretch goal: conversation-aware suggestions

Only work on this after the core demo path works end to end. It is not required for the demo.

- Optional Conversation Mode uses a microphone on UNO Q with local transcription/topic/reply processing, explicit caregiver activation, a visible listening indicator, and a stop control. No conversation audio/transcripts/context is sent to hosted services.
- Use a short rolling transcript to detect the current topic and suggest exactly 6 concise words or replies for the child to choose from.
- Never automatically select or speak a suggestion.
- Keep transcripts in memory only; do not persist raw audio or transcripts. Clear the transcript when Conversation Mode stops.
- If transcription or topic detection fails, keep the existing time/activity/history predictions available.
- Generated suggestions and categorical topic segments may be saved to device-local SQLite as a separate stretch feature; they are not patient actions or automatically confirmed labels. Raw audio/transcripts remain memory-only. Exclude local conversation tables from remote migration/hosted AI/public routes.
- An optional Arduino sound sensor is only an input switch; it cannot transcribe speech.
- Agree on any API contract changes with the team before implementation. Local transcription engine and integration are deferred until benchmarks and the core demo are complete.

## Rules

- AWS credentials live only in `backend/.env`, which is gitignored. Never print, log, or commit them.
- Bedrock: use a fast Claude Haiku model. Ask for JSON with exactly 6 phrases. If the call fails or takes over 2 seconds, fall back to the most frequent phrases for that time of day.
- Polly: neural engine, a child sounding voice.
- UI: large readable targets (at least 120px), high contrast, an unmistakable scanning highlight. Button and keyboard access are required; touch hardware is not.
- Keyboard fallback always works: Space = NEXT, Enter = SELECT.
- Debounce buttons. The vocal switch fires only on sound above the threshold lasting about half a second.
- Seed data for the demo persona lives in `backend/seed/`.
