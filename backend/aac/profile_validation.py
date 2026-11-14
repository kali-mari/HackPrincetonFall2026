"""Explicit patient setup validation shared by views and model validation."""

from .validation import (
    InvalidRequest, validate_fields, validate_integer, validate_string, validate_timezone,
)

PATIENT_FIELDS = {'display_name', 'timezone', 'language', 'preferences'}


def validate_preferences(value):
    required = {'scan_interval_ms', 'input_modes', 'default_activity'}
    validate_fields(value, allowed=required | {'voice_id'}, required=required)
    modes = value['input_modes']
    if (
        not isinstance(modes, list) or not modes
        or any(not isinstance(mode, str) or mode not in {'button', 'keyboard'} for mode in modes)
        or len(set(modes)) != len(modes)
    ):
        raise InvalidRequest('input_modes must contain unique button/keyboard values.')
    result = {
        'scan_interval_ms': validate_integer(
            value['scan_interval_ms'], 'scan_interval_ms', minimum=300, maximum=10000,
        ),
        'input_modes': modes.copy(),
        'default_activity': validate_string(value['default_activity'], 'default_activity', max_length=100),
    }
    if 'voice_id' in value:
        result['voice_id'] = validate_string(value['voice_id'], 'voice_id', max_length=100)
    return result


def validate_patient_setup(payload, *, partial=False):
    validate_fields(
        payload, allowed=PATIENT_FIELDS,
        required=() if partial else PATIENT_FIELDS, require_nonempty=True,
    )
    result = {}
    if 'display_name' in payload:
        result['display_name'] = validate_string(payload['display_name'], 'display_name', max_length=80)
    if 'timezone' in payload:
        result['timezone'] = validate_timezone(payload['timezone']).key
    if 'language' in payload:
        if payload['language'] != 'en':
            raise InvalidRequest('language must be en for the current demo.')
        result['language'] = 'en'
    if 'preferences' in payload:
        result['preferences'] = validate_preferences(payload['preferences'])
    return result
