# Display Question Text Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Display Boswell's current question on screen as a visual reminder for the guest.

**Architecture:** Create a new Pipecat processor that extracts question sentences from LLM responses and sends them to the frontend via Daily app messages. Frontend listens for these messages and displays the question text.

**Tech Stack:** Python/Pipecat (backend processor), Daily.co app messages (transport), React/TypeScript (frontend display)

---

### Task 1: Create DisplayTextProcessor

**Files:**
- Create: `src/boswell/voice/display_text.py`

**Step 1: Create the processor file**

```python
"""Display text processor for sending questions to frontend."""

import logging
import re

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class DisplayTextProcessor(FrameProcessor):
    """Extracts questions from LLM responses and sends to frontend.

    Captures complete LLM responses, extracts the question sentence
    (text ending with ?), and sends it via Daily transport app message.
    """

    def __init__(self, transport, **kwargs):
        """Initialize the processor.

        Args:
            transport: DailyTransport instance for sending app messages.
        """
        super().__init__(**kwargs)
        self._transport = transport
        self._current_text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames, accumulating text and sending questions."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            self._current_text += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            question = self._extract_question(self._current_text)
            if question:
                await self._send_question(question)
            self._current_text = ""

        await self.push_frame(frame, direction)

    def _extract_question(self, text: str) -> str | None:
        """Extract the last question sentence from text.

        Args:
            text: Full LLM response text.

        Returns:
            The last sentence ending with ?, or None if no question found.
        """
        if not text:
            return None

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        # Find the last sentence ending with ?
        for sentence in reversed(sentences):
            sentence = sentence.strip()
            if sentence.endswith('?'):
                return sentence

        return None

    async def _send_question(self, question: str) -> None:
        """Send question to frontend via Daily app message.

        Args:
            question: The question text to display.
        """
        try:
            await self._transport.send_app_message({"question": question})
            logger.debug(f"Sent question to frontend: {question[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to send question to frontend: {e}")
```

**Step 2: Commit**

```bash
git add src/boswell/voice/display_text.py
git commit -m "feat(voice): add DisplayTextProcessor for frontend question display"
```

---

### Task 2: Wire DisplayTextProcessor into Pipeline

**Files:**
- Modify: `src/boswell/voice/pipeline.py:20-26` (imports)
- Modify: `src/boswell/voice/pipeline.py:165-183` (pipeline construction)

**Step 1: Add import**

Add after line 25 (after `from boswell.voice.audio_diagnostics import AudioDiagnosticsProcessor`):

```python
from boswell.voice.display_text import DisplayTextProcessor
```

**Step 2: Create processor instance**

Add after line 158 (`audio_diagnostics = AudioDiagnosticsProcessor()`):

```python
    # Set up display text for frontend question display
    display_text_processor = DisplayTextProcessor(transport)
```

**Step 3: Add processor to pipeline**

Insert `display_text_processor` in the pipeline list after `bot_response_collector` and before `tts` (around line 176-177). The pipeline section should become:

```python
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_collector,  # Capture guest speech after STT
            acknowledgment_processor,  # Immediate filler acknowledgment
            context_aggregator.user(),
            llm,
            strike_control_processor,  # Process strike tags and mark transcript
            speed_control_processor,  # Process speed tags and adjust TTS
            mode_detection_processor,  # Detect mode tags for returning guests
            bot_response_collector,  # Capture bot responses after LLM
            display_text_processor,  # Send questions to frontend display
            tts,
            audio_diagnostics,  # DEBUG: Log audio frames before output
            # speaking_state_processor,  # Disabled - latency issues
            transport.output(),
            context_aggregator.assistant(),
        ]
    )
```

**Step 4: Commit**

```bash
git add src/boswell/voice/pipeline.py
git commit -m "feat(voice): wire DisplayTextProcessor into pipeline"
```

---

### Task 3: Update Room.tsx to Receive and Display Questions

**Files:**
- Modify: `room-ui/src/components/Room.tsx`

**Step 1: Add state and effect for app messages**

Add imports at the top (update existing import line):

```tsx
import { useEffect, useState, useCallback } from 'react'
import { useDaily, useMeetingState, DailyAudio, DailyEventObjectAppMessage } from '@daily-co/daily-react'
```

Add state inside the Room component (after the `countdown` state):

```tsx
const [currentQuestion, setCurrentQuestion] = useState<string | null>(null)
```

Add effect to listen for app messages (after the countdown effect):

```tsx
// Listen for question updates from Boswell
useEffect(() => {
  if (!daily) return

  const handleAppMessage = (event: DailyEventObjectAppMessage) => {
    if (event.data?.question) {
      setCurrentQuestion(event.data.question)
    }
  }

  daily.on('app-message', handleAppMessage)
  return () => {
    daily.off('app-message', handleAppMessage)
  }
}, [daily])
```

**Step 2: Add question display to JSX**

Add after the countdown div and before `<Controls />`:

```tsx
{currentQuestion && countdown === 'done' && (
  <div className="current-question">
    {currentQuestion}
  </div>
)}
```

**Step 3: Commit**

```bash
git add room-ui/src/components/Room.tsx
git commit -m "feat(room-ui): display current question from Boswell"
```

---

### Task 4: Add CSS Styling for Question Display

**Files:**
- Modify: `room-ui/src/styles/room.css`

**Step 1: Add styles at end of file**

```css
/* Current Question Display */
.current-question {
  position: absolute;
  bottom: 120px;
  left: 50%;
  transform: translateX(-50%);
  max-width: 70%;
  padding: 16px 28px;
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: rgba(255, 255, 255, 0.9);
  font-family: var(--font-body);
  font-size: 1.1rem;
  line-height: 1.5;
  text-align: center;
  backdrop-filter: blur(8px);
  animation: question-fade-in 0.3s ease-out;
  z-index: 5;
}

@keyframes question-fade-in {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}
```

**Step 2: Commit**

```bash
git add room-ui/src/styles/room.css
git commit -m "style(room-ui): add styling for question display"
```

---

### Task 5: Build Room UI and Test

**Step 1: Build the room UI**

```bash
cd room-ui && npm run build
```

Expected: Build completes successfully with no TypeScript errors.

**Step 2: Commit built assets**

```bash
git add room-ui/dist/
git commit -m "build(room-ui): rebuild with question display feature"
```

---

### Task 6: Deploy and Verify

**Step 1: Push to deploy**

```bash
git push origin master
```

**Step 2: Monitor Railway logs**

```bash
railway logs
```

Look for: No errors related to `DisplayTextProcessor` or `send_app_message`.

**Step 3: Test manually**

1. Start an interview from the admin dashboard
2. Join as guest
3. Verify: When Boswell asks a question, the question text appears on screen
4. Verify: Short acknowledgments like "Mm-hmm" do NOT display (no question mark)
5. Verify: Question updates when Boswell asks the next question

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Create DisplayTextProcessor | `src/boswell/voice/display_text.py` |
| 2 | Wire into pipeline | `src/boswell/voice/pipeline.py` |
| 3 | Frontend message listener | `room-ui/src/components/Room.tsx` |
| 4 | CSS styling | `room-ui/src/styles/room.css` |
| 5 | Build room UI | `room-ui/dist/` |
| 6 | Deploy and verify | - |
