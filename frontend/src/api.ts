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

// activity is optional: the CLAUDE.md contract only promises phrases. Rejects anything but exactly 6 strings.
export async function predict(time: Date, recent: string[]): Promise<{ phrases: string[]; activity: string }> {
  const res = await post('/api/predict', { time: localIso(time), activity: '', recent })
  const data = await res.json()
  const phrases = data?.phrases
  if (!Array.isArray(phrases) || phrases.length !== 6 || !phrases.every((p) => typeof p === 'string')) {
    throw new Error('/api/predict returned something other than 6 phrases')
  }
  return { phrases, activity: typeof data.activity === 'string' ? data.activity : '' }
}
