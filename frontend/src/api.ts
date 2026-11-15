// Relative URLs: the Vite dev server proxies /api to the Django backend (vite.config.ts).

async function post(path: string, body: unknown): Promise<Response> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  })
  if (!res.ok) throw new Error(`${path} failed with ${res.status}`)
  return res
}

export async function speak(text: string): Promise<string> {
  const res = await post('/api/speak', { text })
  const { audio_url } = (await res.json()) as { audio_url: string }
  return audio_url
}

export async function logSentence(text: string): Promise<void> {
  await post('/api/log', { text, timestamp: new Date().toISOString() })
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
export async function predict(time: Date, recent: string[]): Promise<{ phrases: string[]; activity: string }> {
  const activity = activityAt(time)
  const res = await post('/api/predict', { time: localIso(time), activity, recent })
  const phrases = (await res.json())?.phrases
  if (!Array.isArray(phrases) || phrases.length !== 6 || !phrases.every((p) => typeof p === 'string')) {
    throw new Error('/api/predict returned something other than 6 phrases')
  }
  return { phrases, activity }
}

export type LogEvent = { event_id: string; kind: string; text: string; timestamp: string; activity: string | null }

export const DEMO_PATIENT_ID = '22222222-2222-4222-8222-222222222222' // LEGACY_DEMO_PATIENT_ID: where POST /api/log writes

export type FavoriteItems = { foods?: string[]; drinks?: string[]; activities?: string[] }
export type PatientPreferences = {
  scan_interval_ms: number
  input_modes: ('button' | 'keyboard')[]
  default_activity: string
  voice_id?: string
  favorites?: FavoriteItems
}

export async function patientPreferences(): Promise<PatientPreferences> {
  const res = await fetch(`/api/profile/patients/${DEMO_PATIENT_ID}`, { signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new Error(`Patient preferences failed with ${res.status}`)
  return ((await res.json()) as { preferences: PatientPreferences }).preferences
}

export async function saveFavorites(favorites: FavoriteItems): Promise<FavoriteItems> {
  // PATCH replaces the whole preferences object: reread it so input/voice settings survive.
  const preferences = await patientPreferences()
  const res = await fetch(`/api/profile/patients/${DEMO_PATIENT_ID}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferences: { ...preferences, favorites } }),
    signal: AbortSignal.timeout(10_000),
  })
  if (!res.ok) throw new Error(`Saving favorites failed with ${res.status}`)
  return ((await res.json()) as { preferences: PatientPreferences }).preferences.favorites ?? {}
}

// Newest first. shortcut: one page of 100 events, page with next_cursor if a day ever exceeds that.
export async function events(): Promise<LogEvent[]> {
  const path = `/api/aac/patients/${DEMO_PATIENT_ID}/events?limit=100`
  const res = await fetch(path, { signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new Error(`${path} failed with ${res.status}`)
  return ((await res.json()) as { events: LogEvent[] }).events
}
