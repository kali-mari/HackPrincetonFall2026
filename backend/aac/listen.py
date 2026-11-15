"""Caregiver listen mode: microphone -> phrases -> text, all on the device.

A Listener records 16 kHz mono audio with arecord from LISTEN_DEVICE (or plays an
audio file in real time with ffmpeg when LISTEN_DEVICE is file:<path>, for demos
and measurements without a microphone), cuts it into phrases with the Silero voice
detector in sherpa-onnx, and passes each phrase's text to on_text.

pause(seconds) makes every listener hear silence for that long; /api/speak calls it
so the board's own voice is not transcribed.

Audio and text stay in memory: nothing here writes or logs them.
"""

import array
import logging
import queue
import subprocess
import threading
import time

from django.conf import settings

from . import transcription
from .transcription import SAMPLE_RATE, TranscriptionUnavailable

log = logging.getLogger(__name__)

VAD_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx'
WINDOW = 512  # samples the voice detector takes per step (32 ms)
MAX_PENDING = 3  # phrases waiting for the model; the oldest is dropped beyond this
SILENCE = [0.0] * WINDOW

_pause_until = 0.0  # monotonic time until which the microphone is replaced by silence


def pause(seconds):
    """Treat the microphone as silent for the next seconds (extends, never shortens)."""
    global _pause_until
    _pause_until = max(_pause_until, time.monotonic() + seconds)
    if settings.INFERENCE_SOCKET:
        from .inference_client import request, InferenceUnavailable
        try:
            request({'op': 'pause', 'seconds': seconds}, timeout=1)
        except InferenceUnavailable:
            log.warning('Could not pause local inference: service unavailable')


def capture_command(device):
    """A command writing 16 kHz mono signed 16-bit PCM to stdout until stopped."""
    if device.startswith('file:'):  # decoded at full speed; the Listener paces it
        return ['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', device[5:],
                '-f', 's16le', '-ac', '1', '-ar', str(SAMPLE_RATE), '-']
    return ['arecord', '-q', '-D', device, '-f', 'S16_LE', '-r', str(SAMPLE_RATE),
            '-c', '1', '-t', 'raw']


def load_vad():
    path = settings.LISTEN_VAD_MODEL
    if not path.is_file():
        raise TranscriptionUnavailable('Voice detector model is not installed.')
    try:
        import sherpa_onnx
    except ImportError:
        raise TranscriptionUnavailable('Transcription runtime is not installed.') from None
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(path)
    # Pause that ends a phrase: shorter answers sooner but may split a sentence where the speaker pauses.
    config.silero_vad.min_silence_duration = settings.LISTEN_SILENCE_SECONDS
    config.silero_vad.min_speech_duration = 0.25  # shorter sounds are ignored
    config.silero_vad.max_speech_duration = 10  # long speech is cut into 10 s pieces
    config.sample_rate = SAMPLE_RATE
    config.num_threads = 1
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)


class Listener:
    """One listening session. on_text(text, delay_s) runs for each phrase, on a worker
    thread; delay_s is how long after the phrase ended its text was ready (meaningful
    for real-time sources). on_end(error) runs if capture stops by itself: error is
    None when a file source finished, otherwise a safe message."""

    def __init__(self, on_text, on_end):
        self.on_text = on_text
        self.on_end = on_end
        self.stopped = threading.Event()
        self.phrases = queue.Queue()
        self.process = None
        self.paced = False  # a file source is read at real-time speed, like a microphone
        self.remote = None

    def start(self):
        """Load the models and start recording. Blocks for the model load (seconds the
        first time); raises TranscriptionUnavailable if anything is missing."""
        if settings.INFERENCE_SOCKET:
            from .inference_client import RemoteListener
            self.remote = RemoteListener(self.on_text, self.on_end)
            self.remote.start()
            return
        transcription.load()
        vad = load_vad()
        self.paced = settings.LISTEN_DEVICE.startswith('file:')
        try:
            self.process = subprocess.Popen(
                capture_command(settings.LISTEN_DEVICE),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            raise TranscriptionUnavailable('Audio capture tool is not installed.') from None
        threading.Thread(target=self._record, args=(vad,), daemon=True).start()
        threading.Thread(target=self._transcribe, daemon=True).start()

    def stop(self):
        """Stop recording and discard phrases not yet transcribed. Safe to repeat."""
        self.stopped.set()
        if self.remote:
            self.remote.stop()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            # FFmpeg may try to flush a full stdout pipe after SIGTERM, while
            # _record has already stopped reading it. Bound shutdown so its TCP
            # source (and the Mac mic relay) cannot remain open indefinitely.
            try:
                self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        # Wake a decoder blocked waiting for a phrase, and release queued audio.
        while True:
            try:
                self.phrases.get_nowait()
            except queue.Empty:
                break
        self.phrases.put(('end', None))

    def _record(self, vad):
        started = None  # wall time of the first sample, for phrase delays
        windows = 0
        error = None
        try:
            while not self.stopped.is_set():
                data = self.process.stdout.read(WINDOW * 2)
                if len(data) < WINDOW * 2:
                    break  # capture ended: file finished, device gone or stopped
                if started is None:
                    started = time.monotonic() - WINDOW / SAMPLE_RATE
                windows += 1
                if self.paced:  # hand over each window when a microphone would have
                    time.sleep(max(0.0, started + windows * WINDOW / SAMPLE_RATE - time.monotonic()))
                if time.monotonic() < _pause_until:  # the board is speaking
                    vad.accept_waveform(SILENCE)  # ends any phrase in progress normally
                else:
                    vad.accept_waveform([s / 32768 for s in array.array('h', data)])
                self._queue_phrases(vad, started)
            if not self.stopped.is_set() and started is not None:
                vad.flush()
                self._queue_phrases(vad, started)
            if not self.stopped.is_set():
                if self.process.wait() != 0:
                    detail = self.process.stderr.read().decode(errors='replace').strip()
                    log.warning('Audio capture failed: %s', detail[-300:])
                    error = 'Microphone is not available.'
        except Exception:
            log.exception('Listen mode recording failed')
            error = 'Listening stopped after an error.'
        finally:
            self.phrases.put(('end', error))

    def _queue_phrases(self, vad, started):
        while not vad.empty():
            segment = vad.front
            ended_at = started + (segment.start + len(segment.samples)) / SAMPLE_RATE
            self.phrases.put(('phrase', (segment.samples, ended_at)))
            vad.pop()
            while self.phrases.qsize() > MAX_PENDING:
                try:
                    self.phrases.get_nowait()  # the model is behind; drop the oldest
                    log.warning('Listen mode dropped a phrase: transcription is behind')
                except queue.Empty:
                    break

    def _transcribe(self):
        while True:
            kind, value = self.phrases.get()
            if kind == 'end':
                if not self.stopped.is_set():
                    self.on_end(value)
                return
            if self.stopped.is_set():
                continue
            samples, ended_at = value
            try:
                text = transcription.transcribe_samples(samples)
            except Exception:
                log.exception('Listen mode transcription failed')
                continue
            if text and not self.stopped.is_set():
                self.on_text(text, max(0.0, time.monotonic() - ended_at))
