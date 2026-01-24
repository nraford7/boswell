# Custom Daily.co Room UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a custom-themed Daily.co room UI for Boswell interviews with black & gold styling, branded loading screen, and custom call controls.

**Architecture:** Standalone Vite/React app in `room-ui/` that builds to static files served by FastAPI. In development, Vite dev server provides HMR; in production, built files are copied to `src/boswell/server/static/room-ui/`.

**Tech Stack:** @daily-co/daily-react, Vite, React 18, Plain CSS with CSS variables

---

## Task 1: Initialize React Project with Vite

**Files:**
- Create: `room-ui/package.json`
- Create: `room-ui/tsconfig.json`
- Create: `room-ui/tsconfig.node.json`
- Create: `room-ui/vite.config.ts`
- Create: `room-ui/.gitignore`

**Step 1: Create room-ui directory**

```bash
mkdir -p /Users/noahraford/Projects/boswell/room-ui
```

**Step 2: Initialize package.json**

Create `room-ui/package.json`:

```json
{
  "name": "boswell-room-ui",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@daily-co/daily-react": "^0.21.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0"
  }
}
```

**Step 3: Create tsconfig.json**

Create `room-ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

**Step 4: Create tsconfig.node.json**

Create `room-ui/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

**Step 5: Create vite.config.ts**

Create `room-ui/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        entryFileNames: 'main.js',
        chunkFileNames: '[name].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith('.css')) {
            return 'main.css'
          }
          return 'assets/[name].[ext]'
        }
      }
    }
  }
})
```

**Step 6: Create .gitignore**

Create `room-ui/.gitignore`:

```
node_modules
dist
.DS_Store
```

**Step 7: Install dependencies**

Run: `cd /Users/noahraford/Projects/boswell/room-ui && npm install`
Expected: Dependencies installed successfully, `node_modules/` created

**Step 8: Verify installation**

Run: `cd /Users/noahraford/Projects/boswell/room-ui && npm list --depth=0`
Expected: Shows @daily-co/daily-react, react, react-dom, vite

**Step 9: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/
git commit -m "feat(room-ui): initialize Vite React project with Daily.co"
```

---

## Task 2: Create Entry Point and HTML Shell

**Files:**
- Create: `room-ui/index.html`
- Create: `room-ui/src/main.tsx`
- Create: `room-ui/src/vite-env.d.ts`

**Step 1: Create index.html**

Create `room-ui/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Interview Room - Boswell</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  </head>
  <body>
    <div id="room-root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 2: Create vite-env.d.ts**

Create `room-ui/src/vite-env.d.ts`:

```typescript
/// <reference types="vite/client" />
```

**Step 3: Create main.tsx with data attribute reading**

Create `room-ui/src/main.tsx`:

```tsx
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
```

**Step 4: Verify files exist**

Run: `ls -la /Users/noahraford/Projects/boswell/room-ui/src/`
Expected: Shows main.tsx, vite-env.d.ts

**Step 5: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/index.html room-ui/src/
git commit -m "feat(room-ui): add entry point and HTML shell"
```

---

## Task 3: Create CSS Theme Variables

**Files:**
- Create: `room-ui/src/styles/variables.css`

**Step 1: Create styles directory**

```bash
mkdir -p /Users/noahraford/Projects/boswell/room-ui/src/styles
```

**Step 2: Create variables.css with Boswell theme**

Create `room-ui/src/styles/variables.css`:

```css
:root {
  /* Boswell dark palette - matches base.html */
  --bg-deep: #0a0a0c;
  --bg-elevated: #111114;
  --bg-surface: #18181c;
  --bg-hover: #222228;

  /* Text */
  --fg: #f5f5f0;
  --fg-muted: #a1a1aa;
  --fg-dim: #71717a;

  /* Accent - Gold */
  --accent: #d4a855;
  --accent-hover: #e4bc6a;
  --accent-glow: rgba(212, 168, 85, 0.15);
  --accent-subtle: rgba(212, 168, 85, 0.08);

  /* Status */
  --error: #ef4444;
  --success: #22c55e;

  /* Borders */
  --border: rgba(255, 255, 255, 0.06);
  --border-accent: rgba(212, 168, 85, 0.3);

  /* Typography */
  --font-display: 'Cormorant Garamond', Georgia, serif;
  --font-body: 'Inter', -apple-system, sans-serif;

  /* Spacing */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-base: 250ms ease;
}

/* Reset */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body, #room-root {
  height: 100%;
  width: 100%;
}

body {
  font-family: var(--font-body);
  background: var(--bg-deep);
  color: var(--fg);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

**Step 3: Verify file exists**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/styles/variables.css | head -20`
Expected: Shows CSS custom properties

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/styles/
git commit -m "feat(room-ui): add Boswell theme CSS variables"
```

---

## Task 4: Create Room CSS Styles

**Files:**
- Create: `room-ui/src/styles/room.css`

**Step 1: Create room.css with all component styles**

Create `room-ui/src/styles/room.css`:

```css
/* Room container */
.room {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--bg-deep);
}

/* Loading Screen */
.loading-screen {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  background: var(--bg-deep);
  position: relative;
  overflow: hidden;
}

.loading-glow {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

.loading-logo {
  font-family: var(--font-display);
  font-size: 3rem;
  font-weight: 500;
  color: var(--accent);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  position: relative;
  z-index: 1;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  position: relative;
  z-index: 1;
}

.loading-text {
  font-size: 0.875rem;
  color: var(--fg-muted);
  position: relative;
  z-index: 1;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; transform: translate(-50%, -50%) scale(1); }
  50% { opacity: 0.8; transform: translate(-50%, -50%) scale(1.1); }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Branding overlay */
.branding {
  position: absolute;
  top: 1.5rem;
  left: 1.5rem;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.branding-logo {
  font-family: var(--font-display);
  font-size: 1.25rem;
  font-weight: 500;
  color: var(--accent);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  opacity: 0.8;
  transition: opacity var(--transition-fast);
}

.branding:hover .branding-logo {
  opacity: 1;
}

/* Controls */
.controls {
  position: absolute;
  bottom: 2rem;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 1rem;
  padding: 0.75rem 1.5rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  z-index: 10;
}

.control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--fg);
  font-family: var(--font-body);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.control-btn:hover {
  background: var(--bg-hover);
  border-color: var(--border-accent);
}

.control-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.control-btn.muted {
  background: var(--error);
  border-color: var(--error);
  color: white;
}

.control-btn.muted:hover {
  background: #dc2626;
  border-color: #dc2626;
}

.control-btn.leave {
  background: transparent;
  border-color: var(--error);
  color: var(--error);
}

.control-btn.leave:hover {
  background: var(--error);
  color: white;
}

/* Icon styles */
.control-icon {
  width: 1.25rem;
  height: 1.25rem;
}

/* Error state */
.error-screen {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  background: var(--bg-deep);
  text-align: center;
  padding: 2rem;
}

.error-title {
  font-family: var(--font-display);
  font-size: 1.5rem;
  color: var(--error);
}

.error-message {
  color: var(--fg-muted);
  max-width: 400px;
}

.error-btn {
  margin-top: 1rem;
  padding: 0.75rem 1.5rem;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-md);
  color: var(--bg-deep);
  font-family: var(--font-body);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.error-btn:hover {
  background: var(--accent-hover);
}
```

**Step 2: Verify file created**

Run: `wc -l /Users/noahraford/Projects/boswell/room-ui/src/styles/room.css`
Expected: Shows line count (approximately 180-200 lines)

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/styles/room.css
git commit -m "feat(room-ui): add room component CSS styles"
```

---

## Task 5: Create LoadingScreen Component

**Files:**
- Create: `room-ui/src/components/LoadingScreen.tsx`

**Step 1: Create components directory**

```bash
mkdir -p /Users/noahraford/Projects/boswell/room-ui/src/components
```

**Step 2: Create LoadingScreen.tsx**

Create `room-ui/src/components/LoadingScreen.tsx`:

```tsx
export function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="loading-glow" />
      <div className="loading-logo">Boswell</div>
      <div className="loading-spinner" />
      <p className="loading-text">Connecting to interview room...</p>
    </div>
  )
}
```

**Step 3: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/components/LoadingScreen.tsx`
Expected: Shows component code

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/components/
git commit -m "feat(room-ui): add LoadingScreen component"
```

---

## Task 6: Create BoswellBranding Component

**Files:**
- Create: `room-ui/src/components/BoswellBranding.tsx`

**Step 1: Create BoswellBranding.tsx**

Create `room-ui/src/components/BoswellBranding.tsx`:

```tsx
export function BoswellBranding() {
  return (
    <div className="branding">
      <span className="branding-logo">Boswell</span>
    </div>
  )
}
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/components/BoswellBranding.tsx`
Expected: Shows component code

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/components/BoswellBranding.tsx
git commit -m "feat(room-ui): add BoswellBranding component"
```

---

## Task 7: Create Controls Component

**Files:**
- Create: `room-ui/src/components/Controls.tsx`

**Step 1: Create Controls.tsx with mute, leave, fullscreen**

Create `room-ui/src/components/Controls.tsx`:

```tsx
import { useDaily, useLocalParticipant } from '@daily-co/daily-react'

export function Controls() {
  const daily = useDaily()
  const localParticipant = useLocalParticipant()
  const isMuted = !localParticipant?.audio

  const toggleMute = () => {
    daily?.setLocalAudio(!localParticipant?.audio)
  }

  const leave = () => {
    daily?.leave()
  }

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen()
    } else {
      document.documentElement.requestFullscreen()
    }
  }

  return (
    <div className="controls">
      <button
        onClick={toggleMute}
        className={`control-btn ${isMuted ? 'muted' : ''}`}
        aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
      >
        <MicIcon muted={isMuted} />
        {isMuted ? 'Unmute' : 'Mute'}
      </button>

      <button
        onClick={leave}
        className="control-btn leave"
        aria-label="Leave interview"
      >
        <LeaveIcon />
        Leave
      </button>

      <button
        onClick={toggleFullscreen}
        className="control-btn"
        aria-label="Toggle fullscreen"
      >
        <FullscreenIcon />
        Fullscreen
      </button>
    </div>
  )
}

function MicIcon({ muted }: { muted: boolean }) {
  if (muted) {
    return (
      <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="1" y1="1" x2="23" y2="23" />
        <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
        <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>
    )
  }
  return (
    <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function LeaveIcon() {
  return (
    <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  )
}

function FullscreenIcon() {
  return (
    <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
    </svg>
  )
}
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/components/Controls.tsx | head -30`
Expected: Shows component code with hooks

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/components/Controls.tsx
git commit -m "feat(room-ui): add Controls component with mute, leave, fullscreen"
```

---

## Task 8: Create Room Component

**Files:**
- Create: `room-ui/src/components/Room.tsx`

**Step 1: Create Room.tsx with meeting state handling**

Create `room-ui/src/components/Room.tsx`:

```tsx
import { useEffect } from 'react'
import { useDaily, useMeetingState, DailyAudio } from '@daily-co/daily-react'
import { LoadingScreen } from './LoadingScreen'
import { BoswellBranding } from './BoswellBranding'
import { Controls } from './Controls'

interface RoomProps {
  thankYouUrl: string
}

export function Room({ thankYouUrl }: RoomProps) {
  const daily = useDaily()
  const meetingState = useMeetingState()

  // Redirect to thank you page when user leaves
  useEffect(() => {
    if (meetingState === 'left-meeting') {
      window.location.href = thankYouUrl
    }
  }, [meetingState, thankYouUrl])

  // Auto-join when daily is ready
  useEffect(() => {
    if (daily && meetingState === 'new') {
      daily.join()
    }
  }, [daily, meetingState])

  // Show loading while joining
  if (meetingState === 'joining-meeting' || meetingState === 'new') {
    return <LoadingScreen />
  }

  // Show error if connection failed
  if (meetingState === 'error') {
    return (
      <div className="error-screen">
        <h2 className="error-title">Connection Error</h2>
        <p className="error-message">
          Unable to connect to the interview room. Please check your internet connection and try again.
        </p>
        <button className="error-btn" onClick={() => window.location.reload()}>
          Try Again
        </button>
      </div>
    )
  }

  return (
    <div className="room">
      <DailyAudio />
      <BoswellBranding />
      <Controls />
    </div>
  )
}
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/components/Room.tsx`
Expected: Shows full component code

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/components/Room.tsx
git commit -m "feat(room-ui): add Room component with meeting state handling"
```

---

## Task 9: Create App Component with DailyProvider

**Files:**
- Create: `room-ui/src/App.tsx`

**Step 1: Create App.tsx**

Create `room-ui/src/App.tsx`:

```tsx
import { DailyProvider } from '@daily-co/daily-react'
import { Room } from './components/Room'

interface AppProps {
  roomUrl: string
  roomToken: string
  thankYouUrl: string
}

export function App({ roomUrl, roomToken, thankYouUrl }: AppProps) {
  // Show error if missing config (only in production, dev uses test values)
  if (!roomUrl && import.meta.env.PROD) {
    return (
      <div className="error-screen">
        <h2 className="error-title">Configuration Error</h2>
        <p className="error-message">
          Room configuration is missing. Please return to the interview landing page and try again.
        </p>
      </div>
    )
  }

  return (
    <DailyProvider url={roomUrl} token={roomToken}>
      <Room thankYouUrl={thankYouUrl} />
    </DailyProvider>
  )
}
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/App.tsx`
Expected: Shows App component with DailyProvider

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/App.tsx
git commit -m "feat(room-ui): add App component with DailyProvider wrapper"
```

---

## Task 10: Create Component Index Export

**Files:**
- Create: `room-ui/src/components/index.ts`

**Step 1: Create index.ts for cleaner imports**

Create `room-ui/src/components/index.ts`:

```typescript
export { Room } from './Room'
export { LoadingScreen } from './LoadingScreen'
export { Controls } from './Controls'
export { BoswellBranding } from './BoswellBranding'
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/room-ui/src/components/index.ts`
Expected: Shows exports

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/src/components/index.ts
git commit -m "feat(room-ui): add component barrel export"
```

---

## Task 11: Verify React App Builds

**Files:**
- None (verification only)

**Step 1: Run TypeScript check**

Run: `cd /Users/noahraford/Projects/boswell/room-ui && npx tsc --noEmit`
Expected: No errors (clean exit)

**Step 2: Run Vite build**

Run: `cd /Users/noahraford/Projects/boswell/room-ui && npm run build`
Expected: Build succeeds, creates `dist/` folder with main.js and main.css

**Step 3: Verify build output**

Run: `ls -la /Users/noahraford/Projects/boswell/room-ui/dist/`
Expected: Shows main.js, main.css, index.html

**Step 4: Commit (if any fixes were needed)**

```bash
cd /Users/noahraford/Projects/boswell
git add room-ui/
git commit -m "fix(room-ui): resolve build issues"
```

---

## Task 12: Create Docker Configuration for room-ui

**Files:**
- Create: `Dockerfile.room-ui`

**Step 1: Create Dockerfile.room-ui**

Create `/Users/noahraford/Projects/boswell/Dockerfile.room-ui`:

```dockerfile
FROM node:20-alpine

WORKDIR /app

# Install dependencies first (cached layer)
COPY room-ui/package*.json ./
RUN npm install

# Copy source (changes more often)
COPY room-ui/ ./

# Expose Vite dev server port
EXPOSE 5173

# Run Vite dev server
CMD ["npm", "run", "dev"]
```

**Step 2: Verify file created**

Run: `cat /Users/noahraford/Projects/boswell/Dockerfile.room-ui`
Expected: Shows Dockerfile contents

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add Dockerfile.room-ui
git commit -m "feat(docker): add Dockerfile for room-ui dev server"
```

---

## Task 13: Update docker-compose.yml with room-ui Service

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Read current docker-compose.yml**

Run: `cat /Users/noahraford/Projects/boswell/docker-compose.yml`
Expected: Shows existing services (db, web, worker)

**Step 2: Add room-ui service to docker-compose.yml**

Add after the existing services section:

```yaml
  room-ui:
    build:
      context: .
      dockerfile: Dockerfile.room-ui
    ports:
      - "5173:5173"
    volumes:
      - ./room-ui:/app
      - /app/node_modules
    environment:
      - VITE_API_URL=http://localhost:8000
```

**Step 3: Verify docker-compose is valid**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose config --quiet && echo "Valid"`
Expected: "Valid" (no errors)

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add docker-compose.yml
git commit -m "feat(docker): add room-ui service to docker-compose"
```

---

## Task 14: Create Static Directory for Production Build

**Files:**
- Create: `src/boswell/server/static/room-ui/.gitkeep`

**Step 1: Create directory structure**

```bash
mkdir -p /Users/noahraford/Projects/boswell/src/boswell/server/static/room-ui
touch /Users/noahraford/Projects/boswell/src/boswell/server/static/room-ui/.gitkeep
```

**Step 2: Verify directory created**

Run: `ls -la /Users/noahraford/Projects/boswell/src/boswell/server/static/room-ui/`
Expected: Shows .gitkeep file

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add src/boswell/server/static/room-ui/
git commit -m "feat(server): add static directory for room-ui production build"
```

---

## Task 15: Update room.html Template

**Files:**
- Modify: `src/boswell/server/templates/guest/room.html`

**Step 1: Read current room.html**

Run: `cat /Users/noahraford/Projects/boswell/src/boswell/server/templates/guest/room.html`
Expected: Shows current iframe-based template

**Step 2: Create backup of current template**

Run: `cp /Users/noahraford/Projects/boswell/src/boswell/server/templates/guest/room.html /Users/noahraford/Projects/boswell/src/boswell/server/templates/guest/room.html.iframe-backup`

**Step 3: Replace room.html with React mounting template**

Replace contents of `src/boswell/server/templates/guest/room.html`:

```html
{% extends "base.html" %}

{% block title %}Interview Room - Boswell{% endblock %}

{% block head %}
<style>
  /* Hide base template background effects for immersive room */
  body::before { display: none !important; }
  body { background: #0a0a0c; }
</style>

{% if config.debug %}
<!-- Development: Vite dev server with HMR -->
<script type="module" src="http://localhost:5173/@vite/client"></script>
<script type="module" src="http://localhost:5173/src/main.tsx"></script>
{% else %}
<!-- Production: Built static files -->
<script type="module" src="/static/room-ui/main.js"></script>
<link rel="stylesheet" href="/static/room-ui/main.css">
{% endif %}
{% endblock %}

{% block body %}
<div id="room-root"
     data-room-url="{{ room_url }}"
     data-room-token="{{ room_token }}"
     data-thank-you-url="/i/{{ interview.magic_token }}/thankyou">
</div>
{% endblock %}
```

**Step 4: Verify template updated**

Run: `cat /Users/noahraford/Projects/boswell/src/boswell/server/templates/guest/room.html`
Expected: Shows new React-mounting template

**Step 5: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add src/boswell/server/templates/guest/room.html src/boswell/server/templates/guest/room.html.iframe-backup
git commit -m "feat(templates): update room.html to mount React app"
```

---

## Task 16: Add Static Files Route to FastAPI

**Files:**
- Modify: `src/boswell/server/main.py`

**Step 1: Read current main.py**

Run: `cat /Users/noahraford/Projects/boswell/src/boswell/server/main.py`
Expected: Shows FastAPI app setup

**Step 2: Add StaticFiles mount for room-ui**

After the existing imports, add:

```python
from starlette.staticfiles import StaticFiles
```

After the existing route includes, add:

```python
# Mount static files for room-ui
app.mount("/static", StaticFiles(directory=str(_TEMPLATE_DIR.parent / "static")), name="static")
```

**Step 3: Verify main.py is valid**

Run: `cd /Users/noahraford/Projects/boswell && python -c "from src.boswell.server.main import app; print('OK')"`
Expected: "OK"

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add src/boswell/server/main.py
git commit -m "feat(server): mount static files for room-ui"
```

---

## Task 17: Create Build Script for Production Deployment

**Files:**
- Create: `scripts/build-room-ui.sh`

**Step 1: Create build script**

Create `/Users/noahraford/Projects/boswell/scripts/build-room-ui.sh`:

```bash
#!/bin/bash
set -e

echo "Building room-ui..."

cd "$(dirname "$0")/../room-ui"

# Install dependencies
npm ci

# Build
npm run build

# Copy to static folder
cp -r dist/* ../src/boswell/server/static/room-ui/

echo "room-ui built and copied to static folder"
```

**Step 2: Make executable**

Run: `chmod +x /Users/noahraford/Projects/boswell/scripts/build-room-ui.sh`

**Step 3: Verify script is executable**

Run: `ls -la /Users/noahraford/Projects/boswell/scripts/build-room-ui.sh`
Expected: Shows -rwxr-xr-x permissions

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell
git add scripts/build-room-ui.sh
git commit -m "feat(scripts): add build script for room-ui production"
```

---

## Task 18: Test Development Workflow

**Files:**
- None (testing only)

**Step 1: Start docker-compose**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose up -d`
Expected: All services start (db, web, worker, room-ui)

**Step 2: Check room-ui container logs**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose logs room-ui`
Expected: Vite server running on http://localhost:5173

**Step 3: Verify Vite dev server responds**

Run: `curl -s http://localhost:5173 | head -5`
Expected: HTML response from Vite

**Step 4: Verify FastAPI serves room page**

Run: `curl -s http://localhost:8000/i/test-token/room 2>/dev/null | grep -o 'room-root' || echo "Route may require valid token"`
Expected: Either finds "room-root" or valid token message

**Step 5: Stop docker-compose**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose down`
Expected: All services stopped

---

## Task 19: Test Production Build

**Files:**
- None (testing only)

**Step 1: Run build script**

Run: `cd /Users/noahraford/Projects/boswell && ./scripts/build-room-ui.sh`
Expected: Build succeeds, files copied to static folder

**Step 2: Verify static files exist**

Run: `ls -la /Users/noahraford/Projects/boswell/src/boswell/server/static/room-ui/`
Expected: Shows main.js, main.css, index.html

**Step 3: Check main.js is valid JavaScript**

Run: `head -1 /Users/noahraford/Projects/boswell/src/boswell/server/static/room-ui/main.js`
Expected: Shows minified JavaScript

**Step 4: Commit production build (optional, for Railway)**

```bash
cd /Users/noahraford/Projects/boswell
git add src/boswell/server/static/room-ui/
git commit -m "build(room-ui): add production build for deployment"
```

---

## Task 20: Final Integration Verification

**Files:**
- None (verification only)

**Step 1: Start full stack**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose up -d`

**Step 2: Create test interview (if admin access available)**

Manual: Navigate to http://localhost:8000/admin, create a test project and interview

**Step 3: Test interview flow**

Manual:
1. Go to interview landing page
2. Click "Start Interview"
3. Verify room loads with Boswell branding
4. Verify loading screen shows with gold glow
5. Verify mute button toggles state
6. Verify fullscreen button works
7. Click leave, verify redirect to thank you page

**Step 4: Check success criteria**

- [ ] Room loads with black background and gold accents
- [ ] Boswell logo visible in room
- [ ] Custom loading screen shows while connecting
- [ ] Mute button works and shows state
- [ ] Leave button redirects to thank you page
- [ ] Fullscreen button works
- [ ] Audio works (guest can hear bot, bot can hear guest)

**Step 5: Stop docker-compose**

Run: `cd /Users/noahraford/Projects/boswell && docker-compose down`

**Step 6: Final commit**

```bash
cd /Users/noahraford/Projects/boswell
git add -A
git commit -m "feat: complete custom Daily.co room UI implementation"
```

---

## Summary

This plan implements a custom Daily.co room UI for Boswell interviews in 20 tasks:

1. **Tasks 1-4:** Project setup (Vite, TypeScript, CSS theme)
2. **Tasks 5-10:** React components (LoadingScreen, Branding, Controls, Room, App)
3. **Task 11:** Build verification
4. **Tasks 12-14:** Docker and infrastructure
5. **Tasks 15-17:** FastAPI integration (template, static files, build script)
6. **Tasks 18-20:** Testing and verification

Each task is self-contained with exact file paths, complete code, and verification steps.
