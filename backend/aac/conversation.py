"""Conversation suggestions: a caregiver's last few lines -> six local answer choices.

Everything here runs on the device. Inputs are the in-memory transcript lines, the
patient's stored preferences (caregiver-confirmed favorites, `about` facts and
vocabulary) and recent spoken phrases; outputs are word-bank phrases, confirmed
facts and options named in the question itself. Nothing is stored, logged or sent
to a hosted service, and nothing is selected or spoken automatically.

The on-device embedding model (aac/embeddings.py) picks the topic and ranks
phrases when it is enabled and answers within PREDICT_TIMEOUT_SECONDS; otherwise
word-bank keywords pick the topic. When the patient's own answer is unknown, the
choices stay generic and include "I don't know" rather than inventing a fact.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import functools
import logging
import re

from django.conf import settings

from . import embeddings, wordbank
from .predictions import PHRASE_COUNT, normalize

log = logging.getLogger(__name__)

LINES = 3  # A follow-up such as "What about juice?" can use the topic of an earlier line.
TOPIC_THRESHOLD = 0.45  # Max cosine over a topic's examples; chosen in the step 1 evaluation.
VOCABULARY_THRESHOLD = 0.45
HISTORY_BOOST, HISTORY_CAP = 0.05, 0.15  # Per recent use of the same phrase, capped.
QUESTION_WORDS = {'what', 'which', 'who', 'whose', 'where', 'when', 'why', 'how'}
YES_NO_STARTS = {'am', 'are', 'is', 'was', 'were', 'do', 'does', 'did', 'can', 'could', 'will', 'would',
                 'should', 'shall', 'have', 'has', 'had', 'may', 'might', 'want', 'need'}
ARTICLES = {'a', 'an', 'the', 'some', 'your', 'my'}
NOT_OPTIONS = {'not', 'something', 'anything', 'else', 'this', 'that', 'it', 'you', 'me', 'them', 'so'}
PARTICLES = {'away', 'out', 'up', 'off', 'down', 'over'}  # "taking away", "going out"

# One worker: a slow model call never piles up threads, and the next call skips the
# model until it finishes.
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='suggest-embed')
_pending = None
_bank_vectors = {}


def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def is_question(text):
    found = words(text)
    return text.rstrip().endswith('?') or bool(found) and (found[0] in QUESTION_WORDS or found[0] in YES_NO_STARTS)


def is_yes_no(text):
    found = words(text)
    return bool(found) and found[0] in YES_NO_STARTS


def or_options(text):
    """["Water", "Juice"] for "Water or juice?"; [] unless the line names exactly two short options."""
    found = words(text)
    if found.count('or') != 1:
        return []
    index = found.index('or')
    before, after = found[:index], found[index + 1:]
    while after and after[0] in ARTICLES:
        after = after[1:]
    if not before or not after or before[-1] in ARTICLES | NOT_OPTIONS or after[0] in NOT_OPTIONS:
        return []
    first, second = before[-1], after[0]
    if len(after) > 1 and after[1] == first and len(before) > 1:  # "plus sign or minus sign"
        first, second = f'{before[-2]} {first}', f'{second} {after[1]}'
    elif len(after) > 1 and after[1] in PARTICLES:
        second = f'{second} {after[1]}'
    if first in PARTICLES and len(before) > 1:  # "go out or stay in"
        first = f'{before[-2]} {first}'
    return [option[:1].upper() + option[1:] for option in (first, second)]


def keyword_topic(bank, text):
    """The topic with the most keyword hits (bank order breaks ties), or None."""
    found, best, hits = set(words(text)), None, 0
    for topic_id, topic in bank['topics'].items():
        count = len(found & set(topic['keywords']))
        if count > hits:
            best, hits = topic_id, count
    return best


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def bank_vectors(bank):
    """Example and phrase vectors for the bank, computed once per process."""
    key = id(bank)
    if key not in _bank_vectors:
        examples = [(topic_id, example) for topic_id, topic in bank['topics'].items() for example in topic['examples']]
        phrases = list(bank['phrases'].values())
        vectors = embeddings.embed([text for _, text in examples] + [phrase['text'] for phrase in phrases])
        _bank_vectors[key] = {
            'examples': [(topic_id, vector) for (topic_id, _), vector in zip(examples, vectors)],
            'phrases': {phrase['id']: vector for phrase, vector in zip(phrases, vectors[len(examples):])},
        }
    return _bank_vectors[key]


@functools.lru_cache(maxsize=8)
def vocabulary_vectors(vocabulary):
    return embeddings.embed(list(vocabulary)) if vocabulary else []


def semantic(bank, lines, vocabulary):
    """Model work for one request, run on the worker thread."""
    return {'bank': bank_vectors(bank), 'lines': embeddings.embed(lines), 'vocabulary': vocabulary_vectors(vocabulary)}


def _warm(vocabulary):
    try:
        semantic(wordbank.load(), ['Hello'], vocabulary)
    except Exception as error:  # Missing model or runtime: keywords still work.
        log.warning('Embedding warm-up failed (%s); using keywords', type(error).__name__)


def warm(preferences=None):
    """Start loading the model and bank vectors in the background; returns at once.

    Cold, this takes about 4.5 s on the UNO Q, longer than the suggestion deadline, so
    listen mode calls it when listening starts. It runs on the suggestion worker:
    questions asked meanwhile use keywords instead of waiting. Returns the future, or
    None when embeddings are off.
    """
    global _pending
    if not embeddings.enabled():
        return None
    if _pending is None or _pending.done():
        _pending = EXECUTOR.submit(_warm, tuple((preferences or {}).get('vocabulary', [])))
    return _pending


def model_results(bank, lines, vocabulary):
    """semantic() within the deadline, or None to use keywords."""
    global _pending
    if not embeddings.enabled() or (_pending is not None and not _pending.done()):
        return None
    _pending = EXECUTOR.submit(semantic, bank, lines, vocabulary)
    try:
        return _pending.result(timeout=settings.PREDICT_TIMEOUT_SECONDS)
    except FutureTimeout:
        log.warning('Embedding timed out; using keywords')
    except Exception as error:
        log.warning('Embedding failed (%s); using keywords', type(error).__name__)
    return None


def model_topic(vectors, line_vector):
    scores = {}
    for topic_id, vector in vectors['bank']['examples']:
        scores[topic_id] = max(scores.get(topic_id, -1.0), dot(line_vector, vector))
    best = max(scores, key=scores.get)
    return best if scores[best] >= TOPIC_THRESHOLD else None


def profile_items(preferences, profile_key):
    if not profile_key:
        return []
    group, name = profile_key.split('.')
    return list((preferences.get(group) or {}).get(name, []))


def capitalize(text):
    return text[:1].upper() + text[1:]


def suggest(lines, preferences, recent=()):
    """{'topic', 'label', 'phrases' (exactly six), 'source'} for the newest lines, or None to keep regular predictions.

    `recent` is the patient's recent spoken phrases, newest first, used only as a small ranking boost.
    """
    bank = wordbank.load()
    lines = [line.strip() for line in lines if line.strip()][-LINES:]
    if not lines:
        return None
    newest = lines[-1]
    vocabulary = tuple(preferences.get('vocabulary', []))
    vectors = model_results(bank, lines, vocabulary)

    topic_id = None
    for index in reversed(range(len(lines))):
        topic_id = model_topic(vectors, vectors['lines'][index]) if vectors else keyword_topic(bank, lines[index])
        if topic_id:
            break
    question, options = is_question(newest), or_options(newest)
    if topic_id is None and not question and not options:
        return None
    yes_no = is_yes_no(newest) and not options
    topic = bank['topics'].get(topic_id)
    phrase_text = {phrase_id: phrase['text'] for phrase_id, phrase in bank['phrases'].items()}

    facts = [capitalize(topic['template'].format(item)) for item in profile_items(preferences, topic['profile_key'])] if topic else []
    newest_vector = vectors['lines'][-1] if vectors else None
    if vectors:
        scored = [(dot(newest_vector, vector), item) for item, vector in zip(vocabulary, vectors['vocabulary'])]
        own_words = [capitalize(item) for score, item in sorted(scored, key=lambda pair: -pair[0]) if score >= VOCABULARY_THRESHOLD]
    else:
        newest_words = set(words(newest))
        own_words = [capitalize(item) for item in vocabulary if newest_words & set(words(item))]

    uses = {}
    for text in recent:
        uses[normalize(text)] = uses.get(normalize(text), 0) + 1
    ranked = []
    # "What/which/who" questions want an answer word (Plus, Math, Mom) before a sentence about the topic.
    wants_answer = question and not yes_no and bool(words(newest)) and words(newest)[0] in QUESTION_WORDS
    if topic:
        for order, phrase in enumerate(wordbank.topic_phrases(bank, topic_id)):
            score = dot(newest_vector, vectors['bank']['phrases'][phrase['id']]) if vectors else 0.0
            score += min(HISTORY_CAP, HISTORY_BOOST * uses.get(normalize(phrase['text']), 0))
            sentence_last = wants_answer and phrase['role'] == 'phrase'
            ranked.append((sentence_last, -score, order, phrase['text']))
    topic_choices = [text for *_, text in sorted(ranked)]

    meta = [phrase_text['something-else']]
    if question and not yes_no and not facts and not options:
        meta.insert(0, phrase_text['i-dont-know'])  # Unknown personal answer: say so, don't invent one.
    content = [*options, *([phrase_text['yes'], phrase_text['no']] if yes_no else []), *facts, *own_words, *topic_choices]
    if topic is None:
        content += [phrase_text[phrase_id] for phrase_id in bank['fallback']]

    result, seen = [], {normalize(text) for text in meta}
    for text in content:
        if len(result) == PHRASE_COUNT - len(meta):
            break
        if normalize(text) not in seen:
            seen.add(normalize(text))
            result.append(text)
    for text in [phrase_text[phrase_id] for phrase_id in bank['fallback']]:  # Thin topics still reach six.
        if len(result) == PHRASE_COUNT - len(meta):
            break
        if normalize(text) not in seen:
            seen.add(normalize(text))
            result.append(text)
    return {'topic': topic_id, 'label': topic['label'] if topic else None,
            'phrases': result + meta, 'source': 'model' if vectors else 'keywords'}
