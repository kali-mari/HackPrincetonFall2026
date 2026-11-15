"""Explicit patient setup validation shared by views and model validation."""

from .validation import (
    InvalidRequest, validate_fields, validate_integer, validate_string, validate_timezone,
)

PATIENT_FIELDS = {'display_name', 'timezone', 'language', 'preferences'}
FAVORITE_GROUPS = {'foods', 'drinks', 'activities'}
# Caregiver-confirmed facts the word bank's topics can answer from (wordbank.json profile_key).
ABOUT_GROUPS = {'classes', 'interests', 'people'}
MAX_VOCABULARY = 50


def validate_items(items, label, max_items):
    """Trimmed, single-line, printable, case-insensitively unique items of at most 60 characters."""
    if not isinstance(items, list) or len(items) > max_items:
        raise InvalidRequest(f'Each {label} list must contain at most {max_items} items.')
    cleaned = [validate_string(item, f'{label} item', max_length=60) for item in items]
    if any(not item.isprintable() for item in cleaned):
        raise InvalidRequest(f'{label.capitalize()} items must be single-line printable text.')
    if len({item.casefold() for item in cleaned}) != len(cleaned):
        raise InvalidRequest(f'{label.capitalize()} items must be unique within each list.')
    return cleaned


def validate_groups(value, groups, label):
    validate_fields(value, allowed=groups)
    return {group: validate_items(items, label, 10) for group, items in value.items()}


def validate_favorites(value):
    return validate_groups(value, FAVORITE_GROUPS, 'favorite')


def validate_preferences(value):
    required = {'scan_interval_ms', 'input_modes', 'default_activity'}
    validate_fields(value, allowed=required | {'voice_id', 'favorites', 'about', 'vocabulary'}, required=required)
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
    if 'favorites' in value:
        result['favorites'] = validate_favorites(value['favorites'])
    if 'about' in value:
        result['about'] = validate_groups(value['about'], ABOUT_GROUPS, 'about')
    if 'vocabulary' in value:
        result['vocabulary'] = validate_items(value['vocabulary'], 'vocabulary', MAX_VOCABULARY)
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
