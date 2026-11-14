"""Idempotent synthetic setup; preserve existing demo edits and history."""

from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aac.models import CaregiverPatient, Profile

CAREGIVER_ID = UUID('11111111-1111-4111-8111-111111111111')


class Command(BaseCommand):
    help = 'Create a stable synthetic caregiver, configured legacy patient and link.'

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
        self.stdout.write(self.style.SUCCESS('Synthetic demo setup is ready (existing edits preserved).'))
