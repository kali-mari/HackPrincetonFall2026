import { useState } from 'react'
import type { CaregiverProfile, PatientProfile } from './api'
import type { DeviceMode } from './deviceProfile'
import { validProfileId } from './deviceProfile'
import styles from './Onboarding.module.css'

type Props = {
  caregiver: CaregiverProfile | null
  patients: PatientProfile[]
  selectedPatientId: string | null
  loading: boolean
  error: string
  onRetry: () => void
  onCreateCaregiver: (name: string) => Promise<CaregiverProfile>
  onCreatePatient: (name: string, timezone: string, caregiverName: string) => Promise<PatientProfile>
  onConnect: (id: string, name?: string) => Promise<void>
  onContinue: (mode: DeviceMode, patientId: string | null) => void
}

export default function Onboarding(props: Props) {
  const [step, setStep] = useState<'choose' | 'caregiver' | 'patient' | 'connect'>('choose')
  const [caregiverName, setCaregiverName] = useState('')
  const [patientName, setPatientName] = useState('')
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/New_York')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function changeStep(value: typeof step) { setError(''); setStep(value) }

  async function submit() {
    setBusy(true)
    setError('')
    try {
      if (step === 'caregiver') {
        await props.onCreateCaregiver(caregiverName.trim())
        props.onContinue('caregiver', null)
      } else if (step === 'patient') {
        const patient = await props.onCreatePatient(patientName.trim(), timezone.trim(), caregiverName.trim())
        props.onContinue('patient', patient.id)
      } else if (step === 'connect') {
        if (!validProfileId(code.trim())) throw new Error('Enter a valid caregiver code from the other device.')
        await props.onConnect(code.trim())
        changeStep('choose')
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The profile could not be saved. Please try again.')
    } finally { setBusy(false) }
  }

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <a className={styles.brand} href="#/profiles" onClick={() => changeStep('choose')}>
          <span className={styles.brandMark} aria-hidden>◔</span> Smart AAC Board
        </a>
        <header className={styles.intro}>
          <a href="#/engine">Explore the engine with a seeded demo →</a>
          <p className={styles.eyebrow}>{props.caregiver ? 'Your device, your profiles' : 'Welcome. Let’s get you set up.'}</p>
          <h1>{step === 'choose' ? 'Who’s using the board?' : step === 'caregiver' ? 'Set up a caregiver profile'
            : step === 'patient' ? 'Set up a patient profile' : 'Use an existing caregiver profile'}</h1>
          <p>{step === 'choose' ? 'Choose how you’d like to use this device. You can switch profiles anytime.'
            : step === 'patient' ? 'Give each person their own favorites, suggestions, and communication history.'
            : step === 'connect' ? 'Enter the caregiver code shown on the other device’s dashboard.'
            : 'Keep linked patient profiles and their communication preferences together.'}</p>
        </header>

        {props.error && <div className={styles.problem} role="alert">
          <p>{props.error}</p><button className={styles.secondary} onClick={props.onRetry} disabled={props.loading}>Try again</button>
        </div>}
        {error && <p className={styles.problem} role="alert">{error}</p>}

        {step === 'choose' ? <>
          {props.caregiver && <p className={styles.connected}>Connected caregiver: <strong>{props.caregiver.display_name}</strong></p>}
          <div className={styles.roles}>
            <button className={styles.roleCard} disabled={props.loading || busy}
              onClick={() => props.caregiver ? props.onContinue('caregiver',
                props.patients.find((patient) => patient.id === props.selectedPatientId)?.id ?? props.patients[0]?.id ?? null) : changeStep('caregiver')}>
              <span className={styles.caregiverIcon} aria-hidden>◎</span>
              <strong>Caregiver</strong><span>Set preferences, save favorites, and see communication history.</span>
              <span className={styles.action}>Open caregiver view <span aria-hidden>→</span></span>
            </button>
            <button className={styles.roleCard} disabled={props.loading || busy}
              onClick={() => props.patients.length === 1 ? props.onContinue('patient', props.patients[0].id)
                : props.patients.length > 1 ? document.getElementById('patient-profiles')?.focus() : changeStep('patient')}>
              <span className={styles.patientIcon} aria-hidden>▦</span>
              <strong>Patient</strong><span>Choose pictures, build sentences, and speak with the board.</span>
              <span className={styles.action}>Open communication board <span aria-hidden>→</span></span>
            </button>
          </div>
          {props.loading && <p role="status">Loading linked profiles…</p>}
          {props.patients.length > 0 && <section className={styles.panel} id="patient-profiles" tabIndex={-1} aria-labelledby="patients-title">
            <h2 id="patients-title">Choose a patient profile</h2>
            <div className={styles.patientList}>{props.patients.map((patient) => (
              <button key={patient.id} onClick={() => props.onContinue('patient', patient.id)}>
                <span className={styles.avatar} aria-hidden>{patient.display_name.charAt(0).toUpperCase()}</span>
                <span>{patient.display_name}</span><span aria-hidden>→</span>
              </button>
            ))}</div>
          </section>}
          <nav className={styles.options} aria-label="Profile setup options">
            {props.caregiver && <button className={styles.secondary} onClick={() => changeStep('patient')}>Add patient profile</button>}
            {props.caregiver && <button className={styles.secondary} onClick={() => changeStep('caregiver')}>New caregiver profile</button>}
            <button className={styles.secondary} onClick={() => changeStep('connect')}>Use caregiver code</button>
            {!props.caregiver && <button className={styles.secondary} disabled={busy} onClick={async () => {
              setBusy(true); setError('')
              try { await props.onConnect('11111111-1111-4111-8111-111111111111', 'Demo caregiver') }
              catch { setError('The demo profile is unavailable. Create a profile to continue.') }
              finally { setBusy(false) }
            }}>Try the demo profiles</button>}
          </nav>
        </> : <form className={styles.panel} onSubmit={(event) => { event.preventDefault(); void submit() }}>
          {(step === 'caregiver' || (step === 'patient' && !props.caregiver)) && <label>
            <span>Caregiver name</span><input autoComplete="name" required maxLength={80} value={caregiverName}
              onChange={(event) => setCaregiverName(event.target.value)} disabled={busy} />
          </label>}
          {step === 'patient' && <>
            {props.caregiver && <p>Linked to <strong>{props.caregiver.display_name}</strong></p>}
            <label><span>Patient name</span><input required maxLength={80} value={patientName}
              onChange={(event) => setPatientName(event.target.value)} disabled={busy} /></label>
            <label><span>Time zone</span><input required maxLength={100} value={timezone}
              onChange={(event) => setTimezone(event.target.value)} disabled={busy} /></label>
          </>}
          {step === 'connect' && <label><span>Caregiver code</span><input required value={code}
            onChange={(event) => setCode(event.target.value)} disabled={busy} spellCheck={false} autoCapitalize="none" /></label>}
          <div className={styles.formActions}>
            <button className={styles.secondary} type="button" onClick={() => changeStep('choose')} disabled={busy}>Back</button>
            <button className={styles.primary} type="submit" disabled={busy}>
              {busy ? 'Saving…' : step === 'connect' ? 'Find profiles' : 'Create profile and continue'}
            </button>
          </div>
        </form>}
        <p className={styles.footer}>Profiles are saved on your connected device. Switching profiles keeps each patient’s data separate.</p>
      </div>
    </main>
  )
}
