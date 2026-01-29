# Audio Debugging Session - Findings

**Date:** January 29, 2026
**Issue:** Bot audio not playing for guests in interview rooms
**Status:** ⚠️ Root cause identified - silent audio frames

---

## Executive Summary

After systematic debugging, we identified that the WebRTC pipeline is working correctly, but **the audio frames being sent are silent** (digital silence: 128/128). The issue is in the server-side Pipecat pipeline, specifically with ElevenLabs TTS not generating actual audio data, despite sending frame metadata.

---

## Debugging Process

### Phase 1: Client-Side Investigation

**Initial Problem:**
- "Enable Audio" button modal wasn't appearing
- When it appeared, clicking it did nothing

**Fixes Applied:**
1. ✅ **Removed automatic audio playback attempt** - The `useEffect` was calling `startAudioPlayback()` on join, setting `audioEnabled=true` immediately and hiding the modal
2. ✅ **Made audio playback synchronous** - Changed from `async/await` to synchronous `el.play()` calls to preserve browser user gesture context
3. ✅ **Added comprehensive logging** - Added `[AUDIO-DEBUG]` logs throughout the client

**Client-Side Results:**
- ✅ Modal shows correctly
- ✅ Modal closes when clicked
- ✅ Audio elements found: 5 total
- ✅ Audio elements playing: 2 successfully started
- ✅ Bot participant "Boswell" joined with `audioSubscribed: true, audioState: 'playable'`

### Phase 2: Server-Side Investigation

**Pipeline Status:**
```
Daily Transport → Deepgram STT → Claude LLM → ElevenLabs TTS →
AudioDiagnostics → DailyOutputTransport
```

**Server Logs Analysis:**
- ✅ Bot successfully joined Daily.co room
- ✅ Daily transport configured: `audio_out=True`, `vad_audio_passthrough=True`
- ✅ **11,030 AudioRawFrames sent** (7+ MB of data)
- ✅ TextFrames received from Claude LLM
- ✅ TTSStartedFrame and TTSStoppedFrame events firing
- ⚠️ **ElevenLabs WebSocket instability mentioned in earlier logs**

**Daily.co Dashboard:**
- ✅ Bot participant "Boswell" connected
- ✅ 0% packet loss (both sending and receiving)
- ✅ Duration: 2-5 minutes
- ✅ Connection stable throughout

### Phase 3: Audio Signal Analysis

**WebRTC Connection Test:**
```javascript
// Checked MediaStreamTrack
Track 0: {
  id: 'b489c3bd-22a3-4abd-8ac2-367504ec60c1',
  kind: 'audio',
  enabled: true,
  muted: false,
  readyState: 'live'
}
```
Result: ✅ Track is live and enabled

**Audio Element Test:**
```javascript
Audio 1 (Boswell): {
  paused: false,
  muted: false,
  volume: 1,
  hasSource: true,
  sessionId: 'ef2f60cd-6f59-467a-bf7c-1ab4e5036a01'
}
```
Result: ✅ Element configured correctly

**Audio Signal Analysis (Web Audio API):**
```javascript
Audio level: 0 max: 128 min: 128
```
Result: ❌ **SILENT STREAM - Digital silence (no audio data)**

---

## Root Cause

**The audio frames being transmitted are silent.**

Despite the server sending 7+ MB of audio data (11,030 frames), the actual audio signal is **flat at 128** (the center value representing digital silence). This means:

1. ✅ WebRTC pipeline is working (frames are transmitted)
2. ✅ Client subscription is working (tracks are subscribed)
3. ❌ **Audio frames contain no actual sound data**

**CONFIRMED Root Cause: ElevenLabs WebSocket Instability**

Railway worker logs reveal the exact problem:

1. **Extremely High TTFB (Time To First Byte)**
   ```
   TTFB: 493.37033581733704  (493 seconds!)
   TTFB: 185.71466541290283  (185 seconds!)
   TTFB: 31.15135145187378   (31 seconds)
   TTFB: 18.855751276016235  (18 seconds)
   ```
   The first audio byte takes **minutes** to arrive instead of milliseconds.

2. **Constant WebSocket Reconnections**
   ```
   WARNING | ElevenLabsTTSService#11 connection closed, but with an error: no close frame received or sent
   WARNING | ElevenLabsTTSService#11 reconnecting, attempt 1
   INFO    | ElevenLabsTTSService#11 reconnected successfully on attempt 1
   ```
   WebSocket connections are dropping and reconnecting constantly.

3. **Context Mismatches**
   ```
   DEBUG | Ignoring message from unavailable context: 8dd61920-2ca9-4b39-85ff-40d196a0534b
   ```
   Audio frames arriving from old/stale contexts being ignored.

4. **TTS Text is Generated Correctly**
   ```
   DEBUG | ElevenLabsTTSService#11: Generating TTS [Hi sd, I'm Boswell.]
   ```
   Claude is generating responses and sending them to TTS successfully.

**What's Happening:**
- Claude generates text responses correctly
- ElevenLabs TTS receives the text
- WebSocket connection is unstable, causing massive delays (minutes!)
- By the time audio arrives, it's either stale, dropped, or the context has changed
- Result: Silent frames or no frames at all reach the client

**Likely Causes:**
- ElevenLabs API rate limiting or quota issues
- Network instability between Railway and ElevenLabs servers
- ElevenLabs service degradation
- Account tier limitations (free/starter tier throttling)

---

## Evidence Summary

| Component | Status | Evidence |
|-----------|--------|----------|
| Client UI | ✅ Working | Modal shows, closes on click |
| Browser Audio Policy | ✅ Working | User gesture preserved, play() succeeds |
| Daily.co Connection | ✅ Working | 0% packet loss, stable connection |
| Track Subscription | ✅ Working | `audioSubscribed: true` |
| MediaStreamTrack | ✅ Working | `readyState: 'live'` |
| Audio Element | ✅ Working | Playing, unmuted, full volume |
| WebRTC Transport | ✅ Working | 11,030 frames sent, 7+ MB |
| Pipecat Pipeline | ⚠️ Partial | Frames flowing but empty |
| **ElevenLabs TTS** | ❌ **FAILING** | **Silent audio data (128/128)** |

---

## Next Steps

### Immediate Actions

1. **Check ElevenLabs Dashboard**
   - Log into ElevenLabs account
   - Check API quota usage
   - Verify API key is valid
   - Check for service status/outages

2. **Review Railway Worker Logs**
   - Search for "ElevenLabs" errors
   - Look for WebSocket connection errors
   - Check for API quota/rate limit messages
   - Verify TTS model and voice ID configuration

3. **Test ElevenLabs API Directly**
   ```bash
   curl -X POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id} \
     -H "xi-api-key: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"text": "Test", "model_id": "eleven_turbo_v2"}' \
     --output test.mp3
   ```

### Configuration to Verify

**Current ElevenLabs Config** (from `src/boswell/voice/pipeline.py:95-99`):
```python
tts = ElevenLabsTTSService(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel voice
    model="eleven_turbo_v2",
)
```

**Check:**
- [ ] API key is valid and has quota remaining
- [ ] Voice ID "21m00Tcm4TlvDq8ikWAM" (Rachel) exists and is accessible
- [ ] Model "eleven_turbo_v2" is available on the account tier
- [ ] No rate limiting or usage caps hit
- [ ] WebSocket connection stable (no reconnection errors)

### Alternative Solutions

If ElevenLabs continues to have issues:

1. **Switch TTS Provider**
   - Try Cartesia TTS (faster, more reliable)
   - Try Azure TTS
   - Try Google Cloud TTS

2. **Add Retry Logic**
   - Implement exponential backoff for WebSocket reconnections
   - Add TTS fallback provider

3. **Add Audio Validation**
   - Check if audio frames are non-silent before sending
   - Log audio level statistics in AudioDiagnosticsProcessor
   - Alert if sending too many silent frames

---

## Technical Details

### Audio Signal Characteristics

**Expected Audio (speaking):**
```
Audio level: 50-200 max: 178-255 min: 0-100
```

**Actual Audio (silent):**
```
Audio level: 0 max: 128 min: 128
```

**Interpretation:**
- Max = Min = 128 → flat line at center value
- This is digital silence in PCM audio
- No waveform variation = no sound

### Pipeline Flow

```
Guest Speech → Daily.co Input Transport → Deepgram STT
    ↓
TranscriptCollector (captures guest speech)
    ↓
AcknowledgmentProcessor ("Mm-hmm")
    ↓
Claude LLM (generates response text)
    ↓
StrikeControlProcessor
    ↓
SpeedControlProcessor
    ↓
**ElevenLabs TTS** ← FAILING HERE (silent audio generated)
    ↓
AudioDiagnosticsProcessor (sees 11k frames, 7MB data)
    ↓
Daily.co Output Transport (sends frames)
    ↓
Guest Browser (receives frames but they're silent)
```

---

## Commits Made During Debugging

1. **8a5e951** - `fix(audio): enable track subscription and add diagnostics`
   - Added `autoSubscribeActiveSpeaker={true}`
   - Added client-side track subscription logging
   - Added server-side `AudioDiagnosticsProcessor`

2. **161b987** - `debug(room-ui): add comprehensive logging to startAudioPlayback`
   - Added detailed console logging for audio playback

3. **ede814c** - `fix(room-ui): prevent audio play promises from hanging`
   - Added 2s timeout to prevent Promise.all hanging

4. **a2e0d48** - `fix(room-ui): call audio.play() synchronously to preserve user gesture`
   - Made `startAudioPlayback()` synchronous
   - Preserved browser user gesture context

5. **db19871** - `fix(room-ui): remove automatic audio start to allow modal to show`
   - Removed automatic audio playback attempt
   - Always show modal for user interaction

---

## Files Modified

### Client-Side
- `room-ui/src/components/Room.tsx` - Audio gate modal and playback logic
- `src/boswell/server/static/room-ui/main.js` - Built output

### Server-Side
- `src/boswell/voice/pipeline.py` - Added logging, AudioDiagnosticsProcessor
- `src/boswell/voice/audio_diagnostics.py` - NEW: Frame flow diagnostics

### Documentation
- `claude.md` - NEW: Project overview
- `AUDIO_DEBUG.md` - NEW: Debugging guide
- `AUDIO_DEBUG_FINDINGS.md` - THIS FILE

---

## Conclusion

The systematic debugging revealed that **all components work except the actual audio generation**. The ElevenLabs TTS service is producing silent audio frames. This is likely due to:

1. **API quota exhaustion** (most likely if using free tier)
2. **WebSocket connection instability** (frames lost during transmission)
3. **Configuration issue** (wrong model, voice, or API key)

**Immediate fix:** Check ElevenLabs dashboard for quota/errors and review Railway logs for TTS-specific errors.

**Long-term fix:** Consider switching to a more reliable TTS provider (Cartesia, Azure, Google) or implementing retry/fallback logic.
