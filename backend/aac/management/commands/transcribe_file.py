"""Transcribe a WAV file with the configured provider, to check a device setup."""

import time
import wave

from django.core.management.base import BaseCommand, CommandError

from aac.transcription import SAMPLE_RATE, TranscriptionUnavailable, transcribe


class Command(BaseCommand):
    help = 'Transcribe a 16 kHz mono 16-bit WAV file (at most 30 s) and print the text and timing.'

    def add_arguments(self, parser):
        parser.add_argument('wav')

    def handle(self, *args, wav, **options):
        try:
            with wave.open(wav, 'rb') as audio:
                if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                    raise CommandError(
                        'Convert first: ffmpeg -i in.wav -ac 1 -ar 16000 -c:a pcm_s16le out.wav'
                    )
                pcm = audio.readframes(audio.getnframes())
        except (OSError, wave.Error, EOFError):
            raise CommandError('Could not read that WAV file.') from None
        seconds = len(pcm) / 2 / SAMPLE_RATE
        try:
            transcribe(pcm[:SAMPLE_RATE * 2])  # Load the model and warm up, untimed.
            started = time.monotonic()
            text = transcribe(pcm)
        except (TranscriptionUnavailable, ValueError) as error:
            raise CommandError(str(error)) from None
        elapsed = time.monotonic() - started
        self.stdout.write(text)
        self.stdout.write(f'{seconds:.1f} s of audio decoded in {elapsed:.2f} s.')
