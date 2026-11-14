// Run with: node --test src/voice.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { QUIET, step } from './voice.ts'

// Feeds [loud, ms] segments sampled every 10ms; returns the times the switch fired.
function run(segments: [boolean, number][]) {
  let state = QUIET
  let now = 0
  const fired: number[] = []
  for (const [loud, ms] of segments) {
    for (const end = now + ms; now < end; now += 10) {
      const result = step(state, loud, now)
      state = result.state
      if (result.fire) fired.push(now)
    }
  }
  return fired
}

test('fires after 500ms of sound', () => {
  assert.deepEqual(run([[false, 100], [true, 600]]), [600])
})

test('does not fire at 400ms', () => {
  assert.deepEqual(run([[true, 400], [false, 500]]), [])
})

test('a 50ms dip does not reset the sound', () => {
  assert.deepEqual(run([[true, 300], [false, 50], [true, 300]]), [500])
})

test('a dip longer than the gap resets the sound', () => {
  assert.deepEqual(run([[true, 300], [false, 200], [true, 300]]), [])
})

test('a long sound fires once', () => {
  assert.deepEqual(run([[true, 3000]]), [500])
})

test('a long sound with short dips still fires once', () => {
  assert.deepEqual(run([[true, 600], [false, 50], [true, 600], [false, 50], [true, 600]]), [500])
})

test('must go quiet to re-arm', () => {
  assert.deepEqual(run([[true, 600], [false, 200], [true, 600]]), [500, 1300])
})
