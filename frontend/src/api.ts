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
