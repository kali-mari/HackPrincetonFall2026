export type WordType = 'person' | 'verb' | 'describing' | 'noun' | 'social' | 'negation'

export type Word = {
  id: string
  label: string
  wordType: WordType
  icon: string
}

export type Category = {
  id: string
  label: string
  // Slot numbers 1-24 fill grid columns 3-8 row by row (see LAYOUT.md). Missing slots stay blank.
  slots: Record<number, Word>
}

function word(id: string, label: string, wordType: WordType): Word {
  return { id, label, wordType, icon: `/symbols/${id}.svg` }
}

// Pinned in grid columns 1-2 on every tab, row by row: [col 1, col 2].
export const CORE_WORDS: Word[] = [
  word('i', 'I', 'person'),
  word('want', 'want', 'verb'),
  word('like', 'like', 'verb'),
  word('go', 'go', 'verb'),
  word('more', 'more', 'describing'),
  word('help', 'help', 'verb'),
  word('stop', 'stop', 'verb'),
  word('not', 'not', 'negation'),
]

// Columns keep one job on every tab where they can: col 3 verbs, col 4 describing,
// cols 5-7 things and people, col 8 social words.
export const CATEGORIES: Category[] = [
  {
    id: 'food',
    label: 'Food and Drink',
    slots: {
      1: word('eat', 'eat', 'verb'),
      2: word('hungry', 'hungry', 'describing'),
      3: word('juice', 'juice', 'noun'),
      4: word('water', 'water', 'noun'),
      5: word('milk', 'milk', 'noun'),
      6: word('please', 'please', 'social'),
      7: word('drink', 'drink', 'verb'),
      8: word('thirsty', 'thirsty', 'describing'),
      9: word('snack', 'snack', 'noun'),
      10: word('apple', 'apple', 'noun'),
      11: word('banana', 'banana', 'noun'),
      12: word('thank-you', 'thank you', 'social'),
      14: word('hot', 'hot', 'describing'),
      15: word('crackers', 'crackers', 'noun'),
      16: word('sandwich', 'sandwich', 'noun'),
      17: word('pizza', 'pizza', 'noun'),
      18: word('all-done', 'all done', 'social'),
      20: word('cold', 'cold', 'describing'),
      21: word('cookie', 'cookie', 'noun'),
    },
  },
  {
    id: 'feelings',
    label: 'Feelings',
    slots: {
      1: word('feel', 'feel', 'verb'),
      2: word('happy', 'happy', 'describing'),
      3: word('sad', 'sad', 'describing'),
      4: word('angry', 'angry', 'describing'),
      5: word('scared', 'scared', 'describing'),
      6: word('yes', 'yes', 'social'),
      7: word('hug', 'hug', 'verb'),
      8: word('tired', 'tired', 'describing'),
      9: word('hurt', 'hurt', 'describing'),
      10: word('sick', 'sick', 'describing'),
      11: word('excited', 'excited', 'describing'),
      12: word('no', 'no', 'negation'),
      13: word('rest', 'rest', 'verb'),
      14: word('okay', 'okay', 'describing'),
      15: word('head', 'head', 'noun'),
      16: word('tummy', 'tummy', 'noun'),
      18: word('sorry', 'sorry', 'social'),
    },
  },
  {
    id: 'play',
    label: 'Play and Places',
    slots: {
      1: word('play', 'play', 'verb'),
      2: word('fun', 'fun', 'describing'),
      3: word('outside', 'outside', 'noun'),
      4: word('swing', 'swing', 'noun'),
      5: word('slide', 'slide', 'noun'),
      6: word('my-turn', 'my turn', 'social'),
      7: word('watch', 'watch', 'verb'),
      8: word('fast', 'fast', 'describing'),
      9: word('ball', 'ball', 'noun'),
      10: word('blocks', 'blocks', 'noun'),
      11: word('music', 'music', 'noun'),
      12: word('your-turn', 'your turn', 'social'),
      13: word('read', 'read', 'verb'),
      14: word('loud', 'loud', 'describing'),
      15: word('bathroom', 'bathroom', 'noun'),
      16: word('home', 'home', 'noun'),
      17: word('park', 'park', 'noun'),
      20: word('quiet', 'quiet', 'describing'),
      21: word('book', 'book', 'noun'),
    },
  },
  {
    id: 'people',
    label: 'People and School',
    slots: {
      1: word('see', 'see', 'verb'),
      2: word('nice', 'nice', 'describing'),
      3: word('mom', 'mom', 'person'),
      4: word('dad', 'dad', 'person'),
      5: word('teacher', 'teacher', 'person'),
      6: word('hello', 'hello', 'social'),
      7: word('talk', 'talk', 'verb'),
      8: word('new', 'new', 'describing'),
      9: word('friend', 'friend', 'person'),
      10: word('you', 'you', 'person'),
      11: word('brother', 'brother', 'person'),
      12: word('goodbye', 'goodbye', 'social'),
      13: word('sit', 'sit', 'verb'),
      15: word('sister', 'sister', 'person'),
      16: word('school', 'school', 'noun'),
      17: word('class', 'class', 'noun'),
      18: word('excuse-me', 'excuse me', 'social'),
    },
  },
]

// Shown only when /api/predict fails before any real reply arrives. Each is 22 characters or fewer.
export const FALLBACK_PREDICTIONS = [
  'I want juice',
  'I need the bathroom',
  'I want to play',
  'I am tired',
  'help me please',
  'I want a hug',
]
