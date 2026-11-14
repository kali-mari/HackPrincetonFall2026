import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './index.css'
import App from './App.tsx'
import Caregiver from './Caregiver.tsx'

const root = createRoot(document.getElementById('root')!)
const render = () =>
  root.render(<StrictMode>{location.hash === '#/caregiver' ? <Caregiver /> : <App />}</StrictMode>)
window.addEventListener('hashchange', render)
render()
