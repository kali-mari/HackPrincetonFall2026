"""Delete generated speech files not used recently; cached phrases refresh on use."""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Delete generated audio in MEDIA_ROOT/audio older than --hours (default 24).'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=float, default=24)

    def handle(self, *args, hours, **options):
        if hours < 0:
            raise CommandError('--hours must not be negative.')
        cutoff = time.time() - hours * 3600
        removed = 0
        directory = settings.MEDIA_ROOT / 'audio'
        for pattern in ('*.mp3', '*.tmp'):
            for path in directory.glob(pattern):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
        self.stdout.write(f'Removed {removed} audio file(s).')
