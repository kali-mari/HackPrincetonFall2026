"""Run listen mode in the terminal: print each phrase and its delay until Ctrl-C."""

import threading
import time

from django.core.management.base import BaseCommand, CommandError

from aac.listen import Listener
from aac.transcription import TranscriptionUnavailable


class Command(BaseCommand):
    help = ('Record from LISTEN_DEVICE (or --device) and print each phrase with how long '
            'after it ended the text was ready. Ctrl-C stops.')

    def add_arguments(self, parser):
        parser.add_argument('--device', help='ALSA device or file:<path>; overrides LISTEN_DEVICE')

    def handle(self, *args, **options):
        if options['device']:
            from django.conf import settings
            settings.LISTEN_DEVICE = options['device']
        ended = threading.Event()
        started = time.monotonic()

        def on_text(text, delay):
            self.stdout.write(f'[{time.monotonic() - started:7.1f} s, +{delay:.2f} s] {text}')

        def on_end(error):
            if error:
                self.stderr.write(error)
            ended.set()

        listener = Listener(on_text, on_end)
        try:
            listener.start()
        except TranscriptionUnavailable as error:
            raise CommandError(str(error)) from None
        self.stdout.write('Listening. Ctrl-C stops.')
        started = time.monotonic()
        try:
            ended.wait()
        except KeyboardInterrupt:
            pass
        finally:
            listener.stop()
