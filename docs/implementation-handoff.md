# Implementation handoff

## Completed commits

- `2b059e3`, `777848d`: plan, runtime configuration, shared validators.
- `e745169`, `a29f59e`: Phase 2 profile backend.
- `74cec07`: Phase 3 communication history.
- `6843ebc`: Phase 4 deterministic predictions.
- Following commit: Phase 5 speech.

## Phase 5: backend complete (mocked provider)

`POST /api/aac/speak` and legacy `POST /api/speak` return `{audio_url}` for an MP3 under `/media/audio/`. Speech is provider-neutral (`aac/speech.py`, `SPEECH_PROVIDER`); ElevenLabs is the first provider, called with stdlib urllib. Polly is no longer planned for speech. Audio is cached by a hash of provider/model/voice/text; `cleanup_audio` removes files unused for 24 hours. Optional Google Home casting (`aac/casting.py`, PyChromecast) runs in the background when `GOOGLE_HOME_HOST` is set. 9 learning operations remain 501.

Checks: all 114 tests passed; makemigrations --check reports no changes. Live smoke without a key: 503 on both routes, no files, media serving works.

Not yet verified: a real ElevenLabs call (needs `ELEVENLABS_API_KEY` and `SPEECH_VOICE_ID` in `backend/.env`) and a real Google Home cast (needs a LAN `BACKEND_PUBLIC_BASE_URL` and speaker IP).

## Next

Real ElevenLabs smoke test, then Phase 7 labels or the Channels relay. Frontend and hardware/bridge are owned by others.

Do not modify or stage the unrelated untracked hardware/benchmarks/ directory. No credentials have been read or configured.
