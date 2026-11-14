"""SQLite application records; introduce only the current feature's tables."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .profile_validation import validate_patient_setup
from .validation import InvalidRequest, validate_string


class Profile(models.Model):
    class Role(models.TextChoices):
        CAREGIVER = 'caregiver'
        PATIENT = 'patient'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=9, choices=Role.choices)
    display_name = models.CharField(max_length=80)
    timezone = models.CharField(max_length=100, null=True, blank=True)
    language = models.CharField(max_length=35, null=True, blank=True)
    preferences = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(role='caregiver', timezone__isnull=True, language__isnull=True, preferences__isnull=True)
                    | (models.Q(role='patient', timezone__isnull=False, language__isnull=False, language='en', preferences__isnull=False)
                       & ~models.Q(timezone=''))
                ), name='profile_role_setup',
            ),
            models.CheckConstraint(condition=~models.Q(display_name=''), name='profile_nonempty_name'),
        ]

    def clean(self):
        super().clean()
        if not self._state.adding and Profile.objects.filter(pk=self.pk).exclude(role=self.role).exists():
            raise ValidationError('Profile role is immutable.')
        try:
            self.display_name = validate_string(self.display_name, 'display_name', max_length=80)
            if self.role == self.Role.PATIENT:
                setup = validate_patient_setup({
                    'display_name': self.display_name, 'timezone': self.timezone,
                    'language': self.language, 'preferences': self.preferences,
                })
                for field, value in setup.items():
                    setattr(self, field, value)
            elif self.role == self.Role.CAREGIVER:
                if any(value is not None for value in (self.timezone, self.language, self.preferences)):
                    raise InvalidRequest('Caregivers cannot have patient setup fields.')
        except InvalidRequest as error:
            raise ValidationError(str(error)) from None

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CaregiverPatient(models.Model):
    caregiver = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='patient_links')
    patient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='caregiver_links')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['caregiver', 'patient'], name='unique_caregiver_patient'),
            models.CheckConstraint(condition=~models.Q(caregiver=models.F('patient')), name='different_link_profiles'),
        ]

    def clean(self):
        super().clean()
        if not Profile.objects.filter(pk=self.caregiver_id, role=Profile.Role.CAREGIVER).exists():
            raise ValidationError('A link requires an existing caregiver.')
        if not Profile.objects.filter(pk=self.patient_id, role=Profile.Role.PATIENT).exists():
            raise ValidationError('A link requires an existing patient.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
