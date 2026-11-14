# Smart AAC Board (HackPrinceton 2026)

A low cost AAC (augmentative and alternative communication) board for nonverbal kids. The child builds a sentence from symbols, the board speaks it aloud, and it predicts likely phrases from time of day, activity, and history. Kids with limited motor control use physical switches on an Arduino instead of the touchscreen.

This is a 36 hour hackathon build. The demo path comes first. Keep code simple: no auth, no extra abstraction layers, no features outside the current task.

## Repo layout

- `frontend/`: React + Vite + TypeScript. Symbol grid, sentence strip, prediction row, scanning highlight, input settings, caregiver dashboard.
- `backend/`: Django + Django Channels (Python). One Django app, `aac`, holds the views, the WebSocket consumer, and the Bedrock, text-to-speech, and Google Home code.
- `hardware/`: Arduino Uno sketch (`aac_switch/`) and the Python serial bridge (`bridge.py`).

## Contracts (shared by all three folders; do not change without telling the team)

Backend runs on `http://localhost:8000`.

- `POST /api/speak` body `{ "text": string }` returns `{ "audio_url": string }`. Also casts the audio to the Google Home if one is configured.
- `POST /api/predict` body `{ "time": ISO string, "activity": string, "recent": string[] }` returns `{ "phrases": string[] }` with exactly 6 phrases.
- `POST /api/log` body `{ "text": string, "timestamp": ISO string }` records a spoken sentence to DynamoDB.
- `WS /ws/input/` pushes `{ "action": "NEXT" | "SELECT", "source": "button" | "touch" | "voice" }` to the frontend. The bridge sends to the same socket; the consumer broadcasts to a single Channels group, `input`.

Arduino to bridge: plain text lines over serial at 9600 baud, `NEXT`, `SELECT`, `TOUCH`, `VOICE`.

Grove pins (base shield set to 5V): NEXT button D2, SELECT button D3, touch sensor D4, sound sensor A0.

## Backend conventions

- Plain Django function views returning `JsonResponse`. No Django REST Framework, no serializers.
- API views are `@csrf_exempt`; there is no auth.
- `django-cors-headers` allows `http://localhost:5173`.
- WebSockets through Django Channels with the in-memory channel layer (no Redis). Add `daphne` first in `INSTALLED_APPS` so `runserver` serves ASGI.
- The default SQLite database is only for Django internals. Phrase history lives in DynamoDB.

## Commands

- Frontend: `cd frontend && npm install && npm run dev` (port 5173)
- Backend: `cd backend && python -m venv .venv`, activate it, `pip install -r requirements.txt`, `python manage.py migrate`, then `python manage.py runserver 8000`
- Bridge: `python hardware/bridge.py --port <serial port>` (close the Arduino Serial Monitor first; only one program can hold the port)

## Rules

- AWS and speech-provider credentials (for example `ELEVENLABS_API_KEY`) live only in `backend/.env`, which is gitignored. Never print, log, or commit them.
- Bedrock: use a fast Claude Haiku model. Ask for JSON with exactly 6 phrases. If the call fails or takes over 2 seconds, fall back to the most frequent phrases for that time of day.
- Speech: provider-neutral `aac/speech.py`, selected by `SPEECH_PROVIDER` (currently ElevenLabs), with a child sounding voice set by `SPEECH_VOICE_ID`.
- UI: large touch targets (at least 120px), high contrast, an unmistakable scanning highlight.
- Keyboard fallback always works: Space = NEXT, Enter = SELECT.
- Debounce buttons. The vocal switch fires only on sound above the threshold lasting about half a second.
- Seed data for the demo persona lives in `backend/seed/`.
