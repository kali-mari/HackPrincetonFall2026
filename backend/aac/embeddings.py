"""Provider-neutral sentence embeddings on the device, for conversation suggestions.

A provider is a loader (model_dir, threads) -> embed, where embed takes a list of
texts and returns one unit-length vector (list of floats) per text, so a dot
product is the cosine similarity. Select it with EMBED_PROVIDER; blank turns
embeddings off and callers use keyword matching. Texts stay in memory: nothing here
writes, logs or sends them anywhere.
"""

import threading

from django.conf import settings

MODEL_FILES = {'minilm': ('onnx/model_qint8_arm64.onnx', 'tokenizer.json')}
MAX_TOKENS = 128


class EmbeddingUnavailable(Exception):
    """The model or its runtime is missing; safe to show, never includes text."""


def minilm(model_dir, threads):
    """sentence-transformers/all-MiniLM-L6-v2 (int8 ARM build) through ONNX Runtime, mean pooled."""
    model_file, tokenizer_file = (model_dir / name for name in MODEL_FILES['minilm'])
    if not model_file.is_file() or not tokenizer_file.is_file():
        raise EmbeddingUnavailable('Embedding model is not installed.')
    try:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:
        raise EmbeddingUnavailable('Embedding runtime is not installed.') from None
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_file), options, providers=['CPUExecutionProvider'])
    names = {i.name for i in session.get_inputs()}
    tokenizer = Tokenizer.from_file(str(tokenizer_file))
    tokenizer.enable_truncation(MAX_TOKENS)
    tokenizer.enable_padding()

    def embed(texts):
        encoded = tokenizer.encode_batch(list(texts))
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {'input_ids': ids, 'attention_mask': mask}
        if 'token_type_ids' in names:
            feed['token_type_ids'] = np.zeros_like(ids)
        hidden = session.run(None, feed)[0]
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(1) / np.clip(weights.sum(1), 1e-9, None)
        pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
        return pooled.tolist()

    return embed


PROVIDERS = {'minilm': minilm}

_lock = threading.Lock()  # One inference at a time keeps CPU use bounded next to transcription.
_loaded = {}


def enabled():
    return settings.EMBED_PROVIDER in PROVIDERS


def embed(texts):
    """Unit vectors for texts. Loads the model on first use; raises EmbeddingUnavailable."""
    loader = PROVIDERS.get(settings.EMBED_PROVIDER)
    if loader is None:
        raise EmbeddingUnavailable('Embeddings are not configured.')
    key = (settings.EMBED_PROVIDER, settings.EMBED_MODEL_DIR, settings.EMBED_THREADS)
    with _lock:
        if key not in _loaded:
            _loaded[key] = loader(key[1], key[2])
        return _loaded[key](texts)
