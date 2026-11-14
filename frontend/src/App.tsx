import { useEffect, useRef, useState } from 'react'
import { logSentence, speak } from './api'
import Tile from './components/Tile'
import { CATEGORIES, CORE_WORDS, DEFAULT_PREDICTIONS, type Word } from './data/symbols'
import { next, select, type ScanState } from './scanning'
import { useSwitchInput, type Source, type SourceSettings } from './useSwitchInput'
import styles from './App.module.css'

const SETTINGS_KEY = 'aac-input-sources'
const SOURCES: { id: Source; label: string; hint: string }[] = [
  { id: 'button', label: 'Buttons', hint: 'The NEXT and SELECT switches' },
  { id: 'touch', label: 'Touch pad', hint: 'The touch sensor' },
  { id: 'voice', label: 'Voice switch', hint: 'A sound held for about half a second' },
]

function loadSettings(): SourceSettings {
  const all = { button: true, touch: true, voice: true }
  try {
    return { ...all, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') }
  } catch {
    return all
  }
}

type ScanItem = { key: string; action: () => void }

const BOARD_WIDTH = 1280
const BOARD_HEIGHT = 800
const GRID_COLUMNS = 8
const GRID_ROWS = 4
const CORE_COLUMNS = 2

function fitScale() {
  return Math.min(window.innerWidth / BOARD_WIDTH, window.innerHeight / BOARD_HEIGHT)
}

const ERROR_MS = 3000

// Resolves when the clip finishes, so Speak stays disabled until the room has heard it.
async function playAudio(url: string) {
  const audio = new Audio(url)
  const ended = new Promise((resolve, reject) => {
    audio.onended = resolve
    audio.onerror = reject
  })
  await audio.play()
  await ended
}

export default function App() {
  const [sentence, setSentence] = useState<string[]>([])
  const [categoryId, setCategoryId] = useState(CATEGORIES[0].id)
  const [scale, setScale] = useState(fitScale)
  const [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState('')
  const [scan, setScan] = useState<ScanState>(null)
  const [sources, setSources] = useState(loadSettings)
  const settingsDialog = useRef<HTMLDialogElement>(null)

  function toggleSource(id: Source) {
    const updated = { ...sources, [id]: !sources[id] }
    setSources(updated)
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(updated))
    } catch {
      // Private mode or blocked storage: the setting still applies for this session.
    }
  }

  useEffect(() => {
    const onResize = () => setScale(fitScale())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const category = CATEGORIES.find((c) => c.id === categoryId)!
  const text = sentence.join(' ')
  const addWords = (words: string[]) => setSentence((s) => [...s, ...words])
  const addTile = (word: Word) => addWords([word.label])

  async function handleSpeak() {
    if (!text || speaking) return
    setSpeaking(true)
    try {
      await playAudio(await speak(text))
    } catch (err) {
      console.error(err)
      setError("Couldn't speak. Try again.")
      setTimeout(() => setError(''), ERROR_MS)
      return
    } finally {
      setSpeaking(false)
    }
    setSentence([])
    // The child was already heard, so a failed log is not worth an error banner.
    logSentence(text).catch(console.error)
  }

  const deleteLast = () => setSentence((s) => s.slice(0, -1))
  const clear = () => setSentence([])

  // Row by row: 2 pinned core words, then 6 category slots. Empty slots keep their place.
  const cells: (Word | undefined)[] = []
  for (let row = 0; row < GRID_ROWS; row++) {
    cells.push(...CORE_WORDS.slice(row * CORE_COLUMNS, (row + 1) * CORE_COLUMNS))
    for (let col = 1; col <= GRID_COLUMNS - CORE_COLUMNS; col++) {
      cells.push(category.slots[row * (GRID_COLUMNS - CORE_COLUMNS) + col])
    }
  }

  // Scan groups in LAYOUT.md order, using the same actions as taps. Empty slots are skipped.
  const groups: ScanItem[][] = [
    [
      { key: 'speak', action: handleSpeak },
      { key: 'delete', action: deleteLast },
      { key: 'clear', action: clear },
    ],
    DEFAULT_PREDICTIONS.map((phrase, i) => ({ key: `pred-${i}`, action: () => addWords(phrase.split(' ')) })),
    CATEGORIES.map((c) => ({ key: `tab-${c.id}`, action: () => setCategoryId(c.id) })),
  ]
  for (let row = 0; row < GRID_ROWS; row++) {
    const items: ScanItem[] = []
    for (let i = row * GRID_COLUMNS; i < (row + 1) * GRID_COLUMNS; i++) {
      const word = cells[i]
      if (word) items.push({ key: `cell-${i}`, action: () => addTile(word) })
    }
    groups.push(items)
  }
  const sizes = groups.map((g) => g.length)

  const lit = new Set<string>()
  if (scan) {
    const group = groups[scan.group]
    const one = scan.item !== null && scan.item < group.length ? group[scan.item] : null
    for (const item of one ? [one] : group) lit.add(item.key)
  }
  const scanned = (key: string) => lit.has(key) || undefined

  const scanNext = () => setScan(next(scan, sizes))
  function scanSelect() {
    const result = select(scan, sizes)
    setScan(result.state)
    if (result.activate) groups[result.activate[0]][result.activate[1]].action()
  }

  const { connected, flash } = useSwitchInput(sources, (action) => (action === 'NEXT' ? scanNext() : scanSelect()))

  // Re-bound every render so the handler always sees the current groups and state.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space' && e.code !== 'Enter') return
      // The settings dialog keeps Space and Enter for its own checkboxes and buttons.
      if (settingsDialog.current?.open) return
      // Stop the browser from also clicking whichever button has focus.
      e.preventDefault()
      if (e.repeat) return
      if (e.code === 'Space') scanNext()
      else scanSelect()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  return (
    <div className={styles.viewport}>
      <main
        className={styles.board}
        style={{ transform: `translate(-50%, -50%) scale(${scale})` }}
        onPointerDown={() => setScan(null)}
      >
        <button
          className={styles.strip}
          onClick={handleSpeak}
          disabled={speaking}
          aria-label={`Sentence: ${text || 'empty'}. Tap to speak.`}
        >
          <span>{text}</span>
        </button>

        {/* Caregiver controls: never in the scan order. /f5 adds the demo clock beside the gear. */}
        <div className={styles.status}>
          <div className={styles.statusTools}>
            <button
              className={styles.gear}
              onClick={() => settingsDialog.current?.showModal()}
              aria-label="Input settings"
            >
              <svg viewBox="0 0 24 24" aria-hidden>
                <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
                <circle cx="16" cy="7" r="2" />
                <circle cx="10" cy="17" r="2" />
              </svg>
            </button>
          </div>
          <p className={styles.connection}>
            <span className={connected ? styles.dotOn : styles.dotOff} />
            <span className={styles.visuallyHidden}>{connected ? 'Switches connected' : 'Switches not connected'}</span>
            {flash && <span>{flash}</span>}
          </p>
        </div>
        <button
          className={styles.speak}
          onClick={handleSpeak}
          disabled={speaking}
          aria-busy={speaking}
          data-scan={scanned('speak')}
        >
          {speaking && <span className={styles.spinner} aria-hidden />}
          {speaking ? 'Speaking' : 'Speak'}
        </button>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <button onClick={deleteLast} data-scan={scanned('delete')}>
          Delete
        </button>
        <button onClick={clear} data-scan={scanned('clear')}>
          Clear
        </button>

        <div className={styles.predictions}>
          {DEFAULT_PREDICTIONS.map((phrase, i) => (
            <button
              key={phrase}
              className={styles.prediction}
              onClick={() => addWords(phrase.split(' '))}
              data-scan={scanned(`pred-${i}`)}
            >
              {phrase}
            </button>
          ))}
        </div>

        <nav className={styles.tabs} aria-label="Categories">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              className={styles.tab}
              aria-pressed={c.id === categoryId}
              onClick={() => setCategoryId(c.id)}
              data-scan={scanned(`tab-${c.id}`)}
            >
              {c.label}
            </button>
          ))}
        </nav>

        <div className={styles.grid}>
          {cells.map((word, i) =>
            word ? (
              <Tile key={`${i}-${word.id}`} word={word} onSelect={addTile} scanned={scanned(`cell-${i}`)} />
            ) : (
              <div key={i} aria-hidden />
            ),
          )}
        </div>
      </main>

      <dialog ref={settingsDialog} className={styles.settings} aria-labelledby="settings-title">
        <h2 id="settings-title">Input settings</h2>
        <p>Choose which switches can move the highlight.</p>
        {SOURCES.map((s) => (
          <label key={s.id} className={styles.source}>
            <input type="checkbox" checked={sources[s.id]} onChange={() => toggleSource(s.id)} />
            <span>
              <strong>{s.label}</strong>
              <span>{s.hint}</span>
            </span>
          </label>
        ))}
        <button className={styles.close} onClick={() => settingsDialog.current?.close()}>
          Done
        </button>
      </dialog>
    </div>
  )
}
