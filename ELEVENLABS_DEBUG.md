# ElevenLabs WebSocket Debugging Guide

## Current Problem

**Symptoms:**
- TTFB (Time To First Byte) delays: 493s, 185s, 31s, 18s (should be <1s)
- Constant WebSocket reconnections: "connection closed, but with an error: no close frame received or sent"
- Context mismatches: "Ignoring message from unavailable context"
- Result: Silent audio streams

**Current Configuration:**
```python
ElevenLabsTTSService(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel
    model="eleven_turbo_v2",  # Fast model
)
```

---

## Step 1: Verify Account Status

### Check API Quota
1. Go to https://elevenlabs.io/app/subscription
2. Check:
   - [ ] Current plan tier (Free, Starter, Creator, Pro)
   - [ ] Character quota (used vs. available)
   - [ ] API request rate limits
   - [ ] Concurrent request limits

### Common Issues by Tier

**Free Tier:**
- 10,000 characters/month
- Very limited concurrent requests (1-2)
- Rate limiting likely if hitting quota

**Starter ($5/month):**
- 30,000 characters/month
- Better concurrency but still limited

**Pro ($22/month):**
- 100,000 characters/month
- Higher concurrency limits

### Check API Key
```bash
curl -X GET "https://api.elevenlabs.io/v1/user" \
  -H "xi-api-key: YOUR_API_KEY"
```

Expected response:
```json
{
  "subscription": {
    "tier": "...",
    "character_count": 1234,
    "character_limit": 10000,
    ...
  }
}
```

---

## Step 2: Test ElevenLabs API Directly

### Test API Response Time

```bash
time curl -X POST "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM/stream" \
  -H "xi-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is a test.",
    "model_id": "eleven_turbo_v2",
    "voice_settings": {
      "stability": 0.5,
      "similarity_boost": 0.75
    }
  }' \
  --output test_audio.mp3
```

**Expected:** Should complete in <2 seconds for short text
**Problem:** If takes >10 seconds, API is slow/rate limited

### Test WebSocket Connection

```python
# test_elevenlabs_websocket.py
import asyncio
import websockets
import json
import os

async def test_websocket():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = "21m00Tcm4TlvDq8ikWAM"
    model = "eleven_turbo_v2"

    url = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={model}"

    headers = {"xi-api-key": api_key}

    try:
        print("Connecting to ElevenLabs WebSocket...")
        start = asyncio.get_event_loop().time()

        async with websockets.connect(url, extra_headers=headers) as ws:
            connect_time = asyncio.get_event_loop().time() - start
            print(f"✅ Connected in {connect_time:.2f}s")

            # Send text
            message = {
                "text": "Hello, this is a test. ",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }

            send_start = asyncio.get_event_loop().time()
            await ws.send(json.dumps(message))
            print(f"✅ Sent text in {asyncio.get_event_loop().time() - send_start:.2f}s")

            # Wait for first audio chunk
            first_byte_start = asyncio.get_event_loop().time()
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            ttfb = asyncio.get_event_loop().time() - first_byte_start

            print(f"✅ First audio chunk received in {ttfb:.2f}s (TTFB)")
            print(f"   Chunk size: {len(response)} bytes")

            if ttfb > 2.0:
                print(f"⚠️  WARNING: TTFB is high ({ttfb:.2f}s)")

            # Close properly
            await ws.send(json.dumps({"text": ""}))
            await ws.close()

    except asyncio.TimeoutError:
        print("❌ TIMEOUT: No response within 5 seconds")
    except websockets.exceptions.WebSocketException as e:
        print(f"❌ WebSocket error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(test_websocket())
```

Run this:
```bash
cd /Users/noahraford/Projects/boswell
ELEVENLABS_API_KEY=your_key uv run python test_elevenlabs_websocket.py
```

**Expected Results:**
- Connect: <0.5s
- Send: <0.1s
- TTFB: <1s

**Problem Indicators:**
- Connect >2s: Network or API slow
- TTFB >5s: Rate limiting or API overload
- Timeout: API not responding

---

## Step 3: Add Comprehensive Logging

### Enhanced ElevenLabs Logging

Add this to your pipeline to track timing:

```python
# In src/boswell/voice/pipeline.py

import time
import logging

logger = logging.getLogger(__name__)

class ElevenLabsMetricsWrapper(FrameProcessor):
    """Track ElevenLabs performance metrics."""

    def __init__(self, tts_service):
        super().__init__()
        self.tts = tts_service
        self.request_count = 0
        self.total_ttfb = 0
        self.max_ttfb = 0
        self.errors = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TextFrame):
            self.request_count += 1
            start_time = time.time()

            logger.info(
                f"[ELEVENLABS-METRIC] Request #{self.request_count}: "
                f"'{frame.text[:50]}...'"
            )

        # Monitor for TTS completion
        if isinstance(frame, TTSStartedFrame):
            elapsed = time.time() - start_time if 'start_time' in locals() else 0
            logger.info(f"[ELEVENLABS-METRIC] TTS started after {elapsed:.2f}s")

        if isinstance(frame, AudioRawFrame):
            # First audio frame = TTFB
            if not hasattr(self, '_got_first_audio'):
                ttfb = time.time() - start_time if 'start_time' in locals() else 0
                self.total_ttfb += ttfb
                self.max_ttfb = max(self.max_ttfb, ttfb)

                logger.info(
                    f"[ELEVENLABS-METRIC] TTFB: {ttfb:.2f}s "
                    f"(avg: {self.total_ttfb/self.request_count:.2f}s, "
                    f"max: {self.max_ttfb:.2f}s)"
                )

                if ttfb > 5.0:
                    logger.warning(
                        f"[ELEVENLABS-METRIC] ⚠️  High TTFB detected: {ttfb:.2f}s"
                    )

                self._got_first_audio = True

        await self.push_frame(frame, direction)
```

Then wrap your TTS service:
```python
# After creating tts service
tts = ElevenLabsTTSService(...)
tts_metrics = ElevenLabsMetricsWrapper(tts)

# Use tts_metrics in pipeline instead of tts directly
```

---

## Step 4: Network & Infrastructure Checks

### Check Railway → ElevenLabs Latency

From Railway, test ping to ElevenLabs:
```bash
# SSH into Railway or check from similar location
ping api.elevenlabs.io

# Or test with curl timing
curl -w "@curl-format.txt" -o /dev/null -s "https://api.elevenlabs.io/v1/user" \
  -H "xi-api-key: YOUR_KEY"
```

Create `curl-format.txt`:
```
    time_namelookup:  %{time_namelookup}\n
       time_connect:  %{time_connect}\n
    time_appconnect:  %{time_appconnect}\n
   time_pretransfer:  %{time_pretransfer}\n
      time_redirect:  %{time_redirect}\n
 time_starttransfer:  %{time_starttransfer}\n
                    ----------\n
         time_total:  %{time_total}\n
```

**Expected:** time_starttransfer <500ms
**Problem:** >2s indicates network issues

### Check Railway Region

ElevenLabs API servers are primarily in:
- US East (main)
- EU West (secondary)

If Railway is far from these regions, latency will be high. Consider:
1. Deploying Railway app in `us-east` region
2. Using a CDN/proxy closer to ElevenLabs

---

## Step 5: Configuration Optimizations

### Optimize ElevenLabs Settings

```python
tts = ElevenLabsTTSService(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",
    model="eleven_turbo_v2",
    # Add these optimizations:
    optimize_streaming_latency=3,  # 0-4, higher = lower latency
    output_format="pcm_16000",     # Match Daily.co sample rate
)
```

### Reduce Text Chunks

The logs show Claude generating long responses:
```
Generating TTS [I'm here to conduct your EMIR onboarding interview to help us get to know you better and match you with the right opportunities.]
```

Split long text into smaller chunks for faster TTFB:
```python
# In your pipeline, before TTS
class TextChunker(FrameProcessor):
    """Split long text into smaller chunks for faster TTS."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TextFrame):
            text = frame.text

            # Split on sentence boundaries if text is long
            if len(text) > 100:
                sentences = text.split('. ')
                for sentence in sentences:
                    if sentence.strip():
                        await self.push_frame(
                            TextFrame(text=sentence.strip() + '. '),
                            direction
                        )
            else:
                await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)
```

---

## Step 6: Implement Retry & Fallback

### Add Exponential Backoff

```python
# In pipeline setup
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

class ResilientElevenLabsTTS(ElevenLabsTTSService):
    """ElevenLabs with retry logic."""

    def __init__(self, *args, max_retries=3, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_retries = max_retries

    async def run_tts(self, text: str):
        for attempt in range(self.max_retries):
            try:
                return await super().run_tts(text)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"ElevenLabs attempt {attempt+1} failed: {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"ElevenLabs failed after {self.max_retries} attempts")
                    raise

# Use it
tts = ResilientElevenLabsTTS(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",
    model="eleven_turbo_v2",
    max_retries=3,
)
```

### Add Timeout Protection

```python
import asyncio

class TimeoutElevenLabsTTS(ElevenLabsTTSService):
    """ElevenLabs with timeout protection."""

    def __init__(self, *args, timeout=10.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    async def run_tts(self, text: str):
        try:
            return await asyncio.wait_for(
                super().run_tts(text),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.error(
                f"ElevenLabs TTS timed out after {self.timeout}s for: {text[:50]}"
            )
            # Return empty audio or skip
            return []

tts = TimeoutElevenLabsTTS(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",
    model="eleven_turbo_v2",
    timeout=10.0,  # 10 second max
)
```

---

## Step 7: Monitor in Production

### Add Health Check Endpoint

```python
# In src/boswell/server/routes/admin.py

from datetime import datetime, timedelta

elevenlabs_health = {
    "last_success": None,
    "last_failure": None,
    "total_requests": 0,
    "failed_requests": 0,
    "avg_ttfb": 0.0,
}

@router.get("/health/elevenlabs")
async def elevenlabs_health_check():
    """Check ElevenLabs service health."""

    # Calculate success rate
    if elevenlabs_health["total_requests"] > 0:
        success_rate = (
            1 - elevenlabs_health["failed_requests"] / elevenlabs_health["total_requests"]
        ) * 100
    else:
        success_rate = 0

    # Check if recently failed
    is_healthy = True
    if elevenlabs_health["last_failure"]:
        if datetime.now() - elevenlabs_health["last_failure"] < timedelta(minutes=5):
            is_healthy = False

    return {
        "status": "healthy" if is_healthy else "degraded",
        "success_rate": f"{success_rate:.1f}%",
        "avg_ttfb": f"{elevenlabs_health['avg_ttfb']:.2f}s",
        "last_success": elevenlabs_health["last_success"],
        "last_failure": elevenlabs_health["last_failure"],
        "total_requests": elevenlabs_health["total_requests"],
        "failed_requests": elevenlabs_health["failed_requests"],
    }
```

Monitor this endpoint: `https://web-production-f10c.up.railway.app/health/elevenlabs`

---

## Step 8: Alternative Approaches

If ElevenLabs continues to have issues:

### 1. Use HTTP API Instead of WebSocket

HTTP might be more reliable:
```python
# Switch from streaming WebSocket to HTTP requests
tts = ElevenLabsTTSService(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",
    model="eleven_turbo_v2",
    streaming=False,  # Use HTTP instead of WebSocket
)
```

Trade-off: Higher latency but more reliable.

### 2. Pre-generate Common Phrases

Cache TTS for common greetings:
```python
# Pre-generate and cache
CACHED_AUDIO = {
    "Hi, I'm Boswell.": "cached_greeting.mp3",
    "Ready?": "cached_ready.mp3",
}

class CachedTTS(FrameProcessor):
    """Use cached audio for common phrases."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TextFrame):
            if frame.text in CACHED_AUDIO:
                # Load cached audio
                audio_data = load_cached_audio(CACHED_AUDIO[frame.text])
                await self.push_frame(AudioRawFrame(audio=audio_data), direction)
            else:
                # Generate live
                await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)
```

### 3. Use Multilevel Caching

Implement TTL cache with Redis/local storage.

---

## Debugging Checklist

Run through this checklist:

### Account & API
- [ ] Check ElevenLabs dashboard for quota
- [ ] Verify API key is valid
- [ ] Check account tier (Free vs. Paid)
- [ ] Review recent usage/bills

### Network
- [ ] Test API latency from Railway
- [ ] Check Railway region vs. ElevenLabs location
- [ ] Test WebSocket connection directly
- [ ] Monitor for packet loss

### Configuration
- [ ] Verify voice_id exists
- [ ] Confirm model is available on tier
- [ ] Try `optimize_streaming_latency=3`
- [ ] Match output format to Daily.co

### Code
- [ ] Add comprehensive logging
- [ ] Implement timeout protection
- [ ] Add retry logic
- [ ] Split long text into chunks

### Monitoring
- [ ] Set up health check endpoint
- [ ] Track TTFB metrics
- [ ] Alert on high failure rate
- [ ] Log all WebSocket errors

---

## Expected vs. Actual Performance

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Connection time | <0.5s | ? | ❓ Test needed |
| TTFB | <1s | 31-493s | ❌ CRITICAL |
| WebSocket stability | No drops | Constant reconnects | ❌ CRITICAL |
| Success rate | >95% | Unknown | ❓ Monitor needed |

---

## Contact ElevenLabs Support

If issues persist after trying above:

1. **Collect data** (24-hour period):
   - Total requests
   - Failed requests
   - Average TTFB
   - Example failed request logs

2. **Email support**: support@elevenlabs.io
   - Include account email
   - Attach logs showing TTFB delays
   - Mention "WebSocket reconnection loop"
   - Request priority queue or different endpoint

3. **Check status page**: https://status.elevenlabs.io/

---

## Next Steps

1. Start with **Step 1** (verify account) - takes 2 minutes
2. Run **Step 2** (test WebSocket) - takes 5 minutes
3. Add **Step 3** (logging) - takes 15 minutes
4. If still broken, try **Step 5** (optimizations) - takes 30 minutes

Report back with results from Steps 1 & 2 and we'll continue debugging!
