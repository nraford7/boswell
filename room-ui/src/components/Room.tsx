import { useEffect, useState } from 'react'
import { useDaily, useMeetingState, useParticipantIds, DailyAudio } from '@daily-co/daily-react'
import { LoadingScreen } from './LoadingScreen'
import { BoswellBranding } from './BoswellBranding'
// AudioVisualizer disabled - sync latency issues (see comment below)
// import { AudioVisualizer } from './AudioVisualizer'
import { Controls } from './Controls'

interface RoomProps {
  thankYouUrl: string
}

export function Room({ thankYouUrl }: RoomProps) {
  const daily = useDaily()
  const meetingState = useMeetingState()
  const participantIds = useParticipantIds()
  const [audioEnabled, setAudioEnabled] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)

  // Debug: Log participants
  useEffect(() => {
    console.log('Participants in room:', participantIds)
    if (daily) {
      const participants = daily.participants()
      console.log('Participant details:', participants)
    }
  }, [participantIds, daily])

  // Redirect to thank you page when meeting ends
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

  const startAudioPlayback = async () => {
    if (!daily) {
      return
    }
    try {
      if (typeof (daily as { startAudio?: () => Promise<void> }).startAudio === 'function') {
        await (daily as { startAudio?: () => Promise<void> }).startAudio?.()
      } else {
        const audioEls = Array.from(document.querySelectorAll('audio'))
        await Promise.all(
          audioEls.map((el) => el.play().catch(() => undefined))
        )
      }
      setAudioEnabled(true)
      setAudioError(null)
    } catch (err) {
      console.error('Audio start failed:', err)
      setAudioError('Click to enable audio')
    }
  }

  // Attempt to start audio once joined; browsers may still require a gesture.
  useEffect(() => {
    if (daily && meetingState === 'joined-meeting' && !audioEnabled) {
      startAudioPlayback().catch(() => undefined)
    }
  }, [daily, meetingState, audioEnabled])

  // Loading state
  if (meetingState === 'joining-meeting' || meetingState === 'new') {
    return <LoadingScreen />
  }

  // Error state
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

  // Handle audio playback failures (browser autoplay policy)
  const handlePlayFailed = (e: unknown) => {
    console.error('Audio play failed:', e)
    setAudioError('Click to enable audio')
  }

  // Main room view
  //
  // AudioVisualizer disabled due to ~2s latency between animation and actual speech.
  // Approaches tried:
  // 1. useActiveSpeakerId() - Daily's active speaker detection has inherent delay
  // 2. useParticipantProperty(id, 'tracks.audio') - triggers when track is ready, not when speaking
  // 3. Backend SpeakingStateProcessor sending app messages on TTSStartedFrame/TTSStoppedFrame
  //    - Still had delay due to audio buffering/network latency in the pipeline
  // The latency appears to be inherent in the TTS → Daily → browser audio pipeline.
  //
  return (
    <div className="room">
      <DailyAudio onPlayFailed={handlePlayFailed} />
      <BoswellBranding />
      {/* <AudioVisualizer /> */}
      <Controls />
      {!audioEnabled && meetingState === 'joined-meeting' ? (
        <div className="audio-gate">
          <div className="audio-gate-card">
            <h2>Enable audio</h2>
            <p>Click to allow your browser to play the interview audio.</p>
            <button className="audio-gate-btn" onClick={startAudioPlayback}>
              Enable Audio
            </button>
            {audioError ? <p className="audio-gate-error">{audioError}</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
