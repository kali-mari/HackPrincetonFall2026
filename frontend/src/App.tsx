import { useEffect, useRef, useState } from 'react'
import { activityAt, logSentence, predict, speak } from './api'
import Tile from './components/Tile'
import { CATEGORIES, CORE_WORDS, FALLBACK_PREDICTIONS, type Word, type WordType } from './data/symbols'
import { next, prev, select, type ScanMark, type ScanState } from './scanning'
import { EMPTY_STRIP, addWords, clearStrip, deleteLast as deleteFromStrip } from './sentence'
import { useSwitchInput, type Action, type Source, type SourceSettings } from './useSwitchInput'
import { useVoiceSwitch } from './useVoiceSwitch'
import styles from './App.module.css'
import tileStyles from './components/Tile.module.css'

const SETTINGS_KEY = 'aac-input-sources'
const HOME_KEY = 'aac-play-on-home'
const SENSITIVITY_KEY = 'aac-voice-sensitivity'
const DEFAULT_SENSITIVITY = 0.7
const SOURCES: { id: Source; label: string; hint: string }[] = [
  { id: 'button', label: 'Buttons', hint: 'The PREV, NEXT, WORD, DEL and SAY switches' },
  { id: 'touch', label: 'Touch pad', hint: 'The touch sensor' },
  { id: 'voice', label: 'Voice switch', hint: 'The laptop microphone hears a sound held for about half a second' },
]

function loadPlayOnHome(): boolean {
  try {
    return localStorage.getItem(HOME_KEY) === 'true'
  } catch {
    return false
  }
}

function loadSensitivity(): number {
  try {
    return Number(localStorage.getItem(SENSITIVITY_KEY)) || DEFAULT_SENSITIVITY
  } catch {
    return DEFAULT_SENSITIVITY
  }
}

function loadSettings(): SourceSettings {
  // Voice starts off: it needs microphone permission. Stored choices still win.
  const all = { button: true, touch: true, voice: false }
  try {
    return { ...all, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') }
  } catch {
    return all
  }
}

type ScanItem = { key: string; action: () => void }

// The sentence holds labels, so each strip chip looks up its tile's Fitzgerald color.
const WORD_TYPES = new Map<string, WordType>(
  [...CORE_WORDS, ...CATEGORIES.flatMap((c) => Object.values(c.slots))].map((w) => [w.label, w.wordType]),
)

const BOARD_WIDTH = 1280
const BOARD_HEIGHT = 800
const GRID_COLUMNS = 8
const GRID_ROWS = 4
const CORE_COLUMNS = 2

function fitScale() {
  return Math.min(window.innerWidth / BOARD_WIDTH, window.innerHeight / BOARD_HEIGHT)
}

const ERROR_MS = 3000
const PREDICT_EVERY_MS = 60_000
const RECENT_COUNT = 3

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

// Backup voice when /api/speak or its audio fails, so the board never goes silent.
function speakInBrowser(text: string) {
  return new Promise<void>((resolve, reject) => {
    if (!('speechSynthesis' in window)) return reject(new Error('speechSynthesis is not available'))
    const utterance = new SpeechSynthesisUtterance(text)
    // shortcut: some browsers never fire onend (no voices installed), so stop waiting after a generous estimate.
    const timer = setTimeout(resolve, 2000 + text.length * 150)
    utterance.onend = () => {
      clearTimeout(timer)
      resolve()
    }
    utterance.onerror = (e) => {
      clearTimeout(timer)
      reject(new Error(`speechSynthesis failed: ${e.error}`))
    }
    speechSynthesis.cancel()
    speechSynthesis.speak(utterance)
  })
}

// The hardware's LISTEN chord sends PREV and NEXT first; LISTEN within this window undoes them.
const CHORD_MS = 1000

const BLANK_PREDICTIONS = Array<string>(6).fill('')

const onCaregiverPage = () => location.hash === '#/caregiver'

export default function App() {
  const [strip, setStrip] = useState(EMPTY_STRIP)
  const sentence = strip.words
  const [backupVoice, setBackupVoice] = useState(false) // the last sentence used the browser's voice
  // Scan states from before the latest PREV/NEXT presses, for undoing the LISTEN chord.
  const chord = useRef<{ state: ScanState; at: number }[]>([])
  const [categoryId, setCategoryId] = useState(CATEGORIES[0].id)
  const [scale, setScale] = useState(fitScale)
  const [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState('')
  const [scan, setScan] = useState<ScanState>(null)
  const [sources, setSources] = useState(loadSettings)
  const [playOnHome, setPlayOnHome] = useState(loadPlayOnHome)
  const [sensitivity, setSensitivity] = useState(loadSensitivity)
  const [listening, setListening] = useState(false)
  const settingsDialog = useRef<HTMLDialogElement>(null)
  const clockDialog = useRef<HTMLDialogElement>(null)
  const clockInput = useRef<HTMLInputElement>(null)
  // Blank until the first reply, so a dead backend never hides behind made-up phrases.
  const [predictions, setPredictions] = useState(BLANK_PREDICTIONS)
  const [activity, setActivity] = useState('')
  const [demoTime, setDemoTime] = useState('') // "HH:MM", or empty for the real clock
  const [recent, setRecent] = useState<string[]>([]) // last 3 sentences spoken this session

  function toggleSource(id: Source) {
    const updated = { ...sources, [id]: !sources[id] }
    setSources(updated)
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(updated))
    } catch {
      // Private mode or blocked storage: the setting still applies for this session.
    }
  }

  function changeSensitivity(value: number) {
    setSensitivity(value)
    try {
      localStorage.setItem(SENSITIVITY_KEY, String(value))
    } catch {
      // Same as toggleSource: applies for this session only.
    }
  }

  function togglePlayOnHome() {
    setPlayOnHome(!playOnHome)
    try {
      localStorage.setItem(HOME_KEY, String(!playOnHome))
    } catch {
      // Same as toggleSource: applies for this session only.
    }
  }

  useEffect(() => {
    const onResize = () => setScale(fitScale())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const category = CATEGORIES.find((c) => c.id === categoryId)!
  const text = sentence.join(' ')
  const addTile = (word: Word) => setStrip((s) => addWords(s, [word.label]))

  // On load, every 60 seconds, and right away when the demo clock changes or a sentence is spoken.
  useEffect(() => {
    let stale = false
    async function refresh() {
      const time = new Date()
      if (demoTime) {
        const [hours, minutes] = demoTime.split(':').map(Number)
        time.setHours(hours, minutes, 0, 0)
      }
      setActivity(activityAt(time))
      try {
        const result = await predict(time, recent)
        // A newer fetch has started, so this slow reply must not overwrite it.
        if (stale) return
        setPredictions(result.phrases)
      } catch (err) {
        // Keep the previous real phrases; the fallback fills the row only if none ever arrived.
        console.error('Predictions failed; showing the previous or fallback phrases.', err)
        if (!stale) setPredictions((p) => (p[0] ? p : FALLBACK_PREDICTIONS))
      }
    }
    refresh()
    const timer = setInterval(refresh, PREDICT_EVERY_MS)
    return () => {
      stale = true
      clearInterval(timer)
    }
  }, [demoTime, recent])

  // Speaks a sentence from the strip (then clears it) or a prediction phrase (strip untouched).
  async function say(sentenceText: string, fromStrip: boolean) {
    if (!sentenceText || speaking) return
    setSpeaking(true)
    let playedLocally = !playOnHome
    try {
      try {
        const url = await speak(sentenceText)
        // The backend casts to the Google Home itself; playing here too would echo.
        if (!playOnHome) await playAudio(url)
        setBackupVoice(false)
      } catch (err) {
        // Speech provider down (503), timed out, or the clip failed: speak with the browser instead.
        console.error('Speech failed; using the backup voice.', err)
        await speakInBrowser(sentenceText)
        setBackupVoice(true)
        playedLocally = true
      }
    } catch (err) {
      console.error(err)
      setError("Couldn't speak. Try again.")
      setTimeout(() => setError(''), ERROR_MS)
      return
    } finally {
      setSpeaking(false)
    }
    if (fromStrip) setStrip((s) => ({ ...s, words: [] }))
    // Only confirmed local playback counts as spoken (api-contracts.md event lifecycle); a cast is unconfirmed.
    // The child was already heard, so a failed log is not worth an error banner.
    if (playedLocally) logSentence(sentenceText).catch(console.error)
    setRecent((r) => [...r, sentenceText].slice(-RECENT_COUNT))
  }
  const handleSpeak = () => say(text, true)

  const deleteLast = () => setStrip(deleteFromStrip)
  const clear = () => setStrip(clearStrip)

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
    predictions.map((phrase, i) => ({ key: `pred-${i}`, action: () => say(phrase, false) })),
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

  // Each scannable box gets one highlight state, styled in index.css.
  const marks = new Map<string, ScanMark>()
  if (scan) {
    const size = groups[scan.group].length
    const level = scan.item === null ? 'group' : scan.item === size ? 'back' : 'item'
    groups.forEach((group, g) =>
      group.forEach((item, i) => {
        if (g !== scan.group) marks.set(item.key, 'dim')
        else if (level !== 'item') marks.set(item.key, level)
        else if (i === scan.item) marks.set(item.key, 'item')
      }),
    )
  }
  const scanned = (key: string) => marks.get(key)

  function scanSelect() {
    const result = select(scan, sizes)
    setScan(result.state)
    if (result.activate) groups[result.activate[0]][result.activate[1]].action()
  }

  // One path for switches and keyboard. DELETE and SPEAK act directly and leave the highlight where it is.
  // `now` is a millisecond clock from the caller, only compared within one input source.
  function act(action: Action, now: number) {
    if (action === 'PREV' || action === 'NEXT') {
      chord.current = [...chord.current, { state: scan, at: now }].slice(-2)
      setScan((action === 'PREV' ? prev : next)(scan, sizes))
      return
    }
    if (action === 'LISTEN') {
      // Undo the PREV and NEXT the chord sent just before, so the highlight stays put.
      const [first, second] = chord.current
      if (second && now - first.at < CHORD_MS) setScan(first.state)
      chord.current = []
      setListening((l) => !l)
      return
    }
    chord.current = []
    if (action === 'SELECT') scanSelect()
    else if (action === 'DELETE') deleteLast()
    else handleSpeak()
  }

  // The board stays mounted under the caregiver page so its state survives; it ignores input there.
  const { connected, flash, showFlash } = useSwitchInput(sources, (action, now) => onCaregiverPage() || act(action, now))
  // Per the contract, voice always means SELECT. Higher sensitivity is a lower level threshold.
  const voice = useVoiceSwitch(sources.voice, 1 - sensitivity, () => {
    if (!onCaregiverPage()) act('SELECT', performance.now())
    showFlash('voice')
  })

  // Re-bound every render so the handler always sees the current groups and state.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const action: Action | undefined =
        e.code === 'Space' ? 'NEXT'
        : e.code === 'Enter' ? (e.shiftKey ? 'SPEAK' : 'SELECT')
        : e.code === 'ArrowLeft' ? 'PREV'
        : e.code === 'Backspace' ? 'DELETE'
        : e.code === 'KeyL' ? 'LISTEN'
        : undefined
      // An open dialog (settings, demo clock) keeps its own keys.
      if (!action || onCaregiverPage() || document.querySelector('dialog[open]')) return
      // Stop the browser from also clicking whichever button has focus.
      e.preventDefault()
      if (e.repeat) return
      act(action, e.timeStamp)
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
        <h1 className={styles.visuallyHidden}>Smart AAC Board</h1>
        {/* Announces each spoken sentence to screen readers. */}
        <p className={styles.visuallyHidden} role="status">
          {recent.at(-1)}
        </p>
        <button
          className={styles.strip}
          onClick={handleSpeak}
          disabled={speaking}
          aria-label={`Sentence: ${text || 'empty'}. Tap to speak.`}
          tabIndex={-1} // repeats Speak, so keyboard focus skips it and follows the scan order
        >
          <span className={styles.chips}>
            {sentence.map((label, i) => (
              <span key={i} className={`${styles.chip} ${tileStyles[WORD_TYPES.get(label) ?? '']}`}>
                {label}
              </span>
            ))}
          </span>
        </button>

        <button
          className={styles.speak}
          onClick={handleSpeak}
          disabled={speaking}
          aria-disabled={!text}
          aria-busy={speaking}
          data-scan={scanned('speak')}
        >
          {speaking ? (
            <span className={styles.spinner} aria-hidden />
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M4 9h4l5-4v14l-5-4H4z" />
              <path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" />
            </svg>
          )}
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
          {predictions.map((phrase, i) => (
            <button
              key={i}
              className={styles.prediction}
              onClick={() => say(phrase, false)}
              disabled={speaking}
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

        {/* Caregiver controls: never in the scan order, so they come last in keyboard focus too. */}
        <div className={styles.status}>
          <div className={styles.statusTools}>
            <button
              className={styles.tool}
              onClick={() => settingsDialog.current?.showModal()}
              aria-label="Input settings"
            >
              <svg viewBox="0 0 24 24" aria-hidden>
                <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
                <circle cx="16" cy="7" r="2" />
                <circle cx="10" cy="17" r="2" />
              </svg>
            </button>
            <button
              className={styles.tool}
              onClick={() => clockDialog.current?.showModal()}
              aria-label={demoTime ? `Demo clock: ${demoTime}` : 'Demo clock: real time'}
              aria-pressed={Boolean(demoTime)}
            >
              <svg viewBox="0 0 24 24" aria-hidden>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
            </button>
          </div>
          {/* State only for now; speech-to-text is not built yet. */}
          {listening && (
            <p className={styles.listening} role="status">
              Listening
            </p>
          )}
          {backupVoice && <p className={styles.listening}>Backup voice</p>}
          <p className={styles.connection}>
            <span className={connected ? styles.dotOn : styles.dotOff} />
            <span className={styles.visuallyHidden}>{connected ? 'Switches connected' : 'Switches not connected'}</span>
            {/* A switch flash briefly replaces the activity name. */}
            {flash ? <span>{flash}</span> : <span className={styles.activity}>{activity}</span>}
          </p>
        </div>
      </main>

      <dialog ref={clockDialog} className={styles.dialog} aria-labelledby="clock-title">
        <h2 id="clock-title">Demo clock</h2>
        <p>Predictions use this time instead of the real clock.</p>
        <input ref={clockInput} className={styles.time} type="time" defaultValue={demoTime || '12:15'} />
        <button
          className={styles.close}
          onClick={() => {
            setDemoTime(clockInput.current?.value ?? '')
            clockDialog.current?.close()
          }}
        >
          Use this time
        </button>
        <button
          className={styles.secondary}
          onClick={() => {
            setDemoTime('')
            clockDialog.current?.close()
          }}
        >
          Use the real time
        </button>
      </dialog>

      <dialog ref={settingsDialog} className={styles.dialog} aria-labelledby="settings-title">
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
        {sources.voice && (
          <div className={styles.voice}>
            <label>
              Voice sensitivity
              <input
                type="range"
                min={0.05}
                max={0.95}
                step={0.05}
                value={sensitivity}
                onChange={(e) => changeSensitivity(Number(e.target.value))}
              />
            </label>
            {voice.error ? (
              <p role="status">
                {voice.error === 'denied'
                  ? 'Microphone access is blocked. Allow it in the browser to use the voice switch.'
                  : 'No microphone found for the voice switch.'}
              </p>
            ) : (
              // The bar must cross the line and stay there for half a second to count.
              <div className={styles.meter} role="meter" aria-label="Microphone level" aria-valuenow={voice.level} aria-valuemin={0} aria-valuemax={1}>
                <span className={styles.meterLevel} style={{ width: `${voice.level * 100}%` }} />
                <span className={styles.meterThreshold} style={{ left: `${(1 - sensitivity) * 100}%` }} />
              </div>
            )}
          </div>
        )}
        <label className={styles.source}>
          <input type="checkbox" checked={playOnHome} onChange={togglePlayOnHome} />
          <span>
            <strong>Play on Google Home</strong>
            <span>The backend casts speech there, so this screen stays silent</span>
          </span>
        </label>
        <button className={styles.close} onClick={() => settingsDialog.current?.close()}>
          Done
        </button>
        <button className={styles.secondary} onClick={() => (location.hash = '#/caregiver')}>
          Caregiver dashboard
        </button>
      </dialog>
    </div>
  )
}
