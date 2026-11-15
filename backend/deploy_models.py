"""Explicit model setup over verified TLS; runtime never downloads models.

MiniLM is revision-pinned. The manifest detects truncated/changed local files;
its hashes are recorded at download time, not independent publisher signatures.
"""

import hashlib
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import shutil

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.conf import settings
from aac.listen import VAD_URL
from aac.transcription import MODEL_ARCHIVES

MINILM_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
MINILM_URL = f'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{MINILM_REVISION}'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, target):
    with urlopen(url, timeout=60) as response, target.open('wb') as output:
        shutil.copyfileobj(response, output)


def main():
    root = settings.TRANSCRIBE_MODEL_DIR.parent
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get('minilm_revision') == MINILM_REVISION
                and manifest.get('files')
                and all((root / name).is_file() and sha256(root / name) == digest
                        for name, digest in manifest['files'].items())):
            print('All models verified; no download needed.')
            return
    url, names = MODEL_ARCHIVES['moonshine']
    with TemporaryDirectory(prefix='.download-', dir=root) as directory:
        staging = Path(directory)
        archive = staging / 'moonshine.tar.bz2'
        print('Downloading Moonshine, Silero VAD, and ARM64 MiniLM (setup only).', flush=True)
        download(url, archive)
        folder = url.rsplit('/', 1)[1].removesuffix('.tar.bz2')
        files = {}
        with tarfile.open(archive) as tar:
            for name in names:
                target = staging / name
                with tar.extractfile(f'{folder}/{name}') as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                files[settings.TRANSCRIBE_MODEL_DIR / name] = target
        download(VAD_URL, staging / 'silero_vad.onnx')
        files[settings.LISTEN_VAD_MODEL] = staging / 'silero_vad.onnx'
        for index, name in enumerate(('onnx/model_qint8_arm64.onnx', 'tokenizer.json')):
            target = staging / f'minilm-{index}'
            download(f'{MINILM_URL}/{name}', target)
            files[settings.EMBED_MODEL_DIR / name] = target
        manifest = {'minilm_revision': MINILM_REVISION, 'files': {}}
        for destination, source in files.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            manifest['files'][str(destination.relative_to(root))] = sha256(source)
            source.replace(destination)
        temporary_manifest = staging / 'manifest.json'
        temporary_manifest.write_text(json.dumps(manifest, indent=2) + '\n')
        temporary_manifest.replace(manifest_path)
    print('Models installed; runtime can run without network access.')


if __name__ == '__main__':
    main()
