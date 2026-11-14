"""Download the selected transcription provider's model into TRANSCRIBE_MODEL_DIR."""

from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from aac.transcription import MODEL_ARCHIVES


class Command(BaseCommand):
    help = 'Download the model for TRANSCRIBE_PROVIDER into TRANSCRIBE_MODEL_DIR.'

    def handle(self, *args, **options):
        if settings.TRANSCRIBE_PROVIDER not in MODEL_ARCHIVES:
            raise CommandError('Set TRANSCRIBE_PROVIDER first.')
        url, files = MODEL_ARCHIVES[settings.TRANSCRIBE_PROVIDER]
        directory = settings.TRANSCRIBE_MODEL_DIR
        if all((directory / name).is_file() for name in files):
            self.stdout.write(f'Model already present in {directory}.')
            return
        directory.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'model.tar.bz2'
            urllib.request.urlretrieve(url, archive)
            with tarfile.open(archive) as tar:
                folder = url.rsplit('/', 1)[1].removesuffix('.tar.bz2')
                for name in files:
                    (directory / name).write_bytes(tar.extractfile(f'{folder}/{name}').read())
        self.stdout.write(f'Model saved to {directory}.')
