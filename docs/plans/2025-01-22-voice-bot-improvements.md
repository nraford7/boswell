# Voice Bot UX Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the Boswell voice bot experience with better greeting, faster responses via filler words, cleaner questions, faster speech, and quicker wrap-up.

**Architecture:** All changes are in the voice module - primarily `prompts.py` for behavior changes and `pipeline.py` for TTS speed settings. The filler word feature requires a custom Pipecat processor that intercepts user speech completion and immediately queues an acknowledgment before the LLM responds.

**Tech Stack:** Pipecat, ElevenLabs TTS, Anthropic Claude

---

### Task 1: Update System Prompt - Improved Greeting Instructions

**Files:**
- Modify: `src/boswell/voice/prompts.py:33-62`

**Step 1: Update the system prompt greeting section**

Replace the INTERVIEW STYLE and GUIDELINES sections to include comprehensive greeting instructions and single-question rule.

```python
    return f"""You are Boswell, a skilled AI research interviewer conducting an interview about: {topic}

INTERVIEW STYLE:
- Warm, curious, and intellectually engaged like an NPR interviewer
- Ask open-ended questions that invite detailed, thoughtful responses
- Listen actively and follow interesting threads that emerge
- Acknowledge what the guest says briefly before moving to new topics
- Be conversational and natural, not robotic or scripted
- Use the guest's name occasionally if they've shared it

IMPORTANT - QUESTION FORMAT:
- Ask ONE question at a time - no sub-questions, no examples, no "in other words"
- Keep questions concise and direct
- Let the guest interpret the question their own way
- If clarification is needed, wait for them to ask

IMMEDIATE ACKNOWLEDGMENTS:
- After the guest finishes speaking, IMMEDIATELY say a brief acknowledgment (1-3 words)
- Examples: "Mm-hmm.", "I see.", "Right.", "Interesting.", "Got it.", "Yes."
- Then pause briefly before giving your fuller response
- This helps the guest know you heard them while you formulate your next thought

{research_section}PREPARED QUESTIONS (use as a guide, follow the conversation naturally):
{questions_text}

OPENING THE INTERVIEW:
When the guest first joins, you MUST cover these points quickly and naturally:
1. Greet them warmly and introduce yourself as Boswell
2. Briefly state the interview topic: "{topic}"
3. Mention the target length: about {target_minutes} minutes
4. Let them know: "Feel free to ask me to repeat any question, pause if you need a moment, or stop at any time"
5. Mention: "I take a couple seconds to think after you finish speaking, so don't worry about brief pauses"
6. Ask if they're ready to begin

GUIDELINES:
- Target interview length: {target_minutes} minutes
- Maximum time: {max_minutes} minutes
- Check in with the guest every 4-5 questions ("How are we doing on time?")
- If they go off-topic but it's interesting, follow that thread briefly
- If they seem uncomfortable with a question, gracefully move on

WRAPPING UP:
When all questions are covered or time is up:
1. Thank them briefly and genuinely
2. Ask ONE time if there's anything else they'd like to add
3. If yes, let them share, then wrap up
4. If no, immediately say goodbye warmly and tell them they can close the window
5. Do NOT drag out the ending - be warm but efficient

RESPONSE FORMAT:
- Keep responses concise and natural for spoken conversation
- Avoid long monologues - this is a dialogue
- Don't use bullet points or numbered lists when speaking
- Don't use markdown formatting
- Speak as you would in a real conversation

Remember: The prepared questions are a guide, not a script. Follow interesting threads that emerge naturally. Your goal is to have a genuine, insightful conversation."""
```

**Step 2: Verify the change**

Run: `python3 -c "from boswell.voice.prompts import build_system_prompt; p = build_system_prompt('Test', ['Q1']); print('IMMEDIATE ACKNOWLEDGMENTS' in p and 'ONE question' in p)"`
Expected: `True`

**Step 3: Commit**

```bash
git add src/boswell/voice/prompts.py
git commit -m "feat(voice): improve system prompt with greeting, single questions, acknowledgments"
```

---

### Task 2: Increase TTS Speech Rate by 15%

**Files:**
- Modify: `src/boswell/voice/pipeline.py:82-87`

**Step 1: Update ElevenLabs TTS configuration**

ElevenLabs supports a `stability` parameter and we can pass voice settings. For faster speech, we adjust the output format and add speed settings via the `voice_settings` parameter.

```python
    # Set up TTS (Text-to-Speech) with ElevenLabs
    tts = ElevenLabsTTSService(
        api_key=config.elevenlabs_api_key,
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel - professional female voice
        model="eleven_turbo_v2",  # Fast model for low latency
        voice_settings={
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.15,  # 15% faster speech
        },
    )
```

**Step 2: Verify the change compiles**

Run: `python3 -c "from boswell.voice.pipeline import create_pipeline; print('Pipeline imports OK')"`
Expected: `Pipeline imports OK`

**Step 3: Commit**

```bash
git add src/boswell/voice/pipeline.py
git commit -m "feat(voice): increase TTS speech rate by 15%"
```

---

### Task 3: Update Greeting Trigger Message

**Files:**
- Modify: `src/boswell/voice/pipeline.py:132-138`

**Step 1: Update the on_first_participant_joined handler**

Make the greeting trigger more explicit about what to include.

```python
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        """Greet the guest when they join."""
        # Trigger the initial greeting with full context
        await task.queue_frames(
            [LLMMessagesFrame([{
                "role": "user",
                "content": "The guest has just joined the room. Follow your OPENING THE INTERVIEW instructions exactly - greet them, explain the interview, mention the timing, tell them about pauses and that they can stop/repeat anytime, then ask if they're ready."
            }])]
        )
```

**Step 2: Verify syntax**

Run: `python3 -c "from boswell.voice.pipeline import create_pipeline; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/boswell/voice/pipeline.py
git commit -m "feat(voice): update greeting trigger with explicit instructions"
```

---

### Task 4: Create Acknowledgment Processor for Filler Words

**Files:**
- Create: `src/boswell/voice/acknowledgment.py`
- Modify: `src/boswell/voice/pipeline.py`

**Step 1: Create the acknowledgment processor**

This processor detects when the user stops speaking and immediately queues a filler acknowledgment before the LLM processes the full response.

Create `src/boswell/voice/acknowledgment.py`:

```python
"""Immediate acknowledgment processor for reducing perceived latency."""

import random

from pipecat.frames.frames import (
    Frame,
    TextFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Short acknowledgment phrases to use immediately after user stops speaking
ACKNOWLEDGMENTS = [
    "Mm-hmm.",
    "I see.",
    "Right.",
    "Interesting.",
    "Got it.",
    "Yes.",
    "Okay.",
    "Mm.",
]


class AcknowledgmentProcessor(FrameProcessor):
    """Immediately acknowledges user speech to reduce perceived latency.

    When the user stops speaking, this processor immediately pushes a short
    acknowledgment phrase to the TTS, giving the LLM time to generate a
    fuller response while the user hears immediate feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_acknowledgment = ""

    def _get_acknowledgment(self) -> str:
        """Get a random acknowledgment, avoiding immediate repeats."""
        available = [a for a in ACKNOWLEDGMENTS if a != self._last_acknowledgment]
        ack = random.choice(available)
        self._last_acknowledgment = ack
        return ack

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process frames and inject acknowledgments."""
        await super().process_frame(frame, direction)

        # When user stops speaking, immediately send an acknowledgment
        if isinstance(frame, UserStoppedSpeakingFrame):
            ack = self._get_acknowledgment()
            # Push acknowledgment text frame that will go to TTS
            await self.push_frame(TextFrame(text=ack), FrameDirection.DOWNSTREAM)

        # Always pass the original frame through
        await self.push_frame(frame, direction)
```

**Step 2: Verify the new file**

Run: `python3 -c "from boswell.voice.acknowledgment import AcknowledgmentProcessor; print('OK')"`
Expected: `OK`

**Step 3: Commit the new file**

```bash
git add src/boswell/voice/acknowledgment.py
git commit -m "feat(voice): add acknowledgment processor for filler words"
```

---

### Task 5: Integrate Acknowledgment Processor into Pipeline

**Files:**
- Modify: `src/boswell/voice/pipeline.py:17` (imports)
- Modify: `src/boswell/voice/pipeline.py:102-120` (pipeline construction)

**Step 1: Add import**

After line 17, add:

```python
from boswell.voice.acknowledgment import AcknowledgmentProcessor
```

**Step 2: Add acknowledgment processor to pipeline**

Update the pipeline construction to include the acknowledgment processor. It should be placed after the STT but before the LLM context aggregator, so it can intercept `UserStoppedSpeakingFrame` and inject acknowledgments.

```python
    # Set up transcript collection
    transcript_collector = TranscriptCollector()
    bot_response_collector = BotResponseCollector(transcript_collector)

    # Set up immediate acknowledgment for reduced perceived latency
    acknowledgment_processor = AcknowledgmentProcessor()

    # Build the pipeline
    # Audio flows: transport.input -> stt -> transcript -> ack -> context -> llm -> bot_collector -> tts -> output
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_collector,  # Capture guest speech after STT
            acknowledgment_processor,  # Immediate filler acknowledgment
            context_aggregator.user(),
            llm,
            bot_response_collector,  # Capture bot responses after LLM
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )
```

**Step 3: Verify the pipeline compiles**

Run: `python3 -c "from boswell.voice.pipeline import create_pipeline; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/boswell/voice/pipeline.py
git commit -m "feat(voice): integrate acknowledgment processor into pipeline"
```

---

### Task 6: Update Voice Module Exports

**Files:**
- Modify: `src/boswell/voice/__init__.py`

**Step 1: Add acknowledgment processor to exports**

```python
"""Voice bot module for Boswell.

Provides real-time voice interview capabilities using Pipecat.
"""

from boswell.voice.acknowledgment import AcknowledgmentProcessor
from boswell.voice.bot import InterviewBot
from boswell.voice.pipeline import create_pipeline
from boswell.voice.transcript import TranscriptCollector

__all__ = [
    "AcknowledgmentProcessor",
    "InterviewBot",
    "create_pipeline",
    "TranscriptCollector",
]
```

**Step 2: Verify imports**

Run: `python3 -c "from boswell.voice import AcknowledgmentProcessor; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/boswell/voice/__init__.py
git commit -m "feat(voice): export AcknowledgmentProcessor"
```

---

### Task 7: Final Integration Test

**Step 1: Run full import test**

```bash
python3 -c "
from boswell.voice.pipeline import create_pipeline
from boswell.voice.prompts import build_system_prompt
from boswell.voice.acknowledgment import AcknowledgmentProcessor

# Test prompt has all new sections
prompt = build_system_prompt('Test Topic', ['Question 1', 'Question 2'])
assert 'IMMEDIATE ACKNOWLEDGMENTS' in prompt
assert 'ONE question at a time' in prompt
assert 'OPENING THE INTERVIEW' in prompt
assert 'WRAPPING UP' in prompt
assert 'couple seconds to think' in prompt

print('All checks passed!')
"
```

Expected: `All checks passed!`

**Step 2: Commit final changes and push**

```bash
git add -A
git status
git push origin master
```

---

## Summary of Changes

| Change | File | What |
|--------|------|------|
| Improved greeting | `prompts.py` | Full onboarding: topic, timing, pause warning, can stop/repeat |
| Single questions | `prompts.py` | Explicit instruction to ask one question only |
| Filler words | `acknowledgment.py` | New processor for immediate "Mm-hmm" responses |
| 15% faster speech | `pipeline.py` | ElevenLabs `speed: 1.15` setting |
| Quicker wrap-up | `prompts.py` | Explicit instructions to end efficiently |
| Greeting trigger | `pipeline.py` | More explicit instruction in `on_first_participant_joined` |

## Testing

After implementation, run a short test interview to verify:
1. Bot greets with full context (topic, timing, pause warning)
2. Immediate "Mm-hmm" or similar after each guest response
3. Speech sounds ~15% faster
4. Questions are single-level without sub-questions
5. Wrap-up is efficient - one "anything else?" then goodbye
