import { useState } from 'react'
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

function PauseIcon({ paused }: { paused: boolean }) {
  if (paused) {
    // Play icon when paused
    return (
      <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polygon points="5 3 19 12 5 21 5 3" />
      </svg>
    )
  }
  // Pause icon
  return (
    <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="6" y="4" width="4" height="16" />
      <rect x="14" y="4" width="4" height="16" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg className="control-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="4" width="16" height="16" rx="2" />
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

export function Controls() {
  const daily = useDaily()
  const localParticipant = useLocalParticipant()
  const [isPaused, setIsPaused] = useState(false)

  const isMuted = !localParticipant?.audio

  const toggleMute = () => {
    if (daily) {
      daily.setLocalAudio(!localParticipant?.audio)
    }
  }

  const togglePause = () => {
    if (daily) {
      // Pause mutes the microphone and sets paused state
      const newPausedState = !isPaused
      setIsPaused(newPausedState)
      if (newPausedState) {
        daily.setLocalAudio(false)
      }
    }
  }

  const stop = () => {
    if (daily) {
      daily.leave()
    }
  }

  const leave = () => {
    if (daily) {
      daily.leave()
    }
  }

  return (
    <div className="controls">
      <button
        className={`control-btn ${isMuted ? 'active' : ''}`}
        onClick={toggleMute}
        disabled={isPaused}
      >
        <MicIcon muted={isMuted} />
        <span>{isMuted ? 'Unmute' : 'Mute'}</span>
      </button>
      <button
        className={`control-btn ${isPaused ? 'active' : ''}`}
        onClick={togglePause}
      >
        <PauseIcon paused={isPaused} />
        <span>{isPaused ? 'Resume' : 'Pause'}</span>
      </button>
      <button
        className="control-btn stop"
        onClick={stop}
      >
        <StopIcon />
        <span>Stop</span>
      </button>
      <button
        className="control-btn leave"
        onClick={leave}
      >
        <LeaveIcon />
        <span>Leave</span>
      </button>
    </div>
  )
}
