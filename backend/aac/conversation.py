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
THRESHOLD_RANGE = (0.25, 0.75)  # what a caregiver may choose in the board's input settings
VOCABULARY_THRESHOLD = 0.45
HISTORY_BOOST, HISTORY_CAP = 0.05, 0.15  # Per recent use of the same phrase, capped.
QUESTION_WORDS = {'what', 'which', 'who', 'whose', 'where', 'when', 'why', 'how'}
YES_NO_STARTS = {'am', 'are', 'is', 'was', 'were', 'do', 'does', 'did', 'can', 'could', 'will', 'would',
                 'should', 'shall', 'have', 'has', 'had', 'may', 'might', 'want', 'need'}
ARTICLES = {'a', 'an', 'the', 'some', 'your', 'my'}
NOT_OPTIONS = {'not', 'something', 'anything', 'else', 'this', 'that', 'it', 'you', 'me', 'them', 'so'}
PARTICLES = {'away', 'out', 'up', 'off', 'down', 'over'}  # "taking away", "going out"
FILLER = {'okay', 'ok', 'well', 'um', 'uh', 'hey', 'hi', 'now', 'then', 'alright', 'and', 'like'}
MAX_OPTIONS = 5  # with "Something else", the six cards
MAX_OPTION_WORDS = 3
FOLLOW_UP_STARTS = {'and', 'or', 'also', 'then', 'now', 'again', 'anything', 'more'}

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


def is_follow_up(text):
    """A line that continues the previous topic ("What about now?", "And milk?", "Juice?")
    rather than starting a new one ("What is the weather like?")."""
    found = words(text)
    if not found:
        return False
    if found[:2] in (['what', 'about'], ['how', 'about']) or found[0] in FOLLOW_UP_STARTS:
        return True
    return len(found) <= 3 and found[0] not in QUESTION_WORDS | YES_NO_STARTS


def is_yes_no(text):
    found = words(text)
    return bool(found) and found[0] in YES_NO_STARTS


def _without_articles(found):
    while found and found[0] in ARTICLES:
        found = found[1:]
    return found


def or_options(text):
    """Options the question names, in order, or [] unless it names at least two.

    "Water or juice?" -> Water, Juice; "Water, juice, or milk?" and "Red or blue or
    green?" -> three options (up to MAX_OPTIONS). Items between commas or "or" can be
    a few words ("orange juice"); the first item keeps only its last word, since the
    words before it are the question ("Do you want water" -> Water).
    """
    tokens = re.findall(r"[a-z0-9']+|,", text.lower())
    ors = [index for index, token in enumerate(tokens) if token == 'or']
    if not ors:
        return []
    after = _without_articles(tokens[ors[-1] + 1:])
    if not after or after[0] == ',' or after[0] in NOT_OPTIONS:
        return []
    final = after[:2] if len(after) > 1 and after[1] in PARTICLES else after[:1]  # "taking away"

    segments, current, bounded = [], [], False  # (words, whether a separator precedes them)
    for token in tokens[:ors[-1]]:
        if token in (',', 'or'):
            segments.append((current, bounded))
            current, bounded = [], True
        else:
            current.append(token)
    segments.append((current, bounded))

    items = []
    for found, bounded in reversed([(_without_articles(found), bounded) for found, bounded in segments if found]):
        if not found:
            continue
        if bounded and len(found) <= MAX_OPTION_WORDS:  # a whole item between separators
            items.insert(0, found)
            continue
        last = found[-1]  # the first item: the words before it are the question itself
        if last in FILLER | NOT_OPTIONS:
            break
        shares_last = (len(after) > 1 and after[1] == last) or any(len(item) > 1 and item[-1] == last for item in items)
        if len(found) > 1 and (last in PARTICLES or shares_last):  # "go out", "plus sign"
            items.insert(0, found[-2:])
            if len(after) > 1 and after[1] == last:
                final = after[:2]  # "... or minus sign"
        else:
            items.insert(0, [last])
        break

    options, seen = [], set()
    for item in [*items, final]:
        if item[0] in FILLER | NOT_OPTIONS:
            continue
        text = ' '.join(item)
        if text not in seen:
            seen.add(text)
            options.append(text[:1].upper() + text[1:])
    return options[:MAX_OPTIONS] if len(options) >= 2 else []


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


def model_topic(vectors, line_vector, threshold=TOPIC_THRESHOLD):
    scores = {}
    for topic_id, vector in vectors['bank']['examples']:
        scores[topic_id] = max(scores.get(topic_id, -1.0), dot(line_vector, vector))
    best = max(scores, key=scores.get)
    return best if scores[best] >= threshold else None


def profile_items(preferences, profile_key):
    if not profile_key:
        return []
    group, name = profile_key.split('.')
    return list((preferences.get(group) or {}).get(name, []))


def capitalize(text):
    return text[:1].upper() + text[1:]


def suggest(lines, preferences, recent=(), threshold=TOPIC_THRESHOLD):
    """{'topic', 'label', 'phrases' (exactly six), 'source'} for the newest lines, or None to keep regular predictions.

    `recent` is the patient's recent spoken phrases, newest first, used only as a small ranking boost.
    `threshold` is the topic-match cutoff for the model (higher: fewer, surer topics); keywords ignore it.
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
        topic_id = model_topic(vectors, vectors['lines'][index], threshold) if vectors else keyword_topic(bank, lines[index])
        if topic_id or not is_follow_up(newest):  # a new unrelated question never inherits an old topic
            break
    question, options = is_question(newest), or_options(newest)
    opening = words(newest)[:1]
    if len(lines) > 1 and opening and opening[0] not in QUESTION_WORDS | YES_NO_STARTS:
        # A pause can split "Do you want water, juice," / "or milk?": read the list across both lines.
        joined = or_options(f'{lines[-2].rstrip(" .?!")}, {newest}')
        if len(joined) > len(options):
            options = joined
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
