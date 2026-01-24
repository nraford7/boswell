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
