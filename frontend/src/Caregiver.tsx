import { useEffect, useState } from 'react'
import { events, patientPreferences, predict, saveFavorites, type FavoriteItems, type LogEvent } from './api'
import styles from './Caregiver.module.css'

type Prediction = { label: string; activity: string; phrases: string[] }

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const dayFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
const RECENT_DAYS = 7
const DAY_MS = 24 * 60 * 60 * 1000
const FAVORITE_FIELDS = [{ key: 'foods', label: 'Favorite foods' }, { key: 'drinks', label: 'Favorite drinks' },
  { key: 'activities', label: 'Favorite activities or toys' }] as const

function at1215() {
  const time = new Date()
  time.setHours(12, 15, 0, 0)
  return time
}

export default function Caregiver() {
  const [spoken, setSpoken] = useState<LogEvent[] | null>(null)
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [error, setError] = useState('')
  const [predictionError, setPredictionError] = useState('')
  const [today] = useState(() => new Date())
  const [favoriteDraft, setFavoriteDraft] = useState({ foods: '', drinks: '', activities: '' })
  const [favoritesReady, setFavoritesReady] = useState(false)
  const [favoriteError, setFavoriteError] = useState('')
  const [favoriteStatus, setFavoriteStatus] = useState('')
  const [savingFavorites, setSavingFavorites] = useState(false)
  const [savedVersion, setSavedVersion] = useState(0)

  async function updateFavorites() {
    setFavoriteError('')
    setFavoriteStatus('')
    const favorites: FavoriteItems = {}
    for (const { key } of FAVORITE_FIELDS) {
      const items = favoriteDraft[key].split('\n').map((item) => item.trim()).filter(Boolean)
      if (items.length > 10 || items.some((item) => item.length > 60)
        || new Set(items.map((item) => item.toLowerCase())).size !== items.length) {
        setFavoriteError('Use up to 10 different items per group, at most 60 characters each.')
        return
      }
      favorites[key] = items
    }
    setSavingFavorites(true)
    try {
      await saveFavorites(favorites)
      setFavoriteStatus('Favorites saved.')
      setSavedVersion((value) => value + 1)
    } catch {
      setFavoriteError('Favorites could not be saved. Check the connection and try again.')
    } finally {
      setSavingFavorites(false)
    }
  }

  useEffect(() => {
    if (savedVersion === 0) {
      patientPreferences().then((preferences) => {
        const favorites = preferences.favorites ?? {}
        setFavoriteDraft({ foods: (favorites.foods ?? []).join('\n'), drinks: (favorites.drinks ?? []).join('\n'),
          activities: (favorites.activities ?? []).join('\n') })
        setFavoritesReady(true)
      }).catch(() => setFavoriteError('Favorite items could not be loaded. Check the connection and reload.'))
    }
    const since = Date.now() - RECENT_DAYS * DAY_MS
    events()
      .then((all) => setSpoken(all.filter((e) => e.kind === 'spoken' && new Date(e.timestamp).getTime() >= since)))
      .catch((err) => {
        console.error(err)
        setError("Recent sentences didn't load. Check that the backend is running on port 8000, then reload this page.")
      })
    const now = new Date()
    Promise.all([predict(now, []), predict(at1215(), [])])
      .then(([a, b]) =>
        setPredictions([
          { label: `Now, ${timeFormat.format(now)}`, ...a },
          { label: '12:15 PM', ...b },
        ]),
      )
      .catch((err) => {
        console.error(err)
        setPredictionError("Predictions didn't load. Check that the backend is running on port 8000, then reload this page.")
      })
  }, [savedVersion])

  // Events arrive newest first, so each day's group and the days themselves stay newest first.
  const days = new Map<string, LogEvent[]>()
  for (const e of spoken ?? []) {
    const day = dayFormat.format(new Date(e.timestamp))
    days.set(day, [...(days.get(day) ?? []), e])
  }

  const counts = new Map<string, number>()
  for (const e of spoken ?? []) counts.set(e.text, (counts.get(e.text) ?? 0) + 1)
  const mostSaid = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 5)

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Today</h1>
          <p className={styles.muted}>
            {today.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <a className={styles.back} href="#/">
          Back to the board
        </a>
      </header>

      <main className={styles.columns}>
        <section className={styles.card} aria-labelledby="log-title">
          <h2 id="log-title">Recent</h2>
          {error && (
            <p className={styles.problem} role="alert">
              {error}
            </p>
          )}
          {spoken === null && !error && <p className={styles.muted}>Loading…</p>}
          {spoken?.length === 0 && <p className={styles.muted}>Nothing spoken in the last 7 days.</p>}
          {[...days].map(([day, list]) => (
            <div key={day} className={styles.day}>
              <h3>{day}</h3>
              <ol className={styles.timeline}>
                {list.map((e) => (
                  <li key={e.event_id}>
                    <time dateTime={e.timestamp}>{timeFormat.format(new Date(e.timestamp))}</time>
                    <span>{e.text}</span>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>

        <div className={styles.side}>
          <section className={styles.card} aria-labelledby="favorites-title">
            <h2 id="favorites-title">Favorite items</h2>
            <p className={styles.muted}>Choose the child's favorites. Put one item on each line, up to 10 per group.
              These are saved with the local profile and used to personalize AI suggestions.</p>
            <form className={styles.favorites} onSubmit={(event) => { event.preventDefault(); void updateFavorites() }}>
              {FAVORITE_FIELDS.map(({ key, label }) => (
                <label key={key}>
                  <span>{label}</span>
                  <textarea rows={3} value={favoriteDraft[key]} disabled={!favoritesReady || savingFavorites}
                    onChange={(event) => {
                      setFavoriteDraft((value) => ({ ...value, [key]: event.target.value }))
                      setFavoriteStatus('')
                    }} />
                </label>
              ))}
              {favoriteError && <p className={styles.problem} role="alert">{favoriteError}</p>}
              {favoriteStatus && <p role="status">{favoriteStatus}</p>}
              <button type="submit" disabled={!favoritesReady || savingFavorites}>
                {savingFavorites ? 'Saving…' : 'Save favorites'}
              </button>
            </form>
          </section>
          <section className={styles.card} aria-labelledby="most-title">
            <h2 id="most-title">Most said this week</h2>
            {spoken?.length === 0 && <p className={styles.muted}>Phrases the child says most will show here.</p>}
            <ul className={styles.counts}>
              {mostSaid.map(([text, count]) => (
                <li key={text}>
                  <span>{text}</span>
                  <span className={styles.count}>{count}×</span>
                </li>
              ))}
            </ul>
          </section>

          <section className={styles.card} aria-labelledby="adapt-title">
            <h2 id="adapt-title">How predictions adapt</h2>
            {predictionError && (
              <p className={styles.problem} role="alert">
                {predictionError}
              </p>
            )}
            {predictions.length === 0 && !predictionError && <p className={styles.muted}>Loading…</p>}
            <div className={styles.compare}>
              {predictions.map((p) => (
                <div key={p.label}>
                  <h3>{p.label}</h3>
                  <p className={styles.activity}>{p.activity}</p>
                  <ol className={styles.phrases}>
                    {p.phrases.map((phrase) => (
                      <li key={phrase}>{phrase}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
