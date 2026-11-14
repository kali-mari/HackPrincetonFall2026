"""Optional Google Home casting of generated audio; never delays or fails speech."""

import contextlib
import logging
import threading

from django.conf import settings
import pychromecast

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 5


def cast_audio(url):
    """Start casting in the background when GOOGLE_HOME_HOST is set; return whether it started."""
    if not settings.GOOGLE_HOME_HOST:
        return False
    threading.Thread(target=play, args=(settings.GOOGLE_HOME_HOST, url), daemon=True).start()
    return True


def play(host, url):
    # Connect straight to the configured IP; no network discovery per request.
    cast = None
    try:
        cast = pychromecast.get_chromecast_from_host(
            (host, None, None, None, None), tries=1, timeout=TIMEOUT_SECONDS,
        )
        cast.wait(timeout=TIMEOUT_SECONDS)
        cast.media_controller.play_media(url, 'audio/mpeg', stream_type='BUFFERED')
        cast.media_controller.block_until_active(timeout=TIMEOUT_SECONDS)
    except Exception:  # A background thread has no caller to report to.
        logger.warning('Google Home cast failed.')  # No URL or sentence in logs.
    finally:
        if cast is not None:
            with contextlib.suppress(Exception):
                cast.disconnect(timeout=TIMEOUT_SECONDS)
