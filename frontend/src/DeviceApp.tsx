import { useEffect, useState } from 'react'
import App from './App'
import Caregiver from './Caregiver'
import Onboarding from './Onboarding'
import { createCaregiver, createPatient, listPatients, type CaregiverProfile, type PatientProfile } from './api'
import { readDeviceProfile, rememberDeviceProfile, type DeviceMode } from './deviceProfile'
import styles from './Onboarding.module.css'

export default function DeviceApp() {
  const [saved] = useState(readDeviceProfile)
  const [caregiver, setCaregiver] = useState<CaregiverProfile | null>(saved
    ? { id: saved.caregiverId, display_name: saved.caregiverName, role: 'caregiver' } : null)
  const [patients, setPatients] = useState<PatientProfile[]>([])
  const [patientId, setPatientId] = useState<string | null>(saved?.patientId ?? null)
  const [mode, setMode] = useState<DeviceMode>(saved?.mode ?? 'caregiver')
  const [route, setRoute] = useState(() => !saved ? '#/profiles'
    : location.hash === '#/profiles' ? '#/profiles' : location.hash === '#/caregiver' || saved.mode === 'caregiver' ? '#/caregiver' : '#/')
  const [resolved, setResolved] = useState(!saved)
  const [loading, setLoading] = useState(Boolean(saved))
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const caregiverId = caregiver?.id
  const patient = patients.find((item) => item.id === patientId) ?? null

  useEffect(() => {
    function onRoute() {
      setRoute(location.hash)
      if (location.hash === '#/caregiver') setMode('caregiver')
      if (location.hash === '#/') setMode('patient')
    }
    window.addEventListener('hashchange', onRoute)
    return () => window.removeEventListener('hashchange', onRoute)
  }, [])

  useEffect(() => { if (location.hash !== route) location.hash = route }, [route])

  useEffect(() => {
    if (!caregiverId) return
    const controller = new AbortController()
    let stale = false
    listPatients(caregiverId, controller.signal).then((rows) => {
      if (stale) return
      setPatients(rows); setError(''); setLoading(false); setResolved(true)
    }).catch(() => {
      if (stale) return
      setError('Linked profiles could not be loaded. Check the connection or use another caregiver code.')
      setLoading(false); setResolved(true)
    })
    return () => { stale = true; controller.abort() }
  }, [caregiverId, refresh])

  useEffect(() => {
    if (caregiver) rememberDeviceProfile({ caregiverId: caregiver.id, caregiverName: caregiver.display_name, patientId, mode })
  }, [caregiver, patientId, mode])

  function activate(nextMode: DeviceMode, id: string | null) {
    setMode(nextMode); setPatientId(id); setRoute(nextMode === 'patient' ? '#/' : '#/caregiver')
  }
  const switchProfile = () => setRoute('#/profiles')

  async function addCaregiver(name: string) {
    const created = await createCaregiver(name)
    setCaregiver(created); setPatients([]); setPatientId(null); setError('')
    return created
  }

  async function addPatient(name: string, timezone: string, caregiverName: string) {
    // Keep a successfully created caregiver if patient validation fails, so retry
    // does not create another caregiver profile.
    const owner = caregiver ?? await addCaregiver(caregiverName)
    const created = await createPatient(owner.id, name, timezone)
    setPatients((rows) => [...rows.filter((item) => item.id !== created.id), created])
    setRefresh((value) => value + 1)
    return created
  }

  async function connect(id: string, name = 'Caregiver profile') {
    const rows = await listPatients(id)
    setCaregiver({ id, display_name: name, role: 'caregiver' })
    setPatients(rows); setPatientId(null); setError(''); setResolved(true)
  }

  if (!resolved) return <main className={styles.page}><div className={styles.shell} role="status">Loading your profiles…</div></main>
  if (route === '#/profiles' || !caregiver || (route !== '#/caregiver' && !patient)) return <Onboarding
    caregiver={caregiver} patients={patients} selectedPatientId={patientId} loading={loading} error={error}
    onRetry={() => { setLoading(true); setRefresh((value) => value + 1) }}
    onCreateCaregiver={addCaregiver} onCreatePatient={addPatient} onConnect={connect} onContinue={activate} />

  if (route === '#/caregiver') {
    if (!patient) return <main className={styles.page}><div className={styles.shell}>
      <p className={styles.eyebrow}>Caregiver profile</p><h1>Welcome, {caregiver.display_name}</h1>
      <section className={styles.panel}><h2>Your first patient profile</h2>
        <p>Add a patient to set favorites, personalize the board, and keep their communication history together.</p>
        <button className={styles.primary} onClick={switchProfile}>Add or choose a patient profile</button>
      </section><button className={styles.secondary} onClick={switchProfile}>Switch profile</button>
      <p className={styles.footer}>Caregiver code for another device: <code>{caregiver.id}</code></p>
    </div></main>
    return <Caregiver key={patient.id} patient={patient} caregiver={caregiver} patients={patients}
      onSelectPatient={setPatientId} onSwitchProfile={switchProfile} />
  }
  return patient ? <App key={patient.id} patient={patient} onSwitchProfile={switchProfile} /> : null
}
