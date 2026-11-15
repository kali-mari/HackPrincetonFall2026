// Relative URLs: the Vite dev server proxies /api to the Django backend (vite.config.ts).

async function post(path: string, body: unknown): Promise<Response> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  })
  if (!res.ok) {
    let message = `${path} failed with ${res.status}`
    try { message = ((await res.json()) as { error: { message: string } }).error.message || message } catch { /* Transport error. */ }
    throw new Error(message)
  }
  return res
}

export async function speak(patientId: string, text: string): Promise<string> {
  const res = await post('/api/aac/speak', { patient_id: patientId, text })
  const { audio_url } = (await res.json()) as { audio_url: string }
  return audio_url
}

export async function logSentence(patientId: string, text: string, inputSource: 'button' | 'keyboard', activity: string): Promise<void> {
  await post('/api/aac/events', { patient_id: patientId, text, timestamp: new Date().toISOString(),
    event_id: crypto.randomUUID(), utterance_id: crypto.randomUUID(), kind: 'spoken', input_source: inputSource, activity })
}

// ISO with the local UTC offset (2026-11-14T12:15:00-05:00), so the backend reads 12:15 as lunch, not 17:15.
export function localIso(date: Date): string {
  const offset = -date.getTimezoneOffset()
  const pad = (n: number) => String(Math.abs(n)).padStart(2, '0')
  const local = new Date(date.getTime() + offset * 60_000).toISOString().slice(0, 19)
  return `${local}${offset >= 0 ? '+' : '-'}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`
}

// [start minute of the day, activity], using only the activity names in backend/seed/demo_history.json,
// so the backend's same-activity history matches. Recess and after school count as play.
const SCHEDULE: [number, string][] = [
  [0, 'breakfast'],
  [10 * 60 + 30, 'play'],
  [11 * 60 + 30, 'lunch'],
  [13 * 60, 'play'],
  [19 * 60, 'bedtime'],
]

export function activityAt(date: Date): string {
  const minute = date.getHours() * 60 + date.getMinutes()
  return SCHEDULE.findLast(([start]) => start <= minute)![1]
}

// The backend requires a nonempty activity and does not echo it, so the schedule supplies it. Rejects anything but exactly 6 strings.
export async function predict(patientId: string, time: Date, recent: string[]): Promise<{ phrases: string[]; activity: string }> {
  const activity = activityAt(time)
  const res = await post('/api/aac/predict', { patient_id: patientId, time: localIso(time), activity, recent })
  const phrases = (await res.json())?.phrases
  if (!Array.isArray(phrases) || phrases.length !== 6 || !phrases.every((p) => typeof p === 'string')) {
    throw new Error('/api/aac/predict returned something other than 6 phrases')
  }
  return { phrases, activity }
}

export type LogEvent = { event_id: string; kind: string; text: string; timestamp: string; activity: string | null }

export type FavoriteItems = { foods?: string[]; drinks?: string[]; activities?: string[] }
export type AboutItems = { classes?: string[]; interests?: string[]; people?: string[] }
export type PatientPreferences = {
  scan_interval_ms: number
  input_modes: ('button' | 'keyboard')[]
  default_activity: string
  voice_id?: string
  favorites?: FavoriteItems
  about?: AboutItems
  vocabulary?: string[]
}
// Caregiver-entered facts; suggestions and selections never write these.
export type ProfileDetails = Pick<PatientPreferences, 'favorites' | 'about' | 'vocabulary'>

export type CaregiverProfile = { id: string; display_name: string; role: 'caregiver' }
export type PatientProfile = { id: string; display_name: string; role: 'patient'; timezone: string; language: 'en'; preferences: PatientPreferences }

export async function patientPreferences(patientId: string): Promise<PatientPreferences> {
  const res = await fetch(`/api/profile/patients/${patientId}`, { signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new Error(`Patient preferences failed with ${res.status}`)
  return ((await res.json()) as { preferences: PatientPreferences }).preferences
}

export async function saveProfileDetails(patientId: string, details: ProfileDetails): Promise<PatientPreferences> {
  // PATCH replaces the whole preferences object: reread it so input/voice settings survive.
  const preferences = await patientPreferences(patientId)
  const res = await fetch(`/api/profile/patients/${patientId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferences: { ...preferences, ...details } }),
    signal: AbortSignal.timeout(10_000),
  })
  if (!res.ok) throw new Error(`Saving profile details failed with ${res.status}`)
  return ((await res.json()) as { preferences: PatientPreferences }).preferences
}

// Newest first. shortcut: one page of 100 events, page with next_cursor if a day ever exceeds that.
export async function events(patientId: string): Promise<LogEvent[]> {
  const path = `/api/aac/patients/${patientId}/events?limit=100`
  const res = await fetch(path, { signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new Error(`${path} failed with ${res.status}`)
  return ((await res.json()) as { events: LogEvent[] }).events
}

export async function createCaregiver(displayName: string): Promise<CaregiverProfile> {
  return (await post('/api/profile/caregivers', { display_name: displayName })).json()
}

export async function createPatient(caregiverId: string, displayName: string, timezone: string): Promise<PatientProfile> {
  return (await post('/api/profile/patients', { caregiver_id: caregiverId, display_name: displayName,
    timezone, language: 'en', preferences: { scan_interval_ms: 1500,
      input_modes: ['button', 'keyboard'], default_activity: 'play' } })).json()
}

export async function listPatients(caregiverId: string, signal?: AbortSignal): Promise<PatientProfile[]> {
  const patients: PatientProfile[] = []
  let cursor: string | null = null
  const seen = new Set<string>()
  do {
    const query = new URLSearchParams({ limit: '100' })
    if (cursor) query.set('cursor', cursor)
    const res = await fetch(`/api/profile/caregivers/${caregiverId}/patients?${query}`, {
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000),
    })
    if (!res.ok) throw new Error(res.status === 404 ? 'No caregiver profile was found for that code.'
      : 'Profiles could not be loaded. Check the connection and try again.')
    const data = (await res.json()) as { patients: PatientProfile[]; next_cursor: string | null }
    patients.push(...data.patients)
    cursor = data.next_cursor
    if (cursor && seen.has(cursor)) throw new Error('Patient list repeated a page')
    if (cursor) seen.add(cursor)
  } while (cursor)
  return patients
}
