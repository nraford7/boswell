# Audio Debugging - Systematic Investigation

## Problem Statement
Audio from the voice agent (bot) is not playing in the interview room, despite:
- Bot joining the room successfully
- Bot speaking events firing ("Bot started speaking", "Bot stopped speaking")
- ElevenLabs TTS generating audio
- Pipeline configured correctly with `vad_audio_passthrough=True`

## Root Cause Investigation (Phase 1)

### Evidence Gathered

#### Server-Side (Pipeline)
1. ✅ **Daily Transport Configuration** (pipeline.py:72-84)
   - `audio_out_enabled=True`
   - `vad_audio_passthrough=True` (added in commit 7759128)
   - Bot joins with owner token (`is_owner=True`)

2. ✅ **Audio Pipeline Flow** (pipeline.py:153-170)
   ```
   TTS → AudioDiagnostics → DailyOutputTransport
   ```

3. ⚠️ **ElevenLabs WebSocket Instability**
   - Logs show: "connection closed, but with an error: no close frame received or sent"
   - Service reconnects but may be losing audio frames

4. ⚠️ **Very Short Speaking Duration**
   - Bot speaking events only ~800ms apart
   - Suggests audio might not be fully transmitted OR client not receiving

#### Client-Side (room-ui)
1. ✅ **Audio Gate Implemented** (Room.tsx:113-124)
   - Click-to-enable modal handles browser autoplay policy
   - Calls `daily.startAudio()` or falls back to `audio.play()`

2. ⚠️ **DailyAudio Component** (Room.tsx:109)
   - Uses `<DailyAudio>` component to handle audio playback
   - **Missing**: `autoSubscribeActiveSpeaker` prop (defaults to `false`)
   - **Issue**: Component only subscribes to tracks if either:
     - `autoSubscribeActiveSpeaker=true`, OR
     - Daily instance has `subscribeToTracksAutomatically()=true`

3. ⚠️ **No Explicit Track Subscription**
   - No calls to `daily.updateParticipant()` with `setSubscribedTracks`
   - Relying on Daily.co defaults

## Root Cause Hypothesis

**Primary Hypothesis**: The `DailyAudio` component is not subscribing to the bot participant's audio track.

**Why**:
- The `DailyAudio` component in @daily-co/daily-react only renders audio elements for **subscribed** tracks
- If `autoSubscribeActiveSpeaker=false` (default) AND `subscribeToTracksAutomatically()=false`, tracks are never subscribed
- Even if `subscribeToTracksAutomatically()=true` (Daily.co default), there may be a timing issue where the bot joins before the client is ready

**Evidence from DailyAudio source** (node_modules/@daily-co/daily-react/src/components/DailyAudio.tsx:162-177):
```typescript
if (!isSubscribed(sessionId)) {
  if (
    daily &&
    !daily.isDestroyed() &&
    autoSubscribeActiveSpeaker &&  // ← defaults to FALSE
    !daily.subscribeToTracksAutomatically()
  ) {
    daily.updateParticipant(sessionId, {
      setSubscribedTracks: { audio: true },
    });
  } else {
    return;  // ← SKIPS rendering audio element
  }
}
```

## Changes Made for Testing

### 1. Server-Side Diagnostics (NEW)

**File**: `src/boswell/voice/audio_diagnostics.py`
- Created `AudioDiagnosticsProcessor` to log frame flow
- Tracks:
  - Text frames from LLM
  - TTS started/stopped events
  - Audio raw frames (with byte counts)

**Modified**: `src/boswell/voice/pipeline.py`
- Added `AudioDiagnosticsProcessor` before `transport.output()`
- Added logging for Daily transport configuration
- Pipeline now: `tts → audio_diagnostics → transport.output()`

**Expected Output**:
```
[AUDIO-DIAG] Daily transport configured: audio_in=True, audio_out=True, vad_passthrough=True
[AUDIO-DIAG] TextFrame #1: 'Hello, I'm Boswell...'
[AUDIO-DIAG] TTSStartedFrame #1
[AUDIO-DIAG] AudioRawFrame #10: 3840 bytes (total: 38,400 bytes)
[AUDIO-DIAG] TTSStoppedFrame #1
```

### 2. Client-Side Diagnostics (MODIFIED)

**File**: `room-ui/src/components/Room.tsx`

**Changes**:
1. **Added `autoSubscribeActiveSpeaker={true}`** to `<DailyAudio>` (line 109-112)
   - Forces subscription to active speaker's audio even if `subscribeToTracksAutomatically=false`

2. **Enhanced participant logging** (lines 20-34)
   - Logs track subscription status for each participant
   - Logs `subscribeToTracksAutomatically()` setting
   - Shows audio track state (subscribed, state)

3. **Added track event listeners** (lines 49-75)
   - Logs `track-started` events
   - Logs `participant-updated` events with audio status
   - Helps identify when tracks are added/subscribed

**Expected Output**:
```
[AUDIO-DEBUG] Participant Boswell: {
  local: false,
  audioTrack: { subscribed: true, state: 'playable' },
  audioSubscribed: true,
  audioState: 'playable'
}
[AUDIO-DEBUG] subscribeToTracksAutomatically: true
[AUDIO-DEBUG] track-started: { participant: { ... }, track: 'audio' }
[AUDIO-DEBUG] participant-updated with audio: {
  participant: 'Boswell',
  audioSubscribed: true,
  audioState: 'playable'
}
```

## Testing Instructions

### 1. Start the Server & Worker

Terminal 1 (Web):
```bash
cd /Users/noahraford/Projects/boswell
uv run python -m boswell.server.main
```

Terminal 2 (Worker):
```bash
cd /Users/noahraford/Projects/boswell
uv run python -m boswell.server.worker
```

### 2. Start an Interview

1. Navigate to admin dashboard: `http://localhost:8000/admin`
2. Create or select a project with questions
3. Add a guest and start interview
4. Click the guest interview link to join the room
5. Click "Enable Audio" when prompted

### 3. Check Server Logs

Look for:
- ✅ `[AUDIO-DIAG] Daily transport configured: audio_in=True, audio_out=True, vad_passthrough=True`
- ✅ `[AUDIO-DIAG] TextFrame #N: '...'` (LLM is generating responses)
- ✅ `[AUDIO-DIAG] TTSStartedFrame #N` (TTS is starting)
- ✅ `[AUDIO-DIAG] AudioRawFrame #N: X bytes` (Audio is being generated)
- ❌ ElevenLabs websocket errors (indicates TTS instability)

### 4. Check Browser Console Logs

Look for:
- ✅ `[AUDIO-DEBUG] subscribeToTracksAutomatically: true` (or false)
- ✅ `[AUDIO-DEBUG] Participant Boswell: { audioSubscribed: true, audioState: 'playable' }`
- ✅ `[AUDIO-DEBUG] track-started: ...` (bot's audio track started)
- ❌ `audioSubscribed: false` (track not subscribed)
- ❌ `audioState: 'off'` or `'blocked'` (track not playable)
- ❌ Audio play failed errors

## Interpretation Guide

### Scenario 1: Server Shows Audio, Client Shows audioSubscribed: false
**Diagnosis**: Track subscription issue
**Fix**: The `autoSubscribeActiveSpeaker={true}` change should fix this

### Scenario 2: Server Shows Audio, Client Shows audioSubscribed: true, Still No Sound
**Diagnosis**: Browser autoplay or audio playback issue
**Fix**: Check browser console for play() errors, verify audio gate was clicked

### Scenario 3: Server Shows No AudioRawFrames
**Diagnosis**: TTS not generating audio OR frames blocked in pipeline
**Fix**: Check ElevenLabs API status, quota, and websocket errors

### Scenario 4: Server Shows Short Speaking Durations (~800ms)
**Diagnosis**: LLM generating very short responses OR audio chunking issue
**Fix**: Check TextFrame content in logs, verify system prompt is working

### Scenario 5: ElevenLabs Websocket Errors
**Diagnosis**: Rate limiting or API instability
**Fix**: Check ElevenLabs dashboard for quota/usage

## Next Steps

After testing with diagnostics:

1. **If `autoSubscribeActiveSpeaker={true}` fixes it**:
   - Keep the change, remove verbose logging
   - Document why it's needed
   - Consider also adding explicit `daily.updateParticipant()` subscription

2. **If still not working**:
   - Review all diagnostic logs
   - Check Daily.co dashboard for room activity
   - Test joining the room directly from Daily.co to verify server is sending audio
   - Consider adding explicit track subscription in useEffect

3. **If ElevenLabs is unstable**:
   - Consider implementing retry logic
   - Add buffering or queue management
   - Contact ElevenLabs support about websocket disconnections

## Related Files

### Server
- `src/boswell/voice/pipeline.py` - Pipeline setup with Daily transport
- `src/boswell/voice/audio_diagnostics.py` - NEW diagnostic processor
- `src/boswell/voice/bot.py` - Bot lifecycle and room creation
- `src/boswell/server/worker.py` - Worker that runs interviews

### Client
- `room-ui/src/components/Room.tsx` - Main room component with DailyAudio
- `room-ui/src/App.tsx` - DailyProvider setup

### Dependencies
- @daily-co/daily-react - React hooks and components for Daily.co
- @daily-co/daily-js - Core Daily.co JavaScript SDK
- pipecat-ai - Voice pipeline framework

## References

- [Daily.co DailyAudio Component](https://docs.daily.co/reference/daily-react/daily-audio)
- [Daily.co Track Subscription](https://docs.daily.co/reference/daily-js/instance-methods/set-subscribe-to-tracks-automatically)
- [Daily.co Audio-Only Guide](https://docs.daily.co/guides/products/audio-only)
