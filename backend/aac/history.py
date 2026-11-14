"""Communication event validation, time buckets, serialization and history cursors."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.core import signing

from .validation import (
    InvalidRequest, validate_fields, validate_integer, validate_string, validate_timestamp, validate_uuid,
)

CURSOR_SALT = 'aac.patient-events.v1'
EVENT_FIELDS = {
    'event_id', 'utterance_id', 'patient_id', 'kind', 'text', 'timestamp',
    'activity', 'input_source', 'prediction_id', 'candidate_index',
}
REQUIRED_EVENT_FIELDS = {'event_id', 'utterance_id', 'patient_id', 'kind', 'text', 'timestamp', 'input_source'}
# Patient-local [start, end) hours. Phase 4 ranking matches on these same names.
TIME_BUCKETS = (
    ('night', 0, 5), ('morning', 5, 11), ('midday', 11, 14),
    ('afternoon', 14, 17), ('evening', 17, 21), ('night', 21, 24),
)


class Conflict(Exception):
    """Safe 409 message: changed retry, second spoken event or cross-patient utterance."""


def time_bucket(moment, timezone):
    hour = moment.astimezone(ZoneInfo(timezone)).hour
    return next(name for name, start, end in TIME_BUCKETS if start <= hour < end)


def validate_event(payload):
    """Return normalized event fields; ownership/existence checks need the database."""
    kind = payload.get('kind') if isinstance(payload, dict) else None
    if kind not in ('selection', 'spoken', 'feedback'):
        raise InvalidRequest('kind must be selection, spoken or feedback.')
    feedback = kind == 'feedback'
    validate_fields(
        payload,
        allowed=EVENT_FIELDS | ({'outcome'} if feedback else set()),
        required=REQUIRED_EVENT_FIELDS | ({'outcome', 'prediction_id', 'candidate_index'} if feedback else set()),
    )
    if ('prediction_id' in payload) != ('candidate_index' in payload):
        raise InvalidRequest('Supply prediction_id and candidate_index together.')
    if payload['input_source'] not in ('button', 'keyboard'):
        raise InvalidRequest('input_source must be button or keyboard.')
    if feedback and payload['outcome'] not in ('accepted', 'rejected'):
        raise InvalidRequest('outcome must be accepted or rejected.')
    attributed = 'prediction_id' in payload
    return {
        'id': validate_uuid(payload['event_id'], 'event_id'),
        'utterance_id': validate_uuid(payload['utterance_id'], 'utterance_id'),
        'patient_id': validate_uuid(payload['patient_id'], 'patient_id'),
        'kind': kind,
        'text': validate_string(payload['text'], 'text', max_length=500),
        'occurred_at': validate_timestamp(payload['timestamp'], 'timestamp'),
        'activity': validate_string(payload['activity'], 'activity', max_length=100) if 'activity' in payload else None,
        'input_source': payload['input_source'],
        'prediction_id': validate_uuid(payload['prediction_id'], 'prediction_id') if attributed else None,
        'candidate_index': (
            validate_integer(payload['candidate_index'], 'candidate_index', minimum=0, maximum=5) if attributed else None
        ),
        'outcome': payload['outcome'] if feedback else None,
    }


def same_event(event, data):
    """True when a stored event matches a normalized retry exactly."""
    return all(getattr(event, field) == data[field] for field in (
        'utterance_id', 'patient_id', 'kind', 'text', 'occurred_at', 'activity',
        'input_source', 'prediction_id', 'candidate_index', 'outcome',
    ))


def event_json(event):
    return {
        'event_id': str(event.pk), 'utterance_id': str(event.utterance_id),
        'patient_id': str(event.patient_id), 'kind': event.kind, 'text': event.text,
        'timestamp': event.occurred_at.isoformat(), 'received_at': event.received_at.isoformat(),
        'activity': event.activity, 'input_source': event.input_source,
        'prediction_id': str(event.prediction_id) if event.prediction_id else None,
        'candidate_index': event.candidate_index, 'outcome': event.outcome,
    }


def event_cursor(patient_id, event):
    return signing.dumps({
        'patient': str(patient_id), 'timestamp': event.occurred_at.isoformat(),
        'event': str(event.pk), 'order': 'timestamp_desc', 'version': 1,
    }, salt=CURSOR_SALT)


def read_event_cursor(query, patient_id):
    """Return (timestamp, event_id) of the last event on the previous page, or None."""
    values = query.getlist('cursor')
    if not values:
        return None
    if len(values) != 1:
        raise InvalidRequest('Supply cursor only once.')
    token = validate_string(values[0], 'cursor', max_length=512, trim=False)
    try:
        payload = signing.loads(token, salt=CURSOR_SALT)
        validate_fields(payload, allowed={'patient', 'timestamp', 'event', 'order', 'version'},
                        required={'patient', 'timestamp', 'event', 'order', 'version'})
        if (payload['patient'] != str(patient_id) or payload['order'] != 'timestamp_desc'
                or type(payload['version']) is not int or payload['version'] != 1):
            raise InvalidRequest('Cursor does not match this event list.')
        return datetime.fromisoformat(payload['timestamp']), validate_uuid(payload['event'], 'cursor position')
    except (signing.BadSignature, ValueError, TypeError):
        raise InvalidRequest('Invalid or mismatched cursor.') from None
