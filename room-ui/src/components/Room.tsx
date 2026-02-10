import { useEffect, useState } from 'react'
import { useDaily, useMeetingState, DailyAudio } from '@daily-co/daily-react'
import { LoadingScreen } from './LoadingScreen'
import { BoswellBranding } from './BoswellBranding'
import { Controls } from './Controls'

interface RoomProps {
  thankYouUrl: string
}

type CountdownState = '3' | '2' | '1' | 'dots' | 'fading' | 'done'

interface DisplayQuestion {
  summary: string
}

const summaryLeadPatterns = [
  /^(?:can|could|would|will|do|does|did|is|are|was|were|have|has|had)\s+you\s+/i,
  /^(?:please\s+)?(?:tell|walk|talk|take|describe|share|explain)\s+me(?:\s+through)?\s+/i,
  /^help\s+me\s+understand\s+/i,
]

const summaryPrefixSkipWords = new Set([
  'who', 'what', 'when', 'where', 'why', 'how', 'which',
  'can', 'could', 'would', 'will', 'do', 'does', 'did',
  'is', 'are', 'was', 'were', 'have', 'has', 'had',
  'tell', 'walk', 'talk', 'take', 'describe', 'share', 'explain',
  'please', 'me', 'through', 'about',
])

const summaryDropWords = new Set([
  'i', 'you', 'your', 'we', 'our', 'me', 'my',
  'the', 'a', 'an',
  'is', 'are', 'was', 'were', 'do', 'does', 'did',
  'can', 'could', 'would', 'will', 'have', 'has', 'had',
  'to', 'this', 'that', 'these', 'those',
])

const maxSummaryWords = 5

function summarizeQuestion(question: string): string {
  let text = question.trim().replace(/\s+/g, ' ').replace(/[?.!\s]+$/, '')
  if (!text) return question

  text = text.replace(/^(?:and|so|okay|ok|alright|great|thanks|thank you)[,\s]+/i, '').trim()
  for (const pattern of summaryLeadPatterns) {
    text = text.replace(pattern, '').trim()
  }

  const firstClause = text.split(/(?:,|;|\sand\s|\sor\s|\sbecause\s|\sso that\s)/i, 1)[0]?.trim()
  const summary = firstClause || text
  if (!summary) return question

  const words = summary.split(/\s+/).filter(Boolean)
  while (words.length > 0 && summaryPrefixSkipWords.has(words[0].toLowerCase())) {
    words.shift()
  }

  const filteredWords = words.filter((word) => !summaryDropWords.has(word.toLowerCase()))
  const selected = (filteredWords.length > 0 ? filteredWords : words).slice(0, maxSummaryWords)
  const pithy = selected.join(' ').trim()
  if (!pithy) return question

  return pithy.charAt(0).toUpperCase() + pithy.slice(1)
}

export function Room({ thankYouUrl }: RoomProps) {
  const daily = useDaily()
  const meetingState = useMeetingState()
  const [countdown, setCountdown] = useState<CountdownState>('3')
  const [currentQuestion, setCurrentQuestion] = useState<DisplayQuestion | null>(null)

  // Countdown sequence: 3 -> 2 -> 1 -> ... -> fade -> done
  // Total time: ~5 seconds to sync with server-side TTS delay
  useEffect(() => {
    if (meetingState !== 'joined-meeting') return

    const timers: ReturnType<typeof setTimeout>[] = []

    // 3 -> 2 after 1000ms
    timers.push(setTimeout(() => setCountdown('2'), 1000))
    // 2 -> 1 after 2000ms
    timers.push(setTimeout(() => setCountdown('1'), 2000))
    // 1 -> ... after 3000ms
    timers.push(setTimeout(() => setCountdown('dots'), 3000))
    // ... -> fading after 4000ms
    timers.push(setTimeout(() => setCountdown('fading'), 4000))
    // fading -> done after 5000ms (TTS should start now)
    timers.push(setTimeout(() => setCountdown('done'), 5000))

    return () => timers.forEach(clearTimeout)
  }, [meetingState])

  // Listen for question updates from Boswell
  useEffect(() => {
    if (!daily) return

    const handleAppMessage = (event: any) => {
      const payload = event?.data
      if (!payload || typeof payload !== 'object') return

      if (payload.type && payload.type !== 'display-question') return

      const question = typeof payload.question === 'string' ? payload.question.trim() : ''
      if (!question) return

      const summary = typeof payload.summary === 'string' && payload.summary.trim()
        ? payload.summary.trim()
        : summarizeQuestion(question)

      setCurrentQuestion({ summary })
    }

    daily.on('app-message', handleAppMessage)
    return () => {
      daily.off('app-message', handleAppMessage)
    }
  }, [daily])

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

  // Main room view
  return (
    <div className="room">
      <DailyAudio autoSubscribeActiveSpeaker={true} />
      <BoswellBranding />
      {countdown !== 'done' && (
        <div className={`countdown ${countdown === 'fading' ? 'countdown-fading' : ''}`}>
          <span className="countdown-text">
            {countdown === 'dots' || countdown === 'fading' ? '...' : countdown}
          </span>
        </div>
      )}
      {currentQuestion && (
        <div className="current-question">
          <div className="current-question-label">Current question</div>
          <div className="current-question-summary">{currentQuestion.summary}</div>
        </div>
      )}
      <Controls />
    </div>
  )
}
