import { useEffect, useRef, useState } from 'react'

export type Source = 'button' | 'touch' | 'voice'
export type Action = 'NEXT' | 'SELECT'
export type SourceSettings = Record<Source, boolean>

const MAX_BACKOFF_MS = 5000
const FLASH_MS = 1000

function parse(data: unknown): { action: Action; source: Source } | null {
  try {
    const msg = JSON.parse(String(data))
    const validAction = msg.action === 'NEXT' || msg.action === 'SELECT'
    const validSource = msg.source === 'button' || msg.source === 'touch' || msg.source === 'voice'
    return validAction && validSource ? msg : null
  } catch {
    return null
  }
}

// Listens to WS /ws/input/ (the Arduino bridge) and calls onAction for each message from an enabled source.
export function useSwitchInput(enabled: SourceSettings, onAction: (action: Action) => void) {
  const [connected, setConnected] = useState(false)
  const [flash, setFlash] = useState<Source | null>(null)
  // Refs keep the socket open across renders while still calling the latest handler and settings.
  const latest = useRef({ enabled, onAction })
  useEffect(() => {
    latest.current = { enabled, onAction }
  })

  useEffect(() => {
    let socket: WebSocket
    let retry: number | undefined
    let flashTimer: number | undefined
    let attempt = 0
    let stopped = false

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${protocol}://${location.host}/ws/input/`)
      socket.onopen = () => {
        attempt = 0
        setConnected(true)
      }
      socket.onmessage = (event) => {
        const msg = parse(event.data)
        if (!msg || !latest.current.enabled[msg.source]) return
        latest.current.onAction(msg.action)
        setFlash(msg.source)
        clearTimeout(flashTimer)
        flashTimer = setTimeout(() => setFlash(null), FLASH_MS)
      }
      socket.onclose = () => {
        setConnected(false)
        if (stopped) return
        retry = setTimeout(connect, Math.min(500 * 2 ** attempt++, MAX_BACKOFF_MS))
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(retry)
      clearTimeout(flashTimer)
      socket.close()
    }
  }, [])

  return { connected, flash }
}
