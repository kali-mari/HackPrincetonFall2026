import { StrictMode, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './index.css'
import App from './App.tsx'
import Caregiver from './Caregiver.tsx'

const subscribe = (onChange: () => void) => {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

function Root() {
  const hash = useSyncExternalStore(subscribe, () => location.hash)
  return hash === '#/caregiver' ? <Caregiver /> : <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
