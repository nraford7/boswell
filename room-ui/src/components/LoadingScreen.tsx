export function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="loading-glow" />
      <div className="loading-logo">Boswell</div>
      <div className="loading-spinner" />
      <p className="loading-text">Connecting to interview room...</p>
    </div>
  )
}
