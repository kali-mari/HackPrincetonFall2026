// Run with: node --test src/scanning.test.ts (Node 24 runs TypeScript directly)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { next, prev, select } from './scanning.ts'

const sizes = [3, 6, 4]

test('first next shows the first group, then groups wrap', () => {
  let s = next(null, sizes)
  assert.deepEqual(s, { group: 0, item: null })
  s = next(next(s, sizes), sizes)
  assert.deepEqual(s, { group: 2, item: null })
  assert.deepEqual(next(s, sizes), { group: 0, item: null })
})

test('select enters a group, and select on an item activates it and stays on the group', () => {
  const entered = select({ group: 1, item: null }, sizes)
  assert.deepEqual(entered, { state: { group: 1, item: 0 }, activate: null })
  const chosen = select(next(entered.state, sizes), sizes)
  assert.deepEqual(chosen, { state: { group: 1, item: null }, activate: [1, 1] })
})

test('stepping past the last item reaches back-out, which leaves without choosing', () => {
  let s = next({ group: 0, item: 2 }, sizes)
  assert.deepEqual(s, { group: 0, item: 3 })
  assert.deepEqual(select(s, sizes), { state: { group: 0, item: null }, activate: null })
  s = next(s, sizes)
  assert.deepEqual(s, { group: 0, item: 0 })
})

test('prev mirrors next for groups and items, wrapping both ways', () => {
  assert.deepEqual(prev(null, sizes), { group: 2, item: null })
  assert.deepEqual(prev({ group: 0, item: null }, sizes), { group: 2, item: null })
  assert.deepEqual(prev({ group: 0, item: 0 }, sizes), { group: 0, item: 3 })
  for (const s of [{ group: 1, item: null }, { group: 1, item: 4 }, { group: 0, item: 3 }]) {
    assert.deepEqual(prev(next(s, sizes), sizes), s)
  }
})
