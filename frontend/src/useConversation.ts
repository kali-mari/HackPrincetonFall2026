import { useEffect, useRef, useState } from 'react'

type State = { phase: 'off' | 'starting' | 'listening' | 'paused'; transcript: string; error: string }
const OFF: State = { phase: 'off', transcript: '', error: '' }

// Transcripts never enter storage, predictions, logs, or the sentence strip.
export function useConversation() {
  const [state, setState] = useState<State>(OFF)
  const wanted = useRef(false)
  const playback = useRef(false)
  const socket = useRef<WebSocket | null>(null)

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
      setState({ phase: 'paused', transcript: '', error: '' })
      return
    }
    setState({ phase: 'starting', transcript: '', error: '' })
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const current = new WebSocket(`${protocol}://${location.host}/ws/conversation/`)
    socket.current = current
    let greeting = true
    function fail(message: string) {
      wanted.current = false
      setState({ phase: 'off', transcript: '', error: message })
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
          if (message.listening) setState({ phase: 'listening', transcript: '', error: '' })
          else { wanted.current = false; setState(OFF); void closeSession() }
        } else if (message.type === 'transcript' && typeof message.text === 'string') {
          setState((value) => ({ ...value, transcript: message.text }))
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
    return closeSession()
  }

  function toggle() {
    if (wanted.current) void stop()
    else { wanted.current = true; startSession() }
  }

  // Close capture before either backend audio or browser backup speech starts.
  async function pause() {
    playback.current = true
    if (wanted.current) setState({ phase: 'paused', transcript: '', error: '' })
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
