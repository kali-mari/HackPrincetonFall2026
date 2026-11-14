// The sentence strip's words, plus what the last Clear removed, so one slip never costs a whole sentence.
export type Strip = { words: string[]; cleared: string[] }

export const EMPTY_STRIP: Strip = { words: [], cleared: [] }

// Adding a word ends the chance to undo a Clear.
export const addWords = (strip: Strip, words: string[]): Strip => ({ words: [...strip.words, ...words], cleared: [] })

export const clearStrip = (strip: Strip): Strip => ({
  words: [],
  cleared: strip.words.length ? strip.words : strip.cleared,
})

// Delete on an empty strip right after Clear brings the sentence back.
export const deleteLast = (strip: Strip): Strip =>
  strip.words.length ? { ...strip, words: strip.words.slice(0, -1) } : { words: strip.cleared, cleared: [] }
