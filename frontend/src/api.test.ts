// Run with: TZ=America/New_York node --test src/api.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { activityAt, createCaregiver, createPatient, events, listPatients, localIso, logSentence, predict, saveFavorites, speak } from './api.ts'

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
  const paths: string[] = []
  globalThis.fetch = async (input, init) => {
    paths.push(String(input))
    if (init?.method === 'PATCH') {
      saved = JSON.parse(String(init.body))
      return new Response(JSON.stringify(saved))
    }
    return new Response(JSON.stringify({ preferences }))
  }
  try {
    await saveFavorites('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', { drinks: ['mango juice'] })
    assert.deepEqual(saved, { preferences: { ...preferences, favorites: { drinks: ['mango juice'] } } })
    assert.deepEqual(paths, ['/api/profile/patients/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      '/api/profile/patients/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'])
  } finally {
    globalThis.fetch = original
  }
})

test('patient communication uses explicit profile IDs across role and patient switches', async () => {
  const original = globalThis.fetch
  const requests: { path: string; body?: Record<string, unknown> }[] = []
  globalThis.fetch = async (input, init) => {
    const path = String(input)
    requests.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const data = path.endsWith('/predict') ? { phrases: ['One', 'Two', 'Three', 'Four', 'Five', 'Six'] }
      : path.endsWith('/speak') ? { audio_url: '/media/test.mp3' } : { events: [] }
    return new Response(JSON.stringify(data))
  }
  const a = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', b = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
  try {
    await predict(a, new Date(), [])
    await speak(b, 'Hello')
    await logSentence(a, 'Hello', 'keyboard', 'play')
    await events(b)
    assert.equal(requests[0].path, '/api/aac/predict')
    assert.equal(requests[0].body?.patient_id, a)
    assert.equal(requests[1].body?.patient_id, b)
    assert.equal(requests[2].path, '/api/aac/events')
    assert.equal(requests[2].body?.patient_id, a)
    assert.equal(requests[2].body?.input_source, 'keyboard')
    assert.equal(requests[2].body?.kind, 'spoken')
    assert.match(String(requests[2].body?.event_id), /^[0-9a-f-]{36}$/)
    assert.notEqual(requests[2].body?.event_id, requests[2].body?.utterance_id)
    assert.equal(requests[3].path, `/api/aac/patients/${b}/events?limit=100`)
    assert.ok(requests.every(({ path }) => !['/api/log', '/api/speak', '/api/predict'].includes(path)))
  } finally { globalThis.fetch = original }
})

test('onboarding creates separate roles and links the patient to the selected caregiver', async () => {
  const original = globalThis.fetch
  const requests: { path: string; body: Record<string, unknown> }[] = []
  globalThis.fetch = async (input, init) => {
    requests.push({ path: String(input), body: JSON.parse(String(init?.body)) })
    return new Response(JSON.stringify({ id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' }))
  }
  try {
    const caregiver = await createCaregiver('Alex')
    await createPatient(caregiver.id, 'Sam', 'America/New_York')
    assert.deepEqual(requests[0], { path: '/api/profile/caregivers', body: { display_name: 'Alex' } })
    assert.equal(requests[1].path, '/api/profile/patients')
    assert.equal(requests[1].body.caregiver_id, caregiver.id)
    assert.equal(requests[1].body.display_name, 'Sam')
    assert.deepEqual((requests[1].body.preferences as { input_modes: string[] }).input_modes, ['button', 'keyboard'])
    assert.ok(requests.every(({ body }) => !('role' in body)))
  } finally { globalThis.fetch = original }
})

test('profile selection follows pagination for only the chosen caregiver', async () => {
  const original = globalThis.fetch
  const paths: string[] = []
  globalThis.fetch = async (input) => {
    paths.push(String(input))
    return new Response(JSON.stringify(paths.length === 1
      ? { patients: [{ id: 'first' }], next_cursor: 'opaque+cursor' }
      : { patients: [{ id: 'second' }], next_cursor: null }))
  }
  try {
    assert.deepEqual((await listPatients('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')).map((item) => item.id), ['first', 'second'])
    assert.ok(paths.every((path) => path.startsWith('/api/profile/caregivers/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/patients?')))
    assert.equal(new URL(paths[1], 'http://localhost').searchParams.get('cursor'), 'opaque+cursor')
  } finally { globalThis.fetch = original }
})
