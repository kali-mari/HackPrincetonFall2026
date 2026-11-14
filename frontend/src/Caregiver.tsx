import { useEffect, useState } from 'react'
import { events, predict, type LogEvent } from './api'
import styles from './Caregiver.module.css'

type Prediction = { label: string; activity: string; phrases: string[] }

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

function at1215() {
  const time = new Date()
  time.setHours(12, 15, 0, 0)
  return time
}

export default function Caregiver() {
  const [spoken, setSpoken] = useState<LogEvent[] | null>(null)
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [error, setError] = useState('')
  const [today] = useState(() => new Date())

  useEffect(() => {
    const today = new Date().toDateString()
    events()
      .then((all) => setSpoken(all.filter((e) => e.kind === 'spoken' && new Date(e.timestamp).toDateString() === today)))
      .catch((err) => {
        console.error(err)
        setError("Couldn't load today's log.")
      })
    const now = new Date()
    Promise.all([predict(now, []), predict(at1215(), [])])
      .then(([a, b]) =>
        setPredictions([
          { label: `Now, ${timeFormat.format(now)}`, ...a },
          { label: '12:15 PM', ...b },
        ]),
      )
      .catch(console.error)
  }, [])

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
          <h2 id="log-title">Said today</h2>
          {error && <p role="alert">{error}</p>}
          {spoken?.length === 0 && <p className={styles.muted}>Nothing spoken yet today.</p>}
          <ol className={styles.timeline}>
            {spoken?.map((e) => (
              <li key={e.event_id}>
                <time dateTime={e.timestamp}>{timeFormat.format(new Date(e.timestamp))}</time>
                <span>{e.text}</span>
              </li>
            ))}
          </ol>
        </section>

        <div className={styles.side}>
          <section className={styles.card} aria-labelledby="most-title">
            <h2 id="most-title">Most said today</h2>
            {mostSaid.length === 0 && <p className={styles.muted}>No sentences yet.</p>}
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
