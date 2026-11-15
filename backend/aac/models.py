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
    # Validated patient settings, including explicit categorized favorite items.
    # Kept in SQLite with the profile; spoken/selected choices remain events.
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


class PredictionRecord(models.Model):
    """Six phrases shown to a patient; only what event attribution needs."""

    class Source(models.TextChoices):
        JEV = 'jev'
        AI = 'ai'
        HISTORY = 'history'
        DEFAULT = 'default'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='predictions')
    activity = models.CharField(max_length=100, null=True, blank=True)
    time_bucket = models.CharField(max_length=9)
    phrases = models.JSONField()
    source = models.CharField(max_length=7, choices=Source.choices)
    artifact_version = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['patient', 'created_at'], name='prediction_patient_created')]


class CommunicationEvent(models.Model):
    """An explicit patient action. The primary key is the client's retry key."""

    class Kind(models.TextChoices):
        SELECTION = 'selection'
        SPOKEN = 'spoken'
        FEEDBACK = 'feedback'

    id = models.UUIDField(primary_key=True, editable=False)
    utterance_id = models.UUIDField()
    patient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=9, choices=Kind.choices)
    text = models.CharField(max_length=500)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    activity = models.CharField(max_length=100, null=True, blank=True)
    time_bucket = models.CharField(max_length=9)
    # Null only for legacy /api/log entries, which do not report an input source.
    input_source = models.CharField(max_length=8, null=True, blank=True)
    # RESTRICT still lets a patient deletion cascade through both tables.
    prediction = models.ForeignKey(
        PredictionRecord, on_delete=models.RESTRICT, null=True, blank=True, related_name='events',
    )
    candidate_index = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=8, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['patient', 'occurred_at', 'id'], name='event_patient_time')]
        constraints = [
            models.CheckConstraint(condition=models.Q(kind__in=['selection', 'spoken', 'feedback']), name='event_kind'),
            models.CheckConstraint(
                condition=models.Q(input_source__isnull=True) | models.Q(input_source__in=['button', 'keyboard']),
                name='event_input_source',
            ),
            models.CheckConstraint(
                condition=(models.Q(prediction__isnull=True, candidate_index__isnull=True)
                           | models.Q(prediction__isnull=False, candidate_index__lte=5)),
                name='event_prediction_pair',
            ),
            models.CheckConstraint(
                condition=(models.Q(kind='feedback', outcome__in=['accepted', 'rejected'], prediction__isnull=False)
                           | (~models.Q(kind='feedback') & models.Q(outcome__isnull=True))),
                name='event_feedback_outcome',
            ),
            models.CheckConstraint(condition=~models.Q(text=''), name='event_nonempty_text'),
            models.UniqueConstraint(
                fields=['utterance_id'], condition=models.Q(kind='spoken'), name='one_spoken_per_utterance',
            ),
        ]
