"""The local word bank: generic topics and phrases for conversation suggestions.

wordbank.json holds only curated, generic vocabulary: no patient names, preferences,
transcripts or history. Patient-specific answers come from the profile through each
topic's profile_key at suggestion time, never from this file.
"""

import functools
import json
import re
from pathlib import Path

from .profile_validation import ABOUT_GROUPS as ABOUT_KEYS, FAVORITE_GROUPS

BANK_PATH = Path(__file__).with_name('wordbank.json')
ID_PATTERN = re.compile(r'^[a-z0-9]+(?:[-_][a-z0-9]+)*$')
# Starter intents from docs/label-vocabulary.md; roles are symbols.ts word types plus whole phrases.
INTENTS = {'request', 'refusal', 'greeting', 'feeling', 'question', 'response', 'unknown'}
ROLES = {'person', 'verb', 'describing', 'noun', 'social', 'negation', 'phrase'}
PHRASE_COUNT = 6
MIN_TOPIC_PHRASES = 4  # Leaves room for meta choices such as "Something else".
MAX_TEXT = 60


class InvalidWordBank(ValueError):
    """The bank file breaks a rule below; the message names the entry."""


def _check(condition, message):
    if not condition:
        raise InvalidWordBank(message)


def _text(value, where):
    _check(isinstance(value, str) and value.strip() == value and value, f'{where} must be trimmed, nonempty text.')
    _check(len(value) <= MAX_TEXT and value.isprintable(), f'{where} must be one printable line of at most {MAX_TEXT} characters.')
    return value


def _fields(entry, required, where):
    _check(isinstance(entry, dict), f'{where} must be an object.')
    _check(set(entry) == required, f'{where} must have exactly the fields {sorted(required)}.')


def _profile_key(value, where):
    if value is None:
        return None
    group, _, name = value.partition('.') if isinstance(value, str) else ('', '', '')
    allowed = FAVORITE_GROUPS if group == 'favorites' else ABOUT_KEYS if group == 'about' else set()
    _check(name in allowed, f'{where} profile_key must be favorites.<{"|".join(sorted(FAVORITE_GROUPS))}>, '
           f'about.<{"|".join(sorted(ABOUT_KEYS))}> or null.')
    return value


def validate(data):
    """Return the bank as {'topics': {id: topic}, 'phrases': {id: phrase}, 'fallback': [ids]}."""
    _fields(data, {'version', 'fallback', 'topics', 'phrases'}, 'The word bank')
    _check(data['version'] == 1, 'Only word bank version 1 is supported.')
    _check(isinstance(data['topics'], list) and data['topics'], 'topics must be a nonempty list.')
    _check(isinstance(data['phrases'], list) and data['phrases'], 'phrases must be a nonempty list.')

    topics = {}
    for index, topic in enumerate(data['topics']):
        where = f'topics[{index}]'
        _fields(topic, {'id', 'label', 'profile_key', 'template', 'examples'}, where)
        _check(isinstance(topic['id'], str) and ID_PATTERN.match(topic['id']), f'{where} id must be lowercase words.')
        where = f'topic {topic["id"]!r}'
        _check(topic['id'] not in topics, f'{where} is defined twice.')
        _text(topic['label'], f'{where} label')
        _profile_key(topic['profile_key'], where)
        _check(_text(topic['template'], f'{where} template').count('{}') == 1, f'{where} template needs one {{}}.')
        examples = topic['examples']
        _check(isinstance(examples, list) and len(examples) >= 2, f'{where} needs at least 2 examples.')
        for example in examples:
            _text(example, f'{where} example')
        _check(len({e.casefold() for e in examples}) == len(examples), f'{where} repeats an example.')
        topics[topic['id']] = topic

    phrases, texts = {}, set()
    for index, phrase in enumerate(data['phrases']):
        where = f'phrases[{index}]'
        _fields(phrase, {'id', 'text', 'topics', 'intent', 'role', 'symbol'}, where)
        _check(isinstance(phrase['id'], str) and ID_PATTERN.match(phrase['id']), f'{where} id must be lowercase words.')
        where = f'phrase {phrase["id"]!r}'
        _check(phrase['id'] not in phrases, f'{where} is defined twice.')
        key = _text(phrase['text'], f'{where} text').casefold()
        _check(key not in texts, f'{where} repeats the text of another phrase.')
        texts.add(key)
        _check(isinstance(phrase['topics'], list) and all(t in topics for t in phrase['topics'])
               and len(set(phrase['topics'])) == len(phrase['topics']), f'{where} lists an unknown or repeated topic.')
        _check(phrase['intent'] in INTENTS, f'{where} intent must be one of {sorted(INTENTS)}.')
        _check(phrase['role'] in ROLES, f'{where} role must be one of {sorted(ROLES)}.')
        symbol = phrase['symbol']
        _check(symbol is None or (isinstance(symbol, str) and ID_PATTERN.match(symbol)), f'{where} symbol must be a symbol id or null.')
        phrases[phrase['id']] = phrase

    for topic_id in topics:
        count = sum(topic_id in phrase['topics'] for phrase in phrases.values())
        _check(count >= MIN_TOPIC_PHRASES, f'topic {topic_id!r} needs at least {MIN_TOPIC_PHRASES} phrases, has {count}.')

    fallback = data['fallback']
    _check(isinstance(fallback, list) and len(fallback) == PHRASE_COUNT and len(set(fallback)) == PHRASE_COUNT
           and all(phrase_id in phrases for phrase_id in fallback),
           f'fallback must list {PHRASE_COUNT} distinct phrase ids.')
    return {'topics': topics, 'phrases': phrases, 'fallback': list(fallback)}


@functools.cache
def load(path=BANK_PATH):
    """The validated bank, read once per process."""
    with open(path, encoding='utf-8') as file:
        return validate(json.load(file))


def topic_phrases(bank, topic_id):
    """Phrases tagged with the topic, in file order."""
    return [phrase for phrase in bank['phrases'].values() if topic_id in phrase['topics']]
