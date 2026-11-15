import { useEffect, useRef, useState } from 'react'

type State = { phase: 'off' | 'starting' | 'listening' | 'paused'; transcript: string; segments: string[]; error: string }
const OFF: State = { phase: 'off', transcript: '', segments: [], error: '' }

// Context is used only for local suggestions, never hosted predictions or storage.
export function useConversation(onContextChange?: () => void) {
  const [state, setState] = useState<State>(OFF)
  const wanted = useRef(false)
  const playback = useRef(false)
  const socket = useRef<WebSocket | null>(null)
  const latestChange = useRef(onContextChange)
  useEffect(() => { latestChange.current = onContextChange })

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
    current.onopen = () => {
      if (socket.current === current) current.send(JSON.stringify({ type: 'start' }))
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
          const text = message.text.slice(-500)
          setState((value) => ({ ...value, transcript: text, segments: [...value.segments, text].slice(-3) }))
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
