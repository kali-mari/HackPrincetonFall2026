// Vocal switch detection, kept pure so it can be tested without a microphone.
export const HOLD_MS = 500 // sound must last this long to count (CLAUDE.md: about half a second)
export const GAP_MS = 100 // quiet dips up to this long don't break a sound, like the Arduino sketch's SOUND_GAP_MS

// soundStart: when the current sound began. quietStart: when the current dip began. fired: this sound already fired.
export type VoiceState = { soundStart: number | null; quietStart: number | null; fired: boolean }
export const QUIET: VoiceState = { soundStart: null, quietStart: null, fired: false }

// Feeds one level sample; returns the new state and whether the switch fires now.
export function step(state: VoiceState, loud: boolean, now: number): { state: VoiceState; fire: boolean } {
  if (loud) {
    const soundStart = state.soundStart ?? now
    const fire = !state.fired && now - soundStart >= HOLD_MS
    return { state: { soundStart, quietStart: null, fired: state.fired || fire }, fire }
  }
  const quietStart = state.quietStart ?? now
  // Quiet for longer than a dip: the sound is over, so the next one can fire.
  if (now - quietStart > GAP_MS) return { state: QUIET, fire: false }
  return { state: { ...state, quietStart }, fire: false }
}
