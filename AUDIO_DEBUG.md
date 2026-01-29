# Audio Pipeline Debug - Final Report

**Date:** January 29, 2026
**Status:** ✅ RESOLVED
**Root Cause:** Incorrect `FrameProcessor` pattern in `AudioDiagnosticsProcessor`

---

## Problem Summary

Bot audio was not playing for guests in interview rooms despite:
- ElevenLabs TTS responding successfully (TTFB ~0.2s)
- Server logs showing 7+ MB of audio data "sent"
- Daily.co WebRTC connection stable (0% packet loss)
- Client showing track subscribed and playable

Web Audio API analysis confirmed the audio stream contained **digital silence** (all samples at 128, the PCM center value).

---

## Root Cause

The `AudioDiagnosticsProcessor` was using an incorrect pattern for Pipecat's `FrameProcessor`:

**Broken code:**
```python
async def process_frame(self, frame: Frame, direction: FrameDirection):
    # ... logging logic ...

    # WRONG: Only pushing frames, not handling system frames
    await self.push_frame(frame, direction)
```

This caused `StartFrame` to not be properly handled, which resulted in Pipecat's base `FrameProcessor` class rejecting all subsequent frames with the error:

```
ERROR | AudioDiagnosticsProcessor#13 Trying to process UserAudioRawFrame but StartFrame not received yet
```

---

## Solution

The correct Pipecat `FrameProcessor` pattern requires **both** steps:

```python
async def process_frame(self, frame: Frame, direction: FrameDirection):
    # ... logging logic ...

    # 1. Handle system frames (StartFrame, EndFrame, etc.)
    await super().process_frame(frame, direction)

    # 2. Forward all frames to next processor
    await self.push_frame(frame, direction)
```

---

## Debugging Methodology

Used isolated pipeline testing to identify the exact failure point:

| Phase | Pipeline Configuration | Result |
|-------|----------------------|--------|
| 1 | `TTS → transport.output()` | ✅ Audio works |
| 2 | `transport.input() → TTS → transport.output()` | ✅ Audio works |
| 3 | `transport.input() → TTS → BrokenProcessor → transport.output()` | ❌ Silent |
| 4 | Same as 3, but processor only calls `super().process_frame()` | ❌ Silent (frames not forwarded) |
| 5 | Same as 3, but processor calls both `super()` AND `push_frame()` | ✅ Audio works |

This systematic approach proved the issue was specifically in the custom processor's frame handling pattern.

---

## Files Changed

### Server-side fix
**`src/boswell/voice/audio_diagnostics.py`**
```diff
-        await self.push_frame(frame, direction)
+        await super().process_frame(frame, direction)
+        await self.push_frame(frame, direction)
```

### Client-side cleanup
**`room-ui/src/components/Room.tsx`**
- Removed "Enable Audio" button/modal (was added during debugging)
- Removed debug console logging
- Removed unused state variables

---

## Verification

After deploying the fix:
1. ElevenLabs TTFB: ~0.2-0.4s (excellent)
2. Audio frames flow through pipeline correctly
3. Guests hear Boswell speak in interview rooms
4. No more `StartFrame not received` errors in logs

---

## Lessons Learned

### Pipecat FrameProcessor Pattern

When creating custom `FrameProcessor` subclasses in Pipecat:

```python
class MyProcessor(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # 1. Your custom logic here (logging, transformation, etc.)
        if isinstance(frame, SomeFrameType):
            # do something

        # 2. ALWAYS call super() to handle system frames
        await super().process_frame(frame, direction)

        # 3. ALWAYS push frames to continue pipeline flow
        await self.push_frame(frame, direction)
```

**Why both are needed:**
- `super().process_frame()` - Handles `StartFrame`, `EndFrame`, `InterruptionFrame`, and other system frames that control processor lifecycle
- `self.push_frame()` - Forwards the frame to the next processor in the pipeline

**Skipping either causes failure:**
- Without `super()`: System frames not handled → processor rejects all frames
- Without `push_frame()`: Frames not forwarded → pipeline stops flowing

### Other Boswell Processors

All other Boswell processors (`AcknowledgmentProcessor`, `StrikeControlProcessor`, `SpeedControlProcessor`, `ModeDetectionProcessor`, `TranscriptCollector`, `BotResponseCollector`) were already using the correct pattern.

---

## Test Files

The following test files were created in the worktree during debugging and can be used for future pipeline testing:

- `test_minimal_pipeline.py` - Phase 1: TTS only
- `test_phase2_bidirectional.py` - Phase 2: With transport.input()
- `test_phase3_with_diagnostics.py` - Phase 3: Broken processor
- `test_phase4_fixed_processor.py` - Phase 4: Partial fix attempt
- `test_phase5_correct_fix.py` - Phase 5: Correct fix

Located in: `.worktrees/audio-pipeline-rebuild/`

---

## Related Issues

### ElevenLabs Quota (Separate Issue)
During debugging, we also discovered the user had hit a self-imposed monthly spending limit on ElevenLabs (1,000 credits), causing extreme TTFB delays (493s). This was resolved by increasing the limit to 100,000 credits.

### Browser Autoplay Policy
The "Enable Audio" button was initially added thinking the issue was browser autoplay policy. After fixing the server-side issue, this button was removed as Daily.co's `DailyAudio` component handles autoplay automatically.

---

## Commits

1. `e02f1b7` - fix(voice): correct FrameProcessor pattern to fix silent audio
2. `4815565` - refactor(room-ui): remove audio gate and debug logging
