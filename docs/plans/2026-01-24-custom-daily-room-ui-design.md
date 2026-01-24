# Custom Daily.co Room UI Design

> **For Claude:** Use superpowers:writing-plans to create implementation tasks from this design.

## Goal

Build a custom-themed Daily.co room UI for Boswell interviews with:
- Black & gold color scheme (#0a0a0c background, #d4a855 accent)
- Boswell logo/wordmark
- Custom loading screen with gold glow animation
- Standard call controls (mute, leave, fullscreen) styled to match

## Tech Stack

- **@daily-co/daily-react** - Daily's official React hooks and components
- **Vite** - Build tool with hot module reload for development
- **React 18** - UI framework (only for room page)
- **Plain CSS** - Styling with CSS variables (no Tailwind)

## Architecture

### File Structure

```
boswell/
├── room-ui/                          # React app for room (NEW)
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html                    # Dev entry point
│   ├── src/
│   │   ├── main.tsx                  # Mount point
│   │   ├── App.tsx                   # DailyProvider wrapper
│   │   ├── components/
│   │   │   ├── Room.tsx              # Main room layout
│   │   │   ├── LoadingScreen.tsx     # Boswell branded loader
│   │   │   ├── Controls.tsx          # Mute, leave, fullscreen
│   │   │   └── BoswellBranding.tsx   # Logo overlay
│   │   └── styles/
│   │       ├── variables.css         # Theme colors
│   │       └── room.css              # Component styles
│   └── dist/                         # Production build output
├── src/boswell/server/
│   ├── templates/guest/
│   │   └── room.html                 # Updated to mount React
│   └── static/room-ui/               # Symlink or copy of dist/
├── docker-compose.yml                # Updated with room-ui service
└── Dockerfile.room-ui                # Vite dev server container
```

### Data Flow

1. **FastAPI** renders `room.html` Jinja template with `room_url` and `room_token`
2. **Jinja template** outputs a div with data attributes:
   ```html
   <div id="room-root"
        data-room-url="{{ room_url }}"
        data-room-token="{{ room_token }}"
        data-thank-you-url="/i/{{ interview.magic_token }}/thankyou">
   </div>
   ```
3. **React app** reads data attributes and initializes DailyProvider
4. **Daily.co** handles WebRTC connection, React renders themed UI

### Docker Services (Development)

```yaml
services:
  web:
    # Existing FastAPI service
    ports:
      - "8000:8000"

  worker:
    # Existing voice pipeline worker

  room-ui:
    build:
      dockerfile: Dockerfile.room-ui
    ports:
      - "5173:5173"
    volumes:
      - ./room-ui:/app
      - /app/node_modules
    environment:
      - VITE_API_URL=http://localhost:8000

  db:
    # Existing Postgres
```

### Production Deployment

1. Build React app: `cd room-ui && npm run build`
2. Copy `room-ui/dist/` to `src/boswell/server/static/room-ui/`
3. Update `room.html` to load from `/static/room-ui/` instead of Vite dev server
4. Deploy as normal (Railway builds include the static files)

## Component Design

### DailyProvider Setup (App.tsx)

```tsx
import { DailyProvider } from '@daily-co/daily-react';

export function App({ roomUrl, roomToken, thankYouUrl }) {
  return (
    <DailyProvider url={roomUrl} token={roomToken}>
      <Room thankYouUrl={thankYouUrl} />
    </DailyProvider>
  );
}
```

### Room Component (Room.tsx)

```tsx
import { useDaily, useMeetingState, DailyAudio } from '@daily-co/daily-react';

export function Room({ thankYouUrl }) {
  const daily = useDaily();
  const meetingState = useMeetingState();

  // Redirect on leave
  useEffect(() => {
    if (meetingState === 'left-meeting') {
      window.location.href = thankYouUrl;
    }
  }, [meetingState]);

  if (meetingState === 'joining-meeting') {
    return <LoadingScreen />;
  }

  return (
    <div className="room">
      <DailyAudio />
      <BoswellBranding />
      <Controls />
    </div>
  );
}
```

### Controls Component (Controls.tsx)

```tsx
import { useDaily, useLocalParticipant } from '@daily-co/daily-react';

export function Controls() {
  const daily = useDaily();
  const localParticipant = useLocalParticipant();
  const isMuted = !localParticipant?.audio;

  const toggleMute = () => daily?.setLocalAudio(!localParticipant?.audio);
  const leave = () => daily?.leave();
  const toggleFullscreen = () => document.documentElement.requestFullscreen();

  return (
    <div className="controls">
      <button onClick={toggleMute} className={isMuted ? 'muted' : ''}>
        {isMuted ? 'Unmute' : 'Mute'}
      </button>
      <button onClick={leave} className="leave">
        Leave
      </button>
      <button onClick={toggleFullscreen}>
        Fullscreen
      </button>
    </div>
  );
}
```

### Loading Screen (LoadingScreen.tsx)

Reuse existing Boswell loading animation:

```tsx
export function LoadingScreen() {
  return (
    <div className="loading-state">
      <div className="loading-glow" />
      <div className="loading-logo">Boswell</div>
      <div className="loading-spinner" />
      <p className="loading-text">Connecting to interview room...</p>
    </div>
  );
}
```

## Theme (variables.css)

```css
:root {
  /* Boswell dark palette */
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

  /* Borders */
  --border: rgba(255, 255, 255, 0.06);

  /* Typography */
  --font-display: 'Cormorant Garamond', Georgia, serif;
  --font-body: 'Inter', -apple-system, sans-serif;
}
```

## Updated room.html Template

```html
{% extends "base.html" %}

{% block title %}Interview Room - Boswell{% endblock %}

{% block head %}
<!-- Dev: Vite dev server -->
{% if config.debug %}
<script type="module" src="http://localhost:5173/@vite/client"></script>
<script type="module" src="http://localhost:5173/src/main.tsx"></script>
{% else %}
<!-- Prod: Built static files -->
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

## Docker Development Workflow

### Initial Setup

```bash
# Build and start all services
docker-compose up --build

# In another terminal, watch room-ui logs
docker-compose logs -f room-ui
```

### Development Cycle

1. Edit React files in `room-ui/src/`
2. Vite hot-reloads automatically in browser
3. Changes appear instantly without container restart

### Testing Flow

1. Start docker-compose
2. Go to http://localhost:8000 (FastAPI)
3. Start an interview
4. Room page loads React from http://localhost:5173 (Vite)
5. Verify theming, controls, connection

## Production Build & Deploy

### Build Script (room-ui/package.json)

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }
}
```

### Deployment Steps

1. Build React app:
   ```bash
   cd room-ui
   npm install
   npm run build
   ```

2. Copy to static folder:
   ```bash
   cp -r room-ui/dist/* src/boswell/server/static/room-ui/
   ```

3. Commit and push - Railway builds and deploys

### CI/CD Integration (Optional)

Add to Railway build command or GitHub Action:
```bash
cd room-ui && npm install && npm run build && cp -r dist/* ../src/boswell/server/static/room-ui/
```

## Rollback Plan

If the React UI has issues in production:

1. Revert `room.html` to the simple iframe version (already backed up at `room.html.backup`)
2. Push to deploy
3. Debug React issues locally in Docker

## Success Criteria

- [ ] Room loads with black background and gold accents
- [ ] Boswell logo visible in room
- [ ] Custom loading screen shows while connecting
- [ ] Mute button works and shows state
- [ ] Leave button redirects to thank you page
- [ ] Fullscreen button works
- [ ] Audio works (guest can hear bot, bot can hear guest)
- [ ] Hot reload works in Docker dev environment
- [ ] Production build serves correctly on Railway

## Open Questions (Resolved)

1. ~~Tailwind vs plain CSS~~ → Plain CSS with variables (simpler)
2. ~~Embedded vs separate React build~~ → Separate build, mounted into Jinja
3. ~~Dev workflow~~ → Vite dev server in Docker with hot reload

## Future Enhancements (Out of Scope)

- Video tile display (currently audio-only)
- Transcript preview in UI
- Interview progress indicator
- Network quality indicator
