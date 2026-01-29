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

  // Debug: Log participants and track subscription status
  useEffect(() => {
    console.log('Participants in room:', participantIds)
    if (daily) {
      const participants = daily.participants()
      console.log('Participant details:', participants)

      // Log track subscription details for each participant
      Object.values(participants).forEach((p) => {
        console.log(`[AUDIO-DEBUG] Participant ${p.user_name || p.session_id}:`, {
          local: p.local,
          audioTrack: p.tracks.audio,
          audioSubscribed: p.tracks.audio.subscribed,
          audioState: p.tracks.audio.state,
        })
      })

      // Log Daily.co configuration
      console.log('[AUDIO-DEBUG] subscribeToTracksAutomatically:', daily.subscribeToTracksAutomatically())
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

  // Listen for track events to debug audio issues
  useEffect(() => {
    if (!daily) return

    const handleTrackStarted = (e: any) => {
      console.log('[AUDIO-DEBUG] track-started:', e)
    }

    const handleParticipantUpdated = (e: any) => {
      if (e.participant?.tracks?.audio) {
        console.log('[AUDIO-DEBUG] participant-updated with audio:', {
          participant: e.participant.user_name || e.participant.session_id,
          audioSubscribed: e.participant.tracks.audio.subscribed,
          audioState: e.participant.tracks.audio.state,
        })
      }
    }

    daily.on('track-started', handleTrackStarted)
    daily.on('participant-updated', handleParticipantUpdated)

    return () => {
      daily.off('track-started', handleTrackStarted)
      daily.off('participant-updated', handleParticipantUpdated)
    }
  }, [daily])

  const startAudioPlayback = () => {
    console.log('[AUDIO-DEBUG] startAudioPlayback called')
    if (!daily) {
      console.error('[AUDIO-DEBUG] No daily instance')
      return
    }

    // CRITICAL: Call audio.play() synchronously to preserve user gesture
    const audioEls = Array.from(document.querySelectorAll('audio'))
    console.log('[AUDIO-DEBUG] Found audio elements:', audioEls.length)

    if (audioEls.length === 0) {
      console.warn('[AUDIO-DEBUG] No audio elements found yet')
      setAudioEnabled(true) // Close modal anyway
      return
    }

    // Start all audio elements playing SYNCHRONOUSLY
    const playPromises = audioEls.map((el) => {
      console.log('[AUDIO-DEBUG] Playing audio element:', el)
      // Call play() immediately (synchronously) to preserve user gesture
      const playPromise = el.play()

      // Handle the promise asynchronously after starting playback
      return playPromise.then(() => {
        console.log('[AUDIO-DEBUG] Audio element played successfully')
        return true
      }).catch((err) => {
        console.error('[AUDIO-DEBUG] Audio element play failed:', err)
        return false
      })
    })

    // Close the modal immediately since we've initiated playback
    setAudioEnabled(true)
    setAudioError(null)

    // Track results asynchronously without blocking
    Promise.all(playPromises).then((results) => {
      console.log('[AUDIO-DEBUG] Play results:', results)
      const successCount = results.filter(r => r).length
      console.log(`[AUDIO-DEBUG] ${successCount}/${results.length} audio elements played`)
    })
  }

  // NOTE: Don't attempt automatic audio playback - browser autoplay policies
  // require user interaction. The modal will prompt for a click gesture.

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
      <DailyAudio
        onPlayFailed={handlePlayFailed}
        autoSubscribeActiveSpeaker={true}
      />
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
