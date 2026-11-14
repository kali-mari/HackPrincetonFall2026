// Run with: node --test src/sentence.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EMPTY_STRIP, addWords, clearStrip, deleteLast } from './sentence.ts'

const built = addWords(EMPTY_STRIP, ['I', 'want', 'juice'])

test('Delete right after Clear brings the sentence back, once', () => {
  const cleared = clearStrip(built)
  assert.deepEqual(cleared.words, [])
  const restored = deleteLast(cleared)
  assert.deepEqual(restored.words, ['I', 'want', 'juice'])
  // The undo is used up: Delete now removes words as usual.
  assert.deepEqual(deleteLast(restored).words, ['I', 'want'])
})

test('Adding a word after Clear ends the undo', () => {
  const next = addWords(clearStrip(built), ['go'])
  assert.deepEqual(deleteLast(deleteLast(next)).words, [])
})

test('Clear on an empty strip keeps the earlier undo', () => {
  assert.deepEqual(deleteLast(clearStrip(clearStrip(built))).words, ['I', 'want', 'juice'])
})

test('Delete on a plain empty strip does nothing', () => {
  assert.deepEqual(deleteLast(EMPTY_STRIP), EMPTY_STRIP)
})
