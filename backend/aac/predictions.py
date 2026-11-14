"""Deterministic patient-scoped phrase ranking from confirmed spoken history."""

from .validation import InvalidRequest, validate_fields, validate_string, validate_timestamp

PHRASE_COUNT = 6
HALF_LIFE_DAYS = 7
# Bounds work per request; older speech has negligible weight after a few half-lives.
HISTORY_LIMIT = 1000
# Fill order when history is empty or sparse. Must hold at least six unique phrases.
DEFAULT_PHRASES = (
    'I want water', 'More please', 'I am hungry', 'All done', 'Help me', 'Thank you',
    'Yes', 'No', 'I need a break', 'Bathroom please',
)


def validate_prediction_request(payload, fields):
    """Return (time, activity); `recent` is checked, never stored, and only sent to the optional AI provider."""
    validate_fields(payload, allowed=fields, required=fields)
    recent = payload['recent']
    if not isinstance(recent, list) or len(recent) > 20:
        raise InvalidRequest('recent must be a list of at most 20 phrases.')
    for item in recent:
        validate_string(item, 'recent item', max_length=500)
    return (
        validate_timestamp(payload['time'], 'time'),
        validate_string(payload['activity'], 'activity', max_length=100),
    )


def recent_spoken(patient):
    """Newest-first confirmed speech; selections and feedback are not evidence."""
    return list(
        patient.events.filter(kind='spoken')
        .only('id', 'text', 'activity', 'time_bucket', 'occurred_at')
        .order_by('-occurred_at', '-id')[:HISTORY_LIMIT]
    )


def normalize(text):
    return text.strip().casefold()


def weight(occurred_at, now):
    age_days = max(0.0, (now - occurred_at).total_seconds() / 86400)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def rank(events, now):
    """Phrases by decayed count; ties by most recent use, then normalized text.

    Each spoken event is one completed utterance, so each counts once. The
    displayed text is the most recent spelling of a case-insensitive phrase.
    """
    totals = {}
    for event in events:  # newest first, so the first sighting is the latest
        key = normalize(event.text)
        if key not in totals:
            totals[key] = [0.0, event.occurred_at, event.text.strip()]
        totals[key][0] += weight(event.occurred_at, now)
    ordered = sorted(totals.items(), key=lambda item: (-item[1][0], -item[1][1].timestamp(), item[0]))
    return [text for _, (_, _, text) in ordered]


def predict_phrases(events, activity, bucket, now):
    """Return (six phrases, source). Narrow context first, then broader, then defaults."""
    activity = normalize(activity)
    same_activity = [event for event in events if event.activity and normalize(event.activity) == activity]
    tiers = (
        [event for event in same_activity if event.time_bucket == bucket],
        same_activity,
        [event for event in events if event.time_bucket == bucket],
        events,
    )
    phrases, seen = [], set()

    def take(candidates):
        for text in candidates:
            if len(phrases) == PHRASE_COUNT:
                return
            if normalize(text) not in seen:
                seen.add(normalize(text))
                phrases.append(text)

    for tier in tiers:
        take(rank(tier, now))
    source = 'history' if phrases else 'default'
    take(DEFAULT_PHRASES)
    return phrases, source
