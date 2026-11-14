"""Provider-neutral speech-to-text for caregiver listen mode, running on the device.

A provider is a loader (model_dir, threads, device) -> decode, where decode takes
16 kHz mono float samples and returns text. The loader raises
TranscriptionUnavailable when its runtime or model files are missing. Register it
in PROVIDERS and select it with TRANSCRIBE_PROVIDER; the model directory, thread
count and device (TRANSCRIBE_DEVICE, for example a GPU runtime provider) are
settings, so swapping the model or moving it off the CPU does not touch callers.

Audio and transcripts stay in memory: nothing here writes or logs them.
"""

import array
import threading

from django.conf import settings

SAMPLE_RATE = 16000
MAX_SECONDS = 30  # One speech segment; split longer audio with a voice detector first.

# provider -> (archive URL, files the provider needs); used by fetch_transcription_model.
MODEL_ARCHIVES = {
    'moonshine': (
        'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
        'sherpa-onnx-moonshine-tiny-en-int8.tar.bz2',
        ['preprocess.onnx', 'encode.int8.onnx', 'uncached_decode.int8.onnx',
         'cached_decode.int8.onnx', 'tokens.txt'],
    ),
}


class TranscriptionUnavailable(Exception):
    """Safe 503 message; never includes audio or transcript content."""


def moonshine(model_dir, threads, device):
    """Moonshine tiny (English) through sherpa-onnx; device is its runtime provider."""
    files = MODEL_ARCHIVES['moonshine'][1]
    # Check first: the runtime can end the process on a missing file.
    if not all((model_dir / name).is_file() for name in files):
        raise TranscriptionUnavailable('Transcription model is not installed.')
    try:
        import sherpa_onnx
    except ImportError:
        raise TranscriptionUnavailable('Transcription runtime is not installed.') from None
    recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine(
        preprocessor=str(model_dir / 'preprocess.onnx'),
        encoder=str(model_dir / 'encode.int8.onnx'),
        uncached_decoder=str(model_dir / 'uncached_decode.int8.onnx'),
        cached_decoder=str(model_dir / 'cached_decode.int8.onnx'),
        tokens=str(model_dir / 'tokens.txt'),
        num_threads=threads,
        provider=device,
    )

    def decode(samples):
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        recognizer.decode_stream(stream)
        return stream.result.text

    return decode


PROVIDERS = {'moonshine': moonshine}

_lock = threading.Lock()  # One decode at a time keeps CPU use bounded.
_loaded = {}  # configuration -> decode; the model stays resident after first use.


def load():
    """Load the configured model now (it otherwise loads on first use)."""
    loader = PROVIDERS.get(settings.TRANSCRIBE_PROVIDER)
    if loader is None:
        raise TranscriptionUnavailable('Transcription is not configured.')
    key = (settings.TRANSCRIBE_PROVIDER, settings.TRANSCRIBE_MODEL_DIR,
           settings.TRANSCRIBE_THREADS, settings.TRANSCRIBE_DEVICE)
    with _lock:
        if key not in _loaded:
            _loaded[key] = loader(*key[1:])
        return _loaded[key]


def transcribe_samples(samples):
    """Text for one speech segment of 16 kHz mono float samples in [-1, 1]."""
    if len(samples) > MAX_SECONDS * SAMPLE_RATE:
        raise ValueError(f'Audio must be at most {MAX_SECONDS} seconds.')
    decode = load()
    with _lock:
        return decode(samples).strip()


def transcribe(pcm):
    """Text for one speech segment of 16 kHz mono signed 16-bit little-endian PCM."""
    if len(pcm) % 2:
        raise ValueError('Audio must be whole 16-bit samples.')
    return transcribe_samples([sample / 32768 for sample in array.array('h', pcm)])
