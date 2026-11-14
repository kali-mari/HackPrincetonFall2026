"""Provider-neutral text-to-speech: MP3 files under MEDIA_ROOT/audio, optionally cached.

A provider is a function (text, voice_id, model_id) -> MP3 bytes that raises
SpeechUnavailable on failure. Register it in PROVIDERS and select it with
SPEECH_PROVIDER; caching, storage, URLs and casting stay provider-independent.
"""

from hashlib import sha256
import http.client
import json
import os
from urllib.parse import quote
import urllib.request
from uuid import uuid4

from django.conf import settings

TIMEOUT_SECONDS = 10
MAX_AUDIO_BYTES = 5 * 1024 * 1024


class SpeechUnavailable(Exception):
    """Safe 503 message; never includes provider responses, keys or text."""


def elevenlabs(text, voice_id, model_id):
    if not settings.ELEVENLABS_API_KEY:
        raise SpeechUnavailable('Speech is not configured.')
    request = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe="")}?output_format=mp3_44100_128',
        data=json.dumps({'text': text, 'model_id': model_id or 'eleven_flash_v2_5'}).encode(),
        headers={
            'xi-api-key': settings.ELEVENLABS_API_KEY,
            'Content-Type': 'application/json', 'Accept': 'audio/mpeg',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read(MAX_AUDIO_BYTES + 1)
    except (OSError, http.client.HTTPException):  # Includes HTTP errors and timeouts.
        raise SpeechUnavailable('Speech is unavailable.') from None


PROVIDERS = {'elevenlabs': elevenlabs}


def audio_url(name):
    return f'{settings.BACKEND_PUBLIC_BASE_URL}{settings.MEDIA_URL}audio/{name}'


def synthesize(text, voice_id=None):
    """Return an absolute playable URL for text, or raise SpeechUnavailable."""
    provider = PROVIDERS.get(settings.SPEECH_PROVIDER)
    voice = voice_id or settings.SPEECH_VOICE_ID
    if provider is None or not voice:
        raise SpeechUnavailable('Speech is not configured.')
    if settings.SPEECH_CACHE:
        # The name hashes provider/model/voice/text; it never contains the text itself.
        key = json.dumps([settings.SPEECH_PROVIDER, settings.SPEECH_MODEL_ID, voice, text])
        name = f'{sha256(key.encode()).hexdigest()}.mp3'
    else:
        name = f'{uuid4().hex}.mp3'
    directory = settings.MEDIA_ROOT / 'audio'
    path = directory / name
    try:
        if settings.SPEECH_CACHE and path.exists():
            os.utime(path)  # Recently used phrases survive cleanup_audio.
            return audio_url(name)
        audio = provider(text, voice, settings.SPEECH_MODEL_ID)
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise SpeechUnavailable('Speech is unavailable.')
        directory.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a concurrent request never serves a partial file.
        temporary = directory / f'{uuid4().hex}.tmp'
        temporary.write_bytes(audio)
        os.replace(temporary, path)
    except OSError:
        raise SpeechUnavailable('Audio storage is unavailable.') from None
    return audio_url(name)
