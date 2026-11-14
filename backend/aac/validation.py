"""Small explicit validators for feature views, not a schema framework.

These functions validate values only. Record existence, ownership, revisions,
opaque cursors and feature-specific rules belong to their implementing slice.
"""

from datetime import datetime, timezone
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class InvalidRequest(ValueError):
    """Safe validation message suitable for the existing JSON 400 envelope."""


def validate_fields(payload, *, allowed, required=(), require_nonempty=False):
    if not isinstance(payload, dict):
        raise InvalidRequest('JSON body must be an object.')
    if payload.keys() - set(allowed):
        raise InvalidRequest('Request contains unknown fields.')
    if set(required) - payload.keys():
        raise InvalidRequest('Request is missing required fields.')
    if require_nonempty and not payload:
        raise InvalidRequest('Request must contain at least one field.')
    return payload


def validate_string(value, field, *, max_length, trim=True):
    # Check the original length before normalization; whitespace is not a way
    # around the input bound. Preserve readable Unicode, not just ASCII.
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequest(f'{field} must be a nonempty string.')
    if len(value) > max_length:
        raise InvalidRequest(f'{field} exceeds the maximum length of {max_length}.')
    return value.strip() if trim else value


def validate_uuid(value, field):
    # UUID() alone also accepts braces, URNs and unhyphenated hex; the wire
    # contract uses the standard hyphenated UUID format, not those alternatives.
    if not isinstance(value, str) or not re.fullmatch(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        value,
    ):
        raise InvalidRequest(f'{field} must be a UUID string.')
    return UUID(value)


def validate_timestamp(value, field):
    # datetime.fromisoformat alone accepts dates, spaces and offset-free values
    # outside the date-time wire format. Require seconds and an explicit offset.
    if not isinstance(value, str) or not re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}'
        r'(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})', value,
    ):
        raise InvalidRequest(f'{field} must be an ISO timestamp with a timezone offset.')
    # fromisoformat normalizes offsets such as +00:60; reject them explicitly.
    if value[-1] not in 'Zz' and (
        int(value[-5:-3]) > 23 or int(value[-2:]) > 59
    ):
        raise InvalidRequest(f'{field} has an invalid timezone offset.')
    try:
        parsed = datetime.fromisoformat(value.upper())
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InvalidRequest(f'{field} must be a valid ISO timestamp.') from None


def validate_timezone(value, field='timezone'):
    name = validate_string(value, field, max_length=100, trim=False)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidRequest(f'{field} must be a valid IANA timezone.') from None


def validate_integer(value, field, *, minimum, maximum):
    # bool is a subclass of int in Python, but a JSON boolean is not an integer.
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidRequest(f'{field} must be an integer from {minimum} to {maximum}.')
    return value


def query_limit(query):
    """Read a Django QueryDict page limit; cursor/filter checks stay feature-owned."""
    values = query.getlist('limit')
    if not values:
        return 50
    if len(values) != 1 or not re.fullmatch(r'[0-9]+', values[0]):
        raise InvalidRequest('limit must be an integer from 1 to 100.')
    try:
        value = int(values[0])
    except ValueError:  # Includes Python's oversized integer-string guard.
        raise InvalidRequest('limit must be an integer from 1 to 100.') from None
    return validate_integer(value, 'limit', minimum=1, maximum=100)
