import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './index.css'
import DeviceApp from './DeviceApp.tsx'

const root = createRoot(document.getElementById('root')!)
root.render(<StrictMode><DeviceApp /></StrictMode>)
