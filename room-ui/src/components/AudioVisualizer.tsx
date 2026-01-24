import { useState, useCallback } from 'react'
import { useAppMessage } from '@daily-co/daily-react'
import type { DailyEventObjectAppMessage } from '@daily-co/daily-js'

interface SpeakingStateMessage {
  type: 'speaking_state'
  speaking: boolean
}

export function AudioVisualizer() {
  const [isSpeaking, setIsSpeaking] = useState(false)

  // Listen for speaking state messages from the bot
  useAppMessage({
    onAppMessage: useCallback((event: DailyEventObjectAppMessage) => {
      const data = event.data as SpeakingStateMessage
      if (data?.type === 'speaking_state') {
        setIsSpeaking(data.speaking)
      }
    }, []),
  })

  return (
    <div className={`audio-visualizer ${isSpeaking ? 'speaking' : 'idle'}`}>
      <div className="audio-orb">
        <div className="audio-orb-inner" />
        {isSpeaking && (
          <>
            <div className="audio-ring" />
            <div className="audio-ring delay-1" />
            <div className="audio-ring delay-2" />
          </>
        )}
      </div>
    </div>
  )
}
