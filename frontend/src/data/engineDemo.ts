// Fictional replay data only. Nothing here is written to a real patient profile.
export type Context = 'breakfast' | 'play' | 'school'
type Fact = { group: string; value: string; context: Context; phrase: string }
type Speech = { text: string; context: Context }
type Session = { title: string; time: string; prompt: string; replies: Speech[]; words: string[]; facts: Fact[] }

export const BASE_WORDS = ['Yes', 'No', 'More', 'Help', 'Stop', 'Please']
export const DEFAULTS = ['I want water', 'More please', 'I am hungry', 'All done', 'Help me', 'Thank you']
export const CONTEXTS: { id: Context; label: string; question: string }[] = [
  { id: 'breakfast', label: 'Breakfast', question: 'What would you like for breakfast?' },
  { id: 'play', label: 'Playtime', question: 'What would you like to play?' },
  { id: 'school', label: 'School', question: 'What would you like to do at school?' },
]
export const SESSIONS: Session[] = [
  { title: 'A first breakfast', time: 'Day 1 · 8:00 AM', prompt: 'Would you like water or juice?',
    replies: [{ text: 'I want juice', context: 'breakfast' }, { text: 'More please', context: 'breakfast' }],
    words: ['Juice', 'Toast'], facts: [{ group: 'Favorite drink', value: 'Juice', context: 'breakfast', phrase: 'I want juice' }] },
  { title: 'Finding a favorite', time: 'Day 1 · 3:00 PM', prompt: 'Would you like to play blocks with Maya?',
    replies: [{ text: "Let's play blocks", context: 'play' }, { text: 'My turn', context: 'play' }],
    words: ['Blocks', 'Maya', 'Turn'], facts: [{ group: 'Favorite activity', value: 'Blocks', context: 'play', phrase: 'I want blocks' }] },
  { title: 'Breakfast, again', time: 'Day 2 · 8:00 AM', prompt: 'What would you like to eat and drink?',
    replies: [{ text: 'I want juice', context: 'breakfast' }, { text: 'I want toast', context: 'breakfast' }, { text: 'I want juice', context: 'breakfast' }],
    words: ['Hungry', 'Breakfast'], facts: [{ group: 'Favorite food', value: 'Toast', context: 'breakfast', phrase: 'I want toast' }] },
  { title: 'A day at school', time: 'Day 2 · 10:00 AM', prompt: 'Do you want music or a story with Maya?',
    replies: [{ text: 'Music please', context: 'school' }, { text: 'Read a book', context: 'school' }],
    words: ['Music', 'Book', 'School'], facts: [
      { group: 'Class', value: 'Music', context: 'school', phrase: 'Music please' },
      { group: 'Important person', value: 'Maya', context: 'school', phrase: 'With Maya' },
    ] },
  { title: 'More ways to play', time: 'Day 3 · 3:00 PM', prompt: 'Blocks again, or would you like bubbles?',
    replies: [{ text: "Let's play blocks", context: 'play' }, { text: "Let's play blocks", context: 'play' }, { text: 'Bubbles please', context: 'play' }],
    words: ['Bubbles', 'Together'], facts: [{ group: 'Favorite activity', value: 'Bubbles', context: 'play', phrase: 'I want bubbles' }] },
]

export function snapshot(step: number, context: Context) {
  const sessions = SESSIONS.slice(0, Math.max(0, Math.min(SESSIONS.length, step)))
  const facts = sessions.flatMap((session) => session.facts)
  const vocabulary = [...new Set([...BASE_WORDS, ...sessions.flatMap((session) => session.words)])]
  const speech = sessions.flatMap((session) => session.replies)
  const counts = new Map<string, { text: string; uses: number; matching: number; latest: number }>()
  speech.forEach(({ text, context: spokenContext }, latest) => {
    const key = text.toLowerCase()
    const item = counts.get(key) ?? { text, uses: 0, matching: 0, latest }
    item.uses++
    if (spokenContext === context) item.matching++
    item.latest = latest
    counts.set(key, item)
  })
  const suggestions: { text: string; reason: string; source: string }[] = []
  function take(text: string, reason: string, source: string) {
    if (suggestions.length < 6 && !suggestions.some((item) => item.text.toLowerCase() === text.toLowerCase())) {
      suggestions.push({ text, reason, source })
    }
  }
  facts.filter((fact) => fact.context === context && fact.group.startsWith('Favorite')).slice(0, 2)
    .forEach((fact) => take(fact.phrase, `${fact.group}: ${fact.value} · caregiver approved`, 'Profile'))
  const ranked = [...counts.values()].sort((a, b) => b.matching - a.matching || b.uses - a.uses || b.latest - a.latest)
  ranked.forEach((item) => take(item.text,
    item.matching ? `Spoken ${item.matching}× during ${context}` : `Spoken ${item.uses}× in earlier conversations`, 'History'))
  DEFAULTS.forEach((text) => take(text, 'Starter phrase available before any conversations', 'Starter'))
  return { vocabulary, facts, speech, suggestions, ranked }
}
