import { useDaily, useLocalParticipant } from '@daily-co/daily-react'

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

export function Controls() {
  const daily = useDaily()
  const localParticipant = useLocalParticipant()

  const isMuted = !localParticipant?.audio

  const toggleMute = () => {
    if (daily) {
      daily.setLocalAudio(!localParticipant?.audio)
    }
  }

  const leave = () => {
    if (daily) {
      daily.leave()
    }
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
        className={`control-btn ${isMuted ? 'muted' : ''}`}
        onClick={toggleMute}
        title={isMuted ? 'Unmute' : 'Mute'}
      >
        <MicIcon muted={isMuted} />
      </button>
      <button
        className="control-btn leave"
        onClick={leave}
        title="Leave interview"
      >
        <LeaveIcon />
      </button>
      <button
        className="control-btn"
        onClick={toggleFullscreen}
        title="Toggle fullscreen"
      >
        <FullscreenIcon />
      </button>
    </div>
  )
}
