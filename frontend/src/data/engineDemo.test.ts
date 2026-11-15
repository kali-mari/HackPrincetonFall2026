import assert from 'node:assert/strict'
import test from 'node:test'
import { BASE_WORDS, CONTEXTS, DEFAULTS, SESSIONS, snapshot } from './engineDemo.ts'

test('every replay step has six unique suggestions in every context', () => {
  for (let step = 0; step <= SESSIONS.length; step++) {
    for (const { id } of CONTEXTS) {
      const state = snapshot(step, id)
      assert.equal(state.suggestions.length, 6)
      assert.equal(new Set(state.suggestions.map((item) => item.text.toLowerCase())).size, 6)
      assert.ok(state.suggestions.every((item) => item.reason.length > 0))
    }
  }
})

test('backward replay and reset restore state without leaking future facts', () => {
  const start = snapshot(0, 'breakfast')
  assert.deepEqual(start.vocabulary, BASE_WORDS)
  assert.deepEqual(start.suggestions.map((item) => item.text), DEFAULTS)
  assert.equal(start.facts.length, 0)
  assert.equal(start.speech.length, 0)
  const first = snapshot(1, 'breakfast')
  snapshot(SESSIONS.length, 'school')
  assert.deepEqual(snapshot(1, 'breakfast'), first)
  assert.deepEqual(snapshot(0, 'breakfast'), start)
  assert.ok(!first.vocabulary.includes('Bubbles'))
  assert.ok(!first.facts.some((fact) => fact.value === 'Music'))
})

test('context changes favorites and repeated choices strengthen history', () => {
  const breakfast = snapshot(SESSIONS.length, 'breakfast')
  const play = snapshot(SESSIONS.length, 'play')
  assert.deepEqual(breakfast.suggestions.slice(0, 2).map((item) => item.text), ['I want juice', 'I want toast'])
  assert.deepEqual(play.suggestions.slice(0, 2).map((item) => item.text), ['I want blocks', 'I want bubbles'])
  assert.equal(play.suggestions[2].text, "Let's play blocks")
  assert.match(play.suggestions[2].reason, /3×/)
  assert.equal(breakfast.ranked.find((item) => item.text === 'I want juice')!.uses, 3)
})
