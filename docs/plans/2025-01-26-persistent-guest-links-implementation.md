# Persistent Named Guest Links - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow named guests to reuse their magic link after completing an interview, with options to Resume, Add Detail, or Fresh Start.

**Architecture:** Modify the guest routes to allow completed interviews to restart. Pass returning guest context (previous transcript) to the voice pipeline. The bot asks the guest which mode they want, signals the choice via app message, and the worker handles transcript accordingly.

**Tech Stack:** FastAPI, SQLAlchemy, Pipecat, Daily.co, PostgreSQL

---

## Task 1: Add session_count field to Interview model

**Files:**
- Modify: `src/boswell/server/models.py:183-191`
- Create: `src/boswell/server/migrations/versions/XXXX_add_session_count.py`

**Step 1: Add the field to the model**

In `src/boswell/server/models.py`, add after line 191 (after `expires_at`):

```python
    session_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
```

**Step 2: Create the migration**

Run:
```bash
cd /Users/noahraford/Projects/boswell
alembic revision --autogenerate -m "add session_count to interviews"
```

**Step 3: Review the generated migration**

The migration should add:
```python
op.add_column('guests', sa.Column('session_count', sa.Integer(), nullable=False, server_default='1'))
```

**Step 4: Run the migration**

Run:
```bash
alembic upgrade head
```

**Step 5: Commit**

```bash
git add src/boswell/server/models.py src/boswell/server/migrations/versions/
git commit -m "feat: add session_count field to Interview model"
```

---

## Task 2: Add interview_mode field to Interview model

**Files:**
- Modify: `src/boswell/server/models.py:171-173`

The bot will signal which mode the guest chose. We need to store this on the Interview record.

**Step 1: Add InterviewMode enum after InterviewStatus (line 27)**

```python
class InterviewMode(str, enum.Enum):
    """Mode for returning guest interviews."""

    new = "new"  # First-time interview
    resume = "resume"  # Continue where left off
    add_detail = "add_detail"  # Review and refine previous answers
    fresh_start = "fresh_start"  # Delete old transcript, start over
```

**Step 2: Add the field to Interview model (after session_count)**

```python
    interview_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
```

**Step 3: Create and run migration**

```bash
alembic revision --autogenerate -m "add interview_mode to interviews"
alembic upgrade head
```

**Step 4: Commit**

```bash
git add src/boswell/server/models.py src/boswell/server/migrations/versions/
git commit -m "feat: add interview_mode field for returning guests"
```

---

## Task 3: Modify landing page route to allow completed interviews

**Files:**
- Modify: `src/boswell/server/routes/guest.py:107-174`

**Step 1: Update the interview_landing function**

Replace lines 152-157 (the completed redirect block) with:

```python
    # Completed - for named guests, show landing page with "Start or Resume" option
    # For generic link guests, redirect to thank you page
    if interview.status == InterviewStatus.completed:
        # Check if this is a named guest (has email or was created via admin)
        # Generic link guests have no email and were created on-the-fly
        is_named_guest = interview.email is not None or interview.claimed_by is not None

        if is_named_guest:
            # Show landing page with option to resume
            return templates.TemplateResponse(
                request=request,
                name="guest/landing.html",
                context={
                    "project": interview.project,
                    "interview": interview,
                    "is_returning": True,
                },
            )
        else:
            # Generic link guests go to thank you
            return RedirectResponse(
                url=f"/i/{magic_token}/thankyou",
                status_code=303,
            )
```

**Step 2: Run and verify**

```bash
cd /Users/noahraford/Projects/boswell
docker-compose up -d
# Visit a completed interview's magic link - should see landing page
```

**Step 3: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "feat: allow completed interviews to show landing page for named guests"
```

---

## Task 4: Update landing page template for returning guests

**Files:**
- Modify: `src/boswell/server/templates/guest/landing.html:236-246`

**Step 1: Update the button text conditionally**

Replace the button (lines 240-245) with:

```html
            <button type="submit" class="btn">
                {% if is_returning %}
                Start or Resume Interview
                {% else %}
                Start Interview
                {% endif %}
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
            </button>
```

**Step 2: Add a returning guest message (optional, after info-section)**

```html
        {% if is_returning %}
        <div class="info-section" style="background: var(--accent-subtle); padding: 1rem; border-radius: var(--radius-md); margin-bottom: 1.5rem;">
            <p style="color: var(--accent); font-size: 0.875rem; margin: 0;">
                <strong>Welcome back!</strong> You've completed this interview before.
                Boswell will ask if you'd like to continue, add detail to your previous answers, or start fresh.
            </p>
        </div>
        {% endif %}
```

**Step 3: Commit**

```bash
git add src/boswell/server/templates/guest/landing.html
git commit -m "feat: update landing page for returning guests"
```

---

## Task 5: Modify start_interview route to handle returning guests

**Files:**
- Modify: `src/boswell/server/routes/guest.py:177-251`

**Step 1: Update the start_interview function**

Replace the completed check (lines 222-227) and add returning guest logic:

```python
    # Check if this is a returning guest (completed interview)
    is_returning = interview.status == InterviewStatus.completed
    has_transcript = False

    if is_returning:
        # Fetch existing transcript for context
        from boswell.server.models import Transcript
        transcript_result = await db.execute(
            select(Transcript).where(Transcript.interview_id == interview.id)
        )
        existing_transcript = transcript_result.scalar_one_or_none()
        has_transcript = existing_transcript is not None

        # Increment session count
        interview.session_count = (interview.session_count or 1) + 1

    # Already started with active room - redirect to room
    if interview.status == InterviewStatus.started and interview.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}/room",
            status_code=303,
        )

    # Create Daily.co room
    room_info = await create_daily_room(str(interview.id), interview.name)

    # Update interview record
    interview.status = InterviewStatus.started
    interview.room_name = room_info["room_name"]
    interview.room_token = room_info["room_token"]
    interview.started_at = now
    interview.interview_mode = None  # Will be set by bot via app message

    # Store returning flag in a way the worker can access
    # We'll use interview_mode = None to indicate bot should ask
    if is_returning and has_transcript:
        interview.interview_mode = "pending"  # Bot will update this

    await db.commit()
```

**Step 2: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "feat: handle returning guests in start_interview route"
```

---

## Task 6: Add returning guest prompt builder

**Files:**
- Modify: `src/boswell/voice/prompts.py`

**Step 1: Add new function after build_system_prompt (after line 137)**

```python
def build_returning_guest_prompt(
    previous_transcript: list[dict],
    guest_name: str = "Guest",
) -> str:
    """Build additional prompt for returning guests.

    Args:
        previous_transcript: List of previous transcript entries.
        guest_name: Name of the guest.

    Returns:
        Additional prompt text to inject into system prompt.
    """
    # Format transcript entries for the prompt
    transcript_text = ""
    for entry in previous_transcript[-20:]:  # Last 20 entries to avoid token limits
        speaker = entry.get("speaker", "unknown")
        text = entry.get("text", "")
        if speaker == "guest":
            transcript_text += f"{guest_name}: {text}\n"
        else:
            transcript_text += f"Boswell: {text}\n"

    return f"""
RETURNING GUEST - IMPORTANT:
This guest has completed a previous interview session. When they join, greet them warmly and ask what they'd like to do:

1. RESUME - "Pick up where we left off" - Continue the conversation, appending to the existing transcript
2. ADD DETAIL - "Add detail to my previous answers" - Review and refine previous answers
3. FRESH START - "Start completely fresh" - Delete previous answers and start over (CONFIRM BEFORE PROCEEDING)

Listen for their intent and respond accordingly. Be flexible - if they change their mind or ask about previous answers, accommodate them (unless they confirmed Fresh Start).

For FRESH START: You MUST confirm before proceeding. Say something like "Just to confirm - you'd like to start completely fresh? This will replace your previous answers. Is that okay?" Only proceed after verbal confirmation.

For ADD DETAIL: Offer to help them review their previous answers. Ask something like "Would you like to add anything new, refine a specific answer, or should I run through the questions to jog your memory?" Adapt to what they want.

Once the guest confirms their choice, send an app message with their choice so the system knows how to handle the transcript.

PREVIOUS CONVERSATION:
<previous_transcript>
{transcript_text}
</previous_transcript>

CRITICAL: After the guest confirms their choice (resume/add_detail/fresh_start), include in your response:
- For resume: [MODE:resume]
- For add detail: [MODE:add_detail]
- For fresh start (after confirmation): [MODE:fresh_start]

This tag will be processed by the system to handle the transcript correctly.
"""
```

**Step 2: Commit**

```bash
git add src/boswell/voice/prompts.py
git commit -m "feat: add returning guest prompt builder"
```

---

## Task 7: Create ModeDetectionProcessor for the pipeline

**Files:**
- Create: `src/boswell/voice/mode_detection.py`

**Step 1: Create the processor**

```python
"""Mode detection processor for returning guest interviews."""

import re
from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


MODE_TAG_PATTERN = re.compile(r'\[MODE:(resume|add_detail|fresh_start)\]', re.IGNORECASE)


class ModeDetectionProcessor(FrameProcessor):
    """Detects interview mode tags in bot responses.

    When the bot includes [MODE:xxx] in its response, this processor
    captures the mode and stores it for the worker to read.
    """

    def __init__(self, on_mode_detected=None, **kwargs):
        super().__init__(**kwargs)
        self._detected_mode: str | None = None
        self._on_mode_detected = on_mode_detected

    @property
    def detected_mode(self) -> str | None:
        """Get the detected interview mode."""
        return self._detected_mode

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames, detecting mode tags."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            match = MODE_TAG_PATTERN.search(frame.text)
            if match:
                self._detected_mode = match.group(1).lower()

                if self._on_mode_detected:
                    await self._on_mode_detected(self._detected_mode)

                # Remove the tag from the text before it goes to TTS
                cleaned_text = MODE_TAG_PATTERN.sub('', frame.text).strip()
                frame = TextFrame(text=cleaned_text)

        await self.push_frame(frame, direction)
```

**Step 2: Commit**

```bash
git add src/boswell/voice/mode_detection.py
git commit -m "feat: add ModeDetectionProcessor for returning guest mode"
```

---

## Task 8: Integrate returning guest logic into worker

**Files:**
- Modify: `src/boswell/server/worker.py:56-136`

**Step 1: Update start_voice_interview to accept returning guest params**

Update the function signature and add logic (around line 56):

```python
async def start_voice_interview(
    interview: Interview,
    project: Project,
    is_returning: bool = False,
    previous_transcript: list[dict] | None = None,
    previous_context: list[dict] | None = None,
) -> tuple[list[dict[str, Any]], list[dict], str | None]:
    """Start a voice interview.

    Args:
        interview: The Interview model instance with room_name and room_token.
        project: The Project model instance with topic and questions.
        is_returning: Whether this is a returning guest.
        previous_transcript: Previous transcript entries for returning guests.
        previous_context: Previous conversation context for returning guests.

    Returns:
        Tuple of (transcript entries, conversation history, detected_mode).
    """
```

**Step 2: Build system prompt with returning guest context**

After line 115 (after building system_prompt), add:

```python
    # Add returning guest prompt if applicable
    detected_mode = None
    if is_returning and previous_transcript:
        from boswell.voice.prompts import build_returning_guest_prompt
        returning_prompt = build_returning_guest_prompt(
            previous_transcript=previous_transcript,
            guest_name=guest_name,
        )
        system_prompt = system_prompt + "\n\n" + returning_prompt
```

**Step 3: Update run_interview call to capture mode**

The run_interview function needs to return the detected mode. We'll update the pipeline to track this.

**Step 4: Commit**

```bash
git add src/boswell/server/worker.py
git commit -m "feat: integrate returning guest logic into worker"
```

---

## Task 9: Update pipeline to support mode detection

**Files:**
- Modify: `src/boswell/voice/pipeline.py`

**Step 1: Import ModeDetectionProcessor (after line 20)**

```python
from boswell.voice.mode_detection import ModeDetectionProcessor
```

**Step 2: Add mode detection to create_pipeline**

After line 141 (after speed_control_processor), add:

```python
    # Set up mode detection for returning guests
    mode_detection_processor = ModeDetectionProcessor()
```

**Step 3: Add to pipeline (after speed_control_processor in the list)**

```python
            mode_detection_processor,  # Detect [MODE:xxx] tags for returning guests
```

**Step 4: Return the processor so worker can access detected mode**

Update the return type and return statement to include the processor.

**Step 5: Update run_interview to return detected mode**

```python
async def run_interview(
    room_url: str,
    room_token: str,
    system_prompt: str,
    bot_name: str = "Boswell",
    guest_name: str = "Guest",
    initial_messages: list[dict] | None = None,
) -> tuple[list[dict[str, Any]], list[dict], str | None]:
    """Run a voice interview session.

    Returns:
        Tuple of (transcript entries, conversation history, detected_mode).
    """
    task, runner, transcript_collector, context, mode_processor = await create_pipeline(...)

    await runner.run(task)

    return transcript_collector.get_entries(), context.messages, mode_processor.detected_mode
```

**Step 6: Commit**

```bash
git add src/boswell/voice/pipeline.py
git commit -m "feat: add mode detection to pipeline for returning guests"
```

---

## Task 10: Update worker to handle transcript based on mode

**Files:**
- Modify: `src/boswell/server/worker.py:139-213`

**Step 1: Create mode-aware save_transcript function**

Replace or update save_transcript (lines 139-184):

```python
async def save_transcript(
    db: AsyncSession,
    interview_id: UUID,
    entries: list[dict[str, Any]],
    conversation_context: list[dict],
    mode: str | None = None,
) -> Transcript:
    """Save interview transcript to database based on mode.

    Args:
        db: Database session.
        interview_id: UUID of the interview.
        entries: List of transcript entry dictionaries.
        conversation_context: List of conversation messages.
        mode: Interview mode (resume, add_detail, fresh_start, or None for new).

    Returns:
        The created or updated Transcript model instance.
    """
    # Check if transcript already exists
    result = await db.execute(
        select(Transcript).where(Transcript.interview_id == interview_id)
    )
    transcript = result.scalar_one_or_none()

    if mode == "fresh_start":
        # Delete existing transcript and analysis
        if transcript:
            await db.delete(transcript)
            # Also delete analysis
            from boswell.server.models import Analysis
            analysis_result = await db.execute(
                select(Analysis).where(Analysis.interview_id == interview_id)
            )
            analysis = analysis_result.scalar_one_or_none()
            if analysis:
                await db.delete(analysis)
            await db.flush()

        # Create new transcript
        transcript = Transcript(
            interview_id=interview_id,
            entries=entries,
            conversation_context=conversation_context,
        )
        db.add(transcript)
        logger.info(f"Fresh start: created new transcript for interview {interview_id}")

    elif mode == "resume" and transcript:
        # Append new entries to existing transcript
        existing_entries = transcript.entries or []
        if isinstance(existing_entries, list):
            transcript.entries = existing_entries + entries
        else:
            transcript.entries = entries
        transcript.conversation_context = conversation_context
        logger.info(f"Resume: appended to transcript for interview {interview_id}")

    elif mode == "add_detail" and transcript:
        # Replace transcript with combined conversation (bot wove them together)
        transcript.entries = entries
        transcript.conversation_context = conversation_context
        logger.info(f"Add detail: updated transcript for interview {interview_id}")

    elif transcript:
        # Default: append (backwards compatible)
        existing_entries = transcript.entries or []
        if isinstance(existing_entries, list):
            transcript.entries = existing_entries + entries
        else:
            transcript.entries = entries
        transcript.conversation_context = conversation_context
        logger.info(f"Updated existing transcript for interview {interview_id}")

    else:
        # Create new transcript
        transcript = Transcript(
            interview_id=interview_id,
            entries=entries,
            conversation_context=conversation_context,
        )
        db.add(transcript)
        logger.info(f"Created new transcript for interview {interview_id}")

    await db.flush()
    return transcript
```

**Step 2: Update complete_interview to accept mode**

```python
async def complete_interview(
    db: AsyncSession,
    interview_id: UUID,
    transcript_entries: list[dict[str, Any]],
    conversation_history: list[dict],
    mode: str | None = None,
) -> None:
    """Complete an interview by saving transcript and updating status."""
    # Save transcript with mode
    await save_transcript(db, interview_id, transcript_entries, conversation_history, mode)

    # Update interview status and mode
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()

    if interview:
        interview.status = InterviewStatus.completed
        interview.completed_at = datetime.now(timezone.utc)
        if mode:
            interview.interview_mode = mode
        await db.flush()
        logger.info(f"Interview {interview_id} marked as completed (mode={mode})")
```

**Step 3: Commit**

```bash
git add src/boswell/server/worker.py
git commit -m "feat: handle transcript save based on interview mode"
```

---

## Task 11: Update run_interview_task to pass returning guest context

**Files:**
- Modify: `src/boswell/server/worker.py:215-286`

**Step 1: Fetch previous transcript for returning guests**

In run_interview_task, after fetching interview (around line 230), add:

```python
            # Check if this is a returning guest
            is_returning = interview.interview_mode == "pending"
            previous_transcript = None
            previous_context = None

            if is_returning:
                # Fetch existing transcript
                transcript_result = await db.execute(
                    select(Transcript).where(Transcript.interview_id == interview.id)
                )
                existing_transcript = transcript_result.scalar_one_or_none()
                if existing_transcript:
                    previous_transcript = existing_transcript.entries or []
                    previous_context = existing_transcript.conversation_context or []
```

**Step 2: Pass to start_voice_interview**

Update the call (around line 268):

```python
        transcript_entries, conversation_history, detected_mode = await start_voice_interview(
            interview_data,
            project,
            is_returning=is_returning,
            previous_transcript=previous_transcript,
            previous_context=previous_context,
        )
```

**Step 3: Pass mode to complete_interview**

```python
            await complete_interview(
                db, interview_id, transcript_entries, conversation_history, detected_mode
            )
```

**Step 4: Commit**

```bash
git add src/boswell/server/worker.py
git commit -m "feat: pass returning guest context through worker pipeline"
```

---

## Task 12: End-to-end testing

**Files:**
- No new files, manual testing

**Step 1: Start services**

```bash
cd /Users/noahraford/Projects/boswell
docker-compose up -d
```

**Step 2: Create a test interview and complete it**

1. Go to admin, create a project with questions
2. Add a named guest (with email)
3. Open guest link, complete the interview

**Step 3: Test returning guest flow**

1. Click the same magic link again
2. Should see "Start or Resume Interview" button
3. Join the room
4. Bot should ask about Resume/Add Detail/Fresh Start
5. Test each mode:
   - Resume: Say "let's continue" - verify transcript appends
   - Add Detail: Say "I want to add detail" - verify transcript updates
   - Fresh Start: Say "start fresh" - confirm when asked - verify old transcript deleted

**Step 4: Verify transcript handling**

Check database after each test:
```bash
docker-compose exec db psql -U boswell -d boswell -c "SELECT id, entries FROM transcripts LIMIT 5;"
```

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found in testing"
```

---

## Task 13: Final commit and push

**Step 1: Review all changes**

```bash
git status
git log --oneline -10
```

**Step 2: Push to remote**

```bash
git push origin master
```

**Step 3: Verify deployment**

Check Railway dashboard for successful deploy.

---

## Summary of Files Modified

| File | Changes |
|------|---------|
| `models.py` | Add `session_count`, `interview_mode` fields, `InterviewMode` enum |
| `routes/guest.py` | Allow completed interviews to restart, handle returning guests |
| `templates/guest/landing.html` | "Start or Resume Interview" button, returning guest message |
| `prompts.py` | Add `build_returning_guest_prompt()` function |
| `mode_detection.py` | New file - ModeDetectionProcessor |
| `pipeline.py` | Integrate mode detection, return detected mode |
| `worker.py` | Handle transcript based on mode, pass returning context |
| migrations | Add `session_count` and `interview_mode` columns |
