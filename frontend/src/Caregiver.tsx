import { useEffect, useState } from 'react'
import { events, patientPreferences, predict, saveProfileDetails, type CaregiverProfile, type LogEvent, type PatientPreferences, type PatientProfile, type ProfileDetails } from './api'
import styles from './Caregiver.module.css'

type Prediction = { label: string; activity: string; phrases: string[] }

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })
const dayFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
const RECENT_DAYS = 7
const DAY_MS = 24 * 60 * 60 * 1000
// One textarea per list; group says where it is stored in preferences (vocabulary is a plain list).
const DETAIL_FIELDS = [
  { key: 'foods', group: 'favorites', label: 'Favorite foods', max: 10 },
  { key: 'drinks', group: 'favorites', label: 'Favorite drinks', max: 10 },
  { key: 'activities', group: 'favorites', label: 'Favorite activities or toys', max: 10 },
  { key: 'classes', group: 'about', label: 'Classes', max: 10 },
  { key: 'interests', group: 'about', label: 'Interests and after-school activities', max: 10 },
  { key: 'people', group: 'about', label: 'Important people', max: 10 },
  { key: 'vocabulary', group: null, label: 'Custom words or phrases', max: 50 },
] as const
type DetailKey = (typeof DETAIL_FIELDS)[number]['key']
const EMPTY_DRAFT = Object.fromEntries(DETAIL_FIELDS.map(({ key }) => [key, ''])) as Record<DetailKey, string>

function draftFrom(preferences: PatientPreferences): Record<DetailKey, string> {
  const draft = { ...EMPTY_DRAFT }
  for (const { key, group } of DETAIL_FIELDS) {
    const items = group === null ? preferences.vocabulary
      : (preferences[group] as Record<string, string[] | undefined> | undefined)?.[key]
    draft[key] = (items ?? []).join('\n')
  }
  return draft
}

function at1215() {
  const time = new Date()
  time.setHours(12, 15, 0, 0)
  return time
}

type Props = { patient: PatientProfile; caregiver: CaregiverProfile; patients: PatientProfile[];
  onSelectPatient: (id: string) => void; onSwitchProfile: () => void }

export default function Caregiver({ patient, caregiver, patients, onSelectPatient, onSwitchProfile }: Props) {
  const [spoken, setSpoken] = useState<LogEvent[] | null>(null)
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [error, setError] = useState('')
  const [predictionError, setPredictionError] = useState('')
  const [today] = useState(() => new Date())
  const [detailDraft, setDetailDraft] = useState(EMPTY_DRAFT)
  const [detailsReady, setDetailsReady] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailStatus, setDetailStatus] = useState('')
  const [savingDetails, setSavingDetails] = useState(false)
  const [savedVersion, setSavedVersion] = useState(0)

  async function updateDetails() {
    setDetailError('')
    setDetailStatus('')
    const details: Required<ProfileDetails> = { favorites: {}, about: {}, vocabulary: [] }
    for (const { key, group, label, max } of DETAIL_FIELDS) {
      const items = detailDraft[key].split('\n').map((item) => item.trim()).filter(Boolean)
      if (items.length > max || items.some((item) => item.length > 60)
        || new Set(items.map((item) => item.toLowerCase())).size !== items.length) {
        setDetailError(`${label}: use up to ${max} different items, at most 60 characters each.`)
        return
      }
      if (group === null) details.vocabulary = items
      else (details[group] as Record<string, string[]>)[key] = items
    }
    setSavingDetails(true)
    try {
      await saveProfileDetails(patient.id, details)
      setDetailStatus('Saved.')
      setSavedVersion((value) => value + 1)
    } catch {
      setDetailError('These details could not be saved. Check the connection and try again.')
    } finally {
      setSavingDetails(false)
    }
  }

  useEffect(() => {
    if (savedVersion === 0) {
      patientPreferences(patient.id).then((preferences) => {
        setDetailDraft(draftFrom(preferences))
        setDetailsReady(true)
      }).catch(() => setDetailError('These details could not be loaded. Check the connection and reload.'))
    }
    const since = Date.now() - RECENT_DAYS * DAY_MS
    events(patient.id)
      .then((all) => setSpoken(all.filter((e) => e.kind === 'spoken' && new Date(e.timestamp).getTime() >= since)))
      .catch((err) => {
        console.error(err)
        setError("Recent sentences didn't load. Check that the backend is running on port 8000, then reload this page.")
      })
    const now = new Date()
    Promise.all([predict(patient.id, now, []), predict(patient.id, at1215(), [])])
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
  }, [savedVersion, patient.id])

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
          <h1>{patient.display_name}’s day</h1>
          <p className={styles.muted}>
            {today.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          <p className={styles.muted}>Caregiver: {caregiver.display_name}</p>
        </div>
        <div className={styles.profileControls}>
          <a className={styles.back} href="#/engine">Engine at work</a>
          <label>Patient profile<select value={patient.id} onChange={(event) => onSelectPatient(event.target.value)}>
            {patients.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}
          </select></label>
          <button className={styles.back} onClick={onSwitchProfile}>Switch profile</button>
          <a className={styles.back} href="#/">
          Back to the board
          </a>
        </div>
      </header>

      <details className={styles.deviceCode}><summary>Use these profiles on another device</summary>
        <p>Open onboarding on the other device, choose “Use caregiver code,” and enter:</p>
        <code>{caregiver.id}</code>
      </details>

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
          <section className={styles.card} aria-labelledby="details-title">
            <h2 id="details-title">About the child</h2>
            <p className={styles.muted}>Put one item on each line. These are saved with the local profile and
              treated as known facts when suggesting answers. Suggestions and the child's choices never change them.</p>
            <form className={styles.favorites} onSubmit={(event) => { event.preventDefault(); void updateDetails() }}>
              {DETAIL_FIELDS.map(({ key, label }) => (
                <label key={key}>
                  <span>{label}</span>
                  <textarea rows={3} value={detailDraft[key]} disabled={!detailsReady || savingDetails}
                    onChange={(event) => {
                      setDetailDraft((value) => ({ ...value, [key]: event.target.value }))
                      setDetailStatus('')
                    }} />
                </label>
              ))}
              {detailError && <p className={styles.problem} role="alert">{detailError}</p>}
              {detailStatus && <p role="status">{detailStatus}</p>}
              <button type="submit" disabled={!detailsReady || savingDetails}>
                {savingDetails ? 'Saving…' : 'Save details'}
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
