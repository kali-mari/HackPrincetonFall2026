"""Idempotent synthetic setup; preserve existing demo edits and history."""

from datetime import datetime, time, timedelta
import json
from pathlib import Path
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aac.history import time_bucket
from aac.models import CaregiverPatient, CommunicationEvent, Profile

CAREGIVER_ID = UUID('11111111-1111-4111-8111-111111111111')
HISTORY_FILE = Path(settings.BASE_DIR) / 'seed' / 'demo_history.json'


class Command(BaseCommand):
    help = 'Create a stable synthetic caregiver, configured legacy patient, link and spoken history.'

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.LEGACY_DEMO_PATIENT_ID == CAREGIVER_ID:
            raise CommandError('Demo caregiver and patient IDs must differ.')
        caregiver, _ = Profile.objects.get_or_create(
            pk=CAREGIVER_ID,
            defaults={'role': Profile.Role.CAREGIVER, 'display_name': 'Demo caregiver'},
        )
        if caregiver.role != Profile.Role.CAREGIVER:
            raise CommandError('Demo caregiver ID is occupied by a different role.')
        patient, _ = Profile.objects.get_or_create(
            pk=settings.LEGACY_DEMO_PATIENT_ID,
            defaults={
                'role': Profile.Role.PATIENT, 'display_name': 'Demo patient',
                'timezone': 'America/New_York', 'language': 'en',
                'preferences': {
                    'scan_interval_ms': 1500, 'input_modes': ['button', 'keyboard'],
                    'default_activity': 'play',
                },
            },
        )
        if patient.role != Profile.Role.PATIENT:
            raise CommandError('Legacy demo patient ID is occupied by a different role.')
        CaregiverPatient.objects.get_or_create(caregiver=caregiver, patient=patient)
        self.seed_history(patient)
        self.stdout.write(self.style.SUCCESS('Synthetic demo setup is ready (existing edits preserved).'))

    def seed_history(self, patient):
        # IDs derive from the patient and row number: reruns only restore missing seed rows.
        today = datetime.now(ZoneInfo(patient.timezone)).date()
        rows = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))['spoken']
        for number, row in enumerate(rows):
            event_id = uuid5(patient.pk, f'demo-spoken-{number}')
            if CommunicationEvent.objects.filter(pk=event_id).exists():
                continue
            occurred_at = datetime.combine(
                today - timedelta(days=row['days_ago']), time(row['hour']), ZoneInfo(patient.timezone),
            )
            CommunicationEvent.objects.create(
                id=event_id, utterance_id=uuid5(patient.pk, f'demo-utterance-{number}'), patient=patient,
                kind='spoken', text=row['text'], occurred_at=occurred_at, activity=row['activity'],
                time_bucket=time_bucket(occurred_at, patient.timezone), input_source='button',
            )
