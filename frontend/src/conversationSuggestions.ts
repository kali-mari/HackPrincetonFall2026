import type { FavoriteItems } from './api'

export type ConversationSuggestions = { topic: string; phrases: string[] }
const tokens = (text: string) => text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []

// Local topic matching, not an LLM: never send conversation context to /api/predict.
// Only these reviewed phrases can become suggestions; transcript text is not copied.
const TOPICS = [
  { topic: 'Drinks', words: ['drink', 'thirsty', 'water', 'juice', 'milk'],
    phrases: ['Yes please', 'No thank you', 'Juice please', 'Water please', 'Help me drink', 'All done'] },
  { topic: 'Food', words: ['eat', 'food', 'hungry', 'breakfast', 'lunch', 'dinner', 'snack', 'pizza', 'apple', 'sandwich', 'cookie'],
    phrases: ['I am hungry', 'Yes please', 'No thank you', 'More please', 'Help me eat', 'All done'] },
  { topic: 'Play', words: ['play', 'game', 'blocks', 'ball', 'toy', 'toys', 'park', 'outside'],
    phrases: ['I want to play', 'My turn', 'Your turn', 'Play with me', 'Help me', 'I want a break'] },
  { topic: 'Feelings', words: ['feel', 'feeling', 'happy', 'sad', 'angry', 'scared', 'upset', 'hurt', 'pain'],
    phrases: ['I feel happy', 'I feel sad', 'I am scared', 'Something hurts', 'I need help', 'I want a hug'] },
  { topic: 'Bathroom', words: ['bathroom', 'toilet', 'potty', 'wash', 'hands'],
    phrases: ['Bathroom please', 'Help me please', 'I need to go', 'Wash my hands', 'Not yet', 'All done'] },
  { topic: 'School', words: ['school', 'class', 'teacher', 'book', 'read', 'draw', 'write', 'homework'],
    phrases: ['Read with me', 'Help me please', 'Say it again', 'I want to draw', 'I need a break', 'All done'] },
  { topic: 'Bedtime', words: ['sleep', 'sleepy', 'tired', 'bed', 'bedtime', 'night', 'nap'],
    phrases: ['I am tired', 'Not yet', 'Read to me', 'I want a hug', 'Good night', 'Stay with me'] },
]

export function conversationSuggestions(segments: readonly string[], favorites: FavoriteItems = {}): ConversationSuggestions | null {
  // Recent phrases win; an ambiguous follow-up can use the preceding topic.
  for (const text of segments.slice(-3).reverse()) {
    const sentenceWords = tokens(text)
    const words = new Set(sentenceWords)
    const namedGroup = (['drinks', 'foods', 'activities'] as const).find((group) =>
      (favorites[group] ?? []).some((item) => {
        const itemWords = tokens(item)
        return itemWords.length > 0 && sentenceWords.some((_, start) =>
          itemWords.every((word, offset) => sentenceWords[start + offset] === word),
        )
      }),
    )
    const namedTopic = namedGroup ? { drinks: 'Drinks', foods: 'Food', activities: 'Play' }[namedGroup] : null
    const topic = TOPICS.find((candidate) => candidate.topic === namedTopic)
      ?? TOPICS.find((candidate) => candidate.words.some((word) => words.has(word)))
    if (topic) {
      const group = topic.topic === 'Drinks' ? 'drinks' : topic.topic === 'Food' ? 'foods'
        : ['Play', 'School', 'Bedtime'].includes(topic.topic) ? 'activities' : null
      const relevant = (group ? favorites[group] ?? [] : []).filter((item) =>
        !['School', 'Bedtime'].includes(topic.topic)
          || tokens(item).some((word) => topic.words.includes(word)),
      )
      const phrases = [...topic.phrases]
      const slots = topic.topic === 'Drinks' ? [2, 3] : topic.topic === 'Bedtime' ? [2] : [0, 3]
      relevant.slice(0, slots.length).forEach((item, index) => {
        phrases[slots[index]] = `I want ${item}`
      })
      const unique = new Map<string, string>()
      for (const phrase of [...phrases, ...topic.phrases]) {
        if (!unique.has(phrase.toLowerCase())) unique.set(phrase.toLowerCase(), phrase)
      }
      return { topic: topic.topic, phrases: [...unique.values()].slice(0, 6) }
    }
  }
  return null // Keep time/activity/history predictions for unknown topics.
}
