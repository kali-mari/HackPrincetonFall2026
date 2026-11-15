// Run with: node --test src/useConversation.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseSuggestions } from './useConversation.ts'

const six = ['Yes', 'No', 'Juice please', 'Water please', 'I am thirsty', 'Something else']

test('six phrases become the conversation choices', () => {
  assert.deepEqual(parseSuggestions({ type: 'suggestions', seq: 2, topic: 'Drinks', phrases: six }),
    { seq: 2, topic: 'Drinks', phrases: six })
  assert.deepEqual(parseSuggestions({ type: 'suggestions', seq: 3, topic: null, phrases: six })?.topic, null)
})

test('no phrases means keep the regular predictions', () => {
  assert.equal(parseSuggestions({ type: 'suggestions', seq: 1, topic: null, phrases: [] }), null)
})

test('anything else is rejected rather than shown', () => {
  for (const message of [
    { seq: 1, topic: 'Drinks', phrases: six.slice(0, 5) },
    { seq: 1, topic: 'Drinks', phrases: [...six.slice(0, 5), 7] },
    { seq: '1', topic: 'Drinks', phrases: six },
    { seq: 1, topic: 5, phrases: six },
    { seq: 1, topic: 'Drinks' },
    null,
  ]) assert.equal(parseSuggestions(message), undefined)
})
