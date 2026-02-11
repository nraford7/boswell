import { useEffect, useRef, useState } from 'react'
import { useDaily, useMeetingState, DailyAudio } from '@daily-co/daily-react'
import { LoadingScreen } from './LoadingScreen'
import { BoswellBranding } from './BoswellBranding'
import { Controls } from './Controls'

interface RoomProps {
  thankYouUrl: string
}

type CountdownState = '3' | '2' | '1' | 'dots' | 'fading' | 'done'

interface DisplayQuestion {
  text: string
  summary?: string
}

function normalizeQuestionSentence(text: string): string {
  const cleaned = text.trim().replace(/\s+/g, ' ').replace(/[.!\s]+$/, '')
  if (!cleaned) return ''
  return cleaned.endsWith('?') ? cleaned : `${cleaned}?`
}

export function Room({ thankYouUrl }: RoomProps) {
  const daily = useDaily()
  const meetingState = useMeetingState()
  const [countdown, setCountdown] = useState<CountdownState>('3')
  const [currentQuestion, setCurrentQuestion] = useState<DisplayQuestion | null>(null)
  const [questionVisible, setQuestionVisible] = useState(false)
  const questionChangeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rafIdRef = useRef<number | null>(null)
  const currentQuestionRef = useRef<string | null>(null)

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

  useEffect(() => {
    return () => {
      if (questionChangeTimer.current) {
        clearTimeout(questionChangeTimer.current)
      }
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
      }
    }
  }, [])

  // Listen for question updates from Boswell
  useEffect(() => {
    if (!daily) return

    const transitionToQuestion = (nextQuestion: string, summary?: string) => {
      if (questionChangeTimer.current) {
        clearTimeout(questionChangeTimer.current)
        questionChangeTimer.current = null
      }

      if (nextQuestion === currentQuestionRef.current) return

      if (!currentQuestionRef.current) {
        currentQuestionRef.current = nextQuestion
        setCurrentQuestion({ text: nextQuestion, summary })
        setQuestionVisible(false)
        // Ensure CSS transition runs after mount.
        rafIdRef.current = requestAnimationFrame(() => {
          setQuestionVisible(true)
          rafIdRef.current = null
        })
        return
      }

      setQuestionVisible(false)
      questionChangeTimer.current = setTimeout(() => {
        currentQuestionRef.current = nextQuestion
        setCurrentQuestion({ text: nextQuestion, summary })
        setQuestionVisible(true)
        questionChangeTimer.current = null
      }, 200)
    }

    const handleAppMessage = (event: any) => {
      const payload = event?.data
      if (!payload || typeof payload !== 'object') return

      if (payload.type && payload.type !== 'display-question') return

      const rawQuestion = typeof payload.question === 'string'
        ? payload.question
        : typeof payload.summary === 'string'
          ? payload.summary
          : ''
      const normalizedQuestion = normalizeQuestionSentence(rawQuestion)
      if (!normalizedQuestion) return

      const summary = typeof payload.summary === 'string'
        ? normalizeQuestionSentence(payload.summary)
        : undefined

      transitionToQuestion(normalizedQuestion, summary)
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
        <div
          className={`current-question ${
            questionVisible ? 'current-question-visible' : 'current-question-hidden'
          } ${
            currentQuestion.text.length > 200
              ? 'current-question-xlong'
              : currentQuestion.text.length > 140
                ? 'current-question-long'
                : currentQuestion.text.length > 100
                  ? 'current-question-medium'
                  : ''
          }`}
        >
          {currentQuestion.text.length > 250 && currentQuestion.summary
            ? currentQuestion.summary
            : currentQuestion.text}
        </div>
      )}
      <Controls />
    </div>
  )
}
