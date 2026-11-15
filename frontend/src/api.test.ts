// Run with: TZ=America/New_York node --test src/api.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { activityAt, localIso, saveFavorites } from './api.ts'

test('localIso keeps the local clock time and adds the offset', () => {
  assert.equal(localIso(new Date(2026, 10, 14, 12, 15)), '2026-11-14T12:15:00-05:00')
  assert.equal(localIso(new Date(2026, 6, 1, 10, 40)), '2026-07-01T10:40:00-04:00')
})

test('activityAt uses the seed activity names', () => {
  const at = (h: number, m: number) => activityAt(new Date(2026, 10, 14, h, m))
  assert.equal(at(7, 0), 'breakfast')
  assert.equal(at(10, 29), 'breakfast')
  assert.equal(at(10, 40), 'play')
  assert.equal(at(11, 30), 'lunch')
  assert.equal(at(12, 15), 'lunch')
  assert.equal(at(13, 0), 'play')
  assert.equal(at(19, 0), 'bedtime')
  assert.equal(at(23, 59), 'bedtime')
})

test('saving favorites preserves fresh device and voice settings in the profile', async () => {
  const original = globalThis.fetch
  const preferences = { scan_interval_ms: 2500, input_modes: ['keyboard'], default_activity: 'play', voice_id: 'demo-voice' }
  let saved: unknown
  globalThis.fetch = async (_input, init) => {
    if (init?.method === 'PATCH') {
      saved = JSON.parse(String(init.body))
      return new Response(JSON.stringify(saved))
    }
    return new Response(JSON.stringify({ preferences }))
  }
  try {
    await saveFavorites({ drinks: ['mango juice'] })
    assert.deepEqual(saved, { preferences: { ...preferences, favorites: { drinks: ['mango juice'] } } })
  } finally {
    globalThis.fetch = original
  }
})
