import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './index.css'
import App from './App.tsx'
import Caregiver from './Caregiver.tsx'

// The board stays mounted (just hidden) on the caregiver page, so the child's sentence and the demo clock survive a visit.
const root = createRoot(document.getElementById('root')!)
const render = () => {
  const caregiver = location.hash === '#/caregiver'
  root.render(
    <StrictMode>
      <div hidden={caregiver}>
        <App />
      </div>
      {caregiver && <Caregiver />}
    </StrictMode>,
  )
}
window.addEventListener('hashchange', render)
render()
