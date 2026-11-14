"""Patient serialization and scoped keyset cursors; no auth or extra service layer."""

from django.core import signing

from .validation import InvalidRequest, validate_fields, validate_string, validate_uuid

CURSOR_SALT = 'aac.profile-patients.v1'


def profile_json(profile):
    result = {
        'id': str(profile.pk), 'role': profile.role, 'display_name': profile.display_name,
        'created_at': profile.created_at.isoformat(), 'updated_at': profile.updated_at.isoformat(),
    }
    if profile.role == 'patient':
        result.update(timezone=profile.timezone, language=profile.language, preferences=profile.preferences)
    return result


def patient_cursor(caregiver_id, after_id):
    return signing.dumps({
        'caregiver': str(caregiver_id), 'after': str(after_id), 'order': 'id', 'version': 1,
    }, salt=CURSOR_SALT)


def read_patient_cursor(query, caregiver_id):
    values = query.getlist('cursor')
    if not values:
        return None
    if len(values) != 1:
        raise InvalidRequest('Supply cursor only once.')
    token = validate_string(values[0], 'cursor', max_length=512, trim=False)
    try:
        payload = signing.loads(token, salt=CURSOR_SALT)
        validate_fields(payload, allowed={'caregiver', 'after', 'order', 'version'},
                        required={'caregiver', 'after', 'order', 'version'})
        if payload['caregiver'] != str(caregiver_id) or payload['order'] != 'id' or type(payload['version']) is not int or payload['version'] != 1:
            raise InvalidRequest('Cursor does not match this patient list.')
        return validate_uuid(payload['after'], 'cursor position')
    except (signing.BadSignature, ValueError, TypeError):
        raise InvalidRequest('Invalid or mismatched cursor.') from None
