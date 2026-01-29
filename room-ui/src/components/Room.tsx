import { useEffect } from 'react'
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
    // Could show a "click to enable audio" button here if needed
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
    </div>
  )
}
