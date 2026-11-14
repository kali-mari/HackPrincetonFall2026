// Run with: TZ=America/New_York node --test src/api.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { localIso } from './api.ts'

test('localIso keeps the local clock time and adds the offset', () => {
  assert.equal(localIso(new Date(2026, 10, 14, 12, 15)), '2026-11-14T12:15:00-05:00')
  assert.equal(localIso(new Date(2026, 6, 1, 10, 40)), '2026-07-01T10:40:00-04:00')
})
