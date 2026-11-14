import { useEffect, useRef, useState } from 'react'
import { QUIET, step } from './voice'

const POLL_MS = 20
const FULL_SCALE_RMS = 0.25 // a raised voice near a laptop mic; this RMS fills the meter

export type MicError = 'denied' | 'unavailable' | null

// Laptop microphone as a vocal switch: calls onFire once per sound held above threshold (0-1) for HOLD_MS.
// The mic only opens while enabled; level (0-1) feeds the settings meter.
export function useVoiceSwitch(enabled: boolean, threshold: number, onFire: () => void) {
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<MicError>(null)
  const latest = useRef({ threshold, onFire })
  useEffect(() => {
    latest.current = { threshold, onFire }
  })

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let timer: number | undefined

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (err) {
        console.error('Microphone unavailable for the voice switch.', err)
        if (!stopped) setError(err instanceof DOMException && err.name === 'NotAllowedError' ? 'denied' : 'unavailable')
        return
      }
      if (stopped) return stream.getTracks().forEach((t) => t.stop())
      setError(null)
      context = new AudioContext()
      context.resume().catch(() => {}) // Chrome may start it suspended; mic permission usually allows resuming
      const analyser = context.createAnalyser()
      context.createMediaStreamSource(stream).connect(analyser)
      const samples = new Float32Array(analyser.fftSize)
      let state = QUIET
      timer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples)
        const rms = Math.sqrt(samples.reduce((sum, s) => sum + s * s, 0) / samples.length)
        const value = Math.min(1, rms / FULL_SCALE_RMS)
        // Rounded so React skips re-rendering the board when the level barely moves.
        setLevel(Math.round(value * 20) / 20)
        const result = step(state, value >= latest.current.threshold, performance.now())
        state = result.state
        if (result.fire) latest.current.onFire()
      }, POLL_MS)
    }

    start()
    return () => {
      stopped = true
      clearInterval(timer)
      stream?.getTracks().forEach((t) => t.stop())
      context?.close()
      setLevel(0)
    }
  }, [enabled])

  return { level, error }
}
