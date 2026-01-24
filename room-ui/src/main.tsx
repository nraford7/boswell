import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles/variables.css'
import './styles/room.css'

const root = document.getElementById('room-root')

if (!root) {
  throw new Error('Root element not found')
}

// Read config from data attributes (set by Jinja template)
const roomUrl = root.dataset.roomUrl || ''
const roomToken = root.dataset.roomToken || ''
const thankYouUrl = root.dataset.thankYouUrl || '/'

createRoot(root).render(
  <StrictMode>
    <App roomUrl={roomUrl} roomToken={roomToken} thankYouUrl={thankYouUrl} />
  </StrictMode>
)
