import { useEffect, useRef, useState } from 'react'

// Six on-device answer choices for the newest phrase; computed by the UNO Q, never stored here.
export type ConversationSuggestions = { seq: number; topic: string | null; phrases: string[] }
type State = { phase: 'off' | 'starting' | 'listening' | 'paused'; transcript: string; suggestions: ConversationSuggestions | null; error: string }
const OFF: State = { phase: 'off', transcript: '', suggestions: null, error: '' }

export function parseSuggestions(message: unknown): ConversationSuggestions | null | undefined {
  // undefined: not a valid suggestions message; null: valid, but no choices for this phrase.
  const data = message as { seq?: unknown; topic?: unknown; phrases?: unknown }
  if (typeof data?.seq !== 'number' || !(data.topic === null || typeof data.topic === 'string')
    || !Array.isArray(data.phrases) || !data.phrases.every((phrase) => typeof phrase === 'string')
    || ![0, 6].includes(data.phrases.length)) return undefined
  return data.phrases.length ? { seq: data.seq, topic: data.topic, phrases: data.phrases } : null
}

// Transcripts and suggestions stay in memory for display only, never hosted predictions or storage.
// topicThreshold is the caregiver's topic-match cutoff from Input settings (see the backend's start message).
export function useConversation(patientId: string, topicThreshold: number, onContextChange?: () => void) {
  const [state, setState] = useState<State>(OFF)
  const wanted = useRef(false)
  const playback = useRef(false)
  const socket = useRef<WebSocket | null>(null)
  const latestChange = useRef(onContextChange)
  const newestSeq = useRef(0)
  const threshold = useRef(topicThreshold)
  useEffect(() => { latestChange.current = onContextChange })

  const startMessage = () => JSON.stringify({ type: 'start', patient_id: patientId, topic_threshold: threshold.current })

  // A new threshold applies at once: sending start again on an open session updates its settings.
  useEffect(() => {
    threshold.current = topicThreshold
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: 'start', patient_id: patientId, topic_threshold: topicThreshold }))
    }
  }, [patientId, topicThreshold])

  function closeSession(): Promise<void> {
    const current = socket.current
    socket.current = null // ignore late messages immediately, before close is acknowledged
    if (!current) return Promise.resolve()
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, 2000)
      current.onclose = () => { clearTimeout(timer); resolve() }
      current.close()
    })
  }

  function startSession() {
    if (!wanted.current || socket.current) return
    if (playback.current) {
      setState({ ...OFF, phase: 'paused' })
      return
    }
    setState({ ...OFF, phase: 'starting' })
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const current = new WebSocket(`${protocol}://${location.host}/ws/conversation/`)
    socket.current = current
    let greeting = true
    function fail(message: string) {
      wanted.current = false
      setState({ ...OFF, error: message })
      latestChange.current?.()
      void closeSession()
    }
    newestSeq.current = 0 // seq restarts with each connection
    current.onopen = () => {
      if (socket.current === current) current.send(startMessage())
    }
    current.onmessage = (event) => {
      if (socket.current !== current) return
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'state' && typeof message.listening === 'boolean') {
          if (greeting) { greeting = false; if (!message.listening) return }
          if (message.listening) setState({ ...OFF, phase: 'listening' })
          else { wanted.current = false; setState(OFF); latestChange.current?.(); void closeSession() }
        } else if (message.type === 'transcript' && typeof message.text === 'string') {
          setState((value) => ({ ...value, transcript: message.text.slice(-500) }))
        } else if (message.type === 'suggestions') {
          const suggestions = parseSuggestions(message)
          if (suggestions === undefined) throw new Error('Invalid suggestions')
          if (message.seq < newestSeq.current) return // a slower, older answer
          newestSeq.current = message.seq
          setState((value) => ({ ...value, suggestions }))
          latestChange.current?.()
        } else if (message.type === 'error' && typeof message.message === 'string') {
          fail(message.message)
        }
      } catch {
        fail('Could not read the listening response.')
      }
    }
    current.onclose = () => {
      if (socket.current === current) fail('Listening disconnected. Start it again when the board is ready.')
    }
  }

  function stop() {
    wanted.current = false
    setState(OFF)
    latestChange.current?.()
    return closeSession()
  }

  function toggle() {
    if (wanted.current) void stop()
    else { wanted.current = true; startSession() }
  }

  // Close capture before either backend audio or browser backup speech starts.
  async function pause() {
    playback.current = true
    if (wanted.current) {
      setState({ ...OFF, phase: 'paused' })
      latestChange.current?.()
    }
    await closeSession()
  }

  function resume() {
    playback.current = false
    if (wanted.current) startSession()
  }

  useEffect(() => {
    function onRoute() {
      if (location.hash === '#/caregiver') void stop()
    }
    window.addEventListener('hashchange', onRoute)
    return () => {
      window.removeEventListener('hashchange', onRoute)
      wanted.current = false
      void closeSession()
    }
  }, [])

  return { ...state, active: state.phase !== 'off', toggle, stop, pause, resume }
}
