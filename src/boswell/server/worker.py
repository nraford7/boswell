# src/boswell/server/worker.py
"""Voice worker for conducting interviews.

This worker polls for guests who have started their interviews (status="started"
with a room_name) and launches the Pipecat voice pipeline to conduct the interview.
When the interview completes, it saves the transcript and updates the guest status.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session_context
from boswell.server.models import Guest, GuestStatus, Interview, Transcript
from boswell.voice.pipeline import run_interview
from boswell.voice.prompts import build_system_prompt

logger = logging.getLogger(__name__)

# Track active interviews to prevent duplicate bot sessions
# Maps guest_id -> asyncio.Task
_active_interviews: dict[UUID, asyncio.Task] = {}


def _extract_questions_list(interview: Interview) -> list[str]:
    """Extract question text list from interview.questions JSONB.

    The questions field has structure:
    {
        "questions": [
            {"id": 1, "text": "...", "type": "opening", "follow_ups": [...]},
            ...
        ]
    }

    Args:
        interview: The Interview model instance.

    Returns:
        List of question text strings.
    """
    if not interview.questions:
        return []

    questions_data = interview.questions.get("questions", [])
    return [q.get("text", "") for q in questions_data if q.get("text")]


async def start_interview_for_guest(
    guest: Guest,
    interview: Interview,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """Start a voice interview for a guest.

    Args:
        guest: The Guest model instance with room_name and room_token.
        interview: The Interview model instance with topic and questions.

    Returns:
        Tuple of (transcript entries, conversation history).

    Raises:
        ValueError: If guest is missing room credentials.
        RuntimeError: If the pipeline fails to start.
    """
    if not guest.room_name:
        raise ValueError(f"Guest {guest.id} has no room_name")

    # Build room URL from room_name
    # The room_name is like "boswell-{guest_id[:8]}"
    room_url = f"https://boswell.daily.co/{guest.room_name}"

    # Get the bot token (stored in guest.room_token)
    # Note: In current implementation, room_token is a guest token
    # We need a bot token for the pipeline
    # For now, we'll use the guest token as a placeholder
    # TODO: Generate proper bot token when creating room
    room_token = guest.room_token or ""

    # Extract questions from interview
    questions = _extract_questions_list(interview)
    if not questions:
        logger.warning(
            f"Interview {interview.id} has no questions, using default greeting"
        )
        questions = [
            "Can you tell me a bit about yourself and your background?",
            "What brings you to this interview today?",
            "Is there anything specific you'd like to discuss?",
        ]

    # Build the system prompt
    system_prompt = build_system_prompt(
        topic=interview.topic,
        questions=questions,
        research_summary=interview.research_summary,
        target_minutes=interview.target_minutes,
        max_minutes=interview.target_minutes + 15,  # Allow 15 min buffer
    )

    logger.info(
        f"Starting voice interview for guest {guest.id} "
        f"(room={guest.room_name}, topic='{interview.topic}')"
    )

    # Run the Pipecat pipeline (blocks until interview ends)
    transcript_entries, conversation_history = await run_interview(
        room_url=room_url,
        room_token=room_token,
        system_prompt=system_prompt,
        bot_name="Boswell",
    )

    logger.info(
        f"Interview completed for guest {guest.id}: "
        f"{len(transcript_entries)} transcript entries"
    )

    return transcript_entries, conversation_history


async def save_transcript(
    db: AsyncSession,
    guest_id: UUID,
    entries: list[dict[str, Any]],
    conversation_context: list[dict],
) -> Transcript:
    """Save interview transcript to database.

    Creates a new Transcript record or updates existing one for the guest.

    Args:
        db: Database session.
        guest_id: UUID of the guest.
        entries: List of transcript entry dictionaries.
        conversation_context: List of conversation messages (for potential resume).

    Returns:
        The created or updated Transcript model instance.
    """
    # Check if transcript already exists
    result = await db.execute(
        select(Transcript).where(Transcript.guest_id == guest_id)
    )
    transcript = result.scalar_one_or_none()

    if transcript:
        # Update existing transcript (e.g., resumed interview)
        existing_entries = transcript.entries or []
        if isinstance(existing_entries, list):
            transcript.entries = existing_entries + entries
        else:
            transcript.entries = entries
        transcript.conversation_context = conversation_context
        logger.info(f"Updated existing transcript for guest {guest_id}")
    else:
        # Create new transcript
        transcript = Transcript(
            guest_id=guest_id,
            entries=entries,
            conversation_context=conversation_context,
        )
        db.add(transcript)
        logger.info(f"Created new transcript for guest {guest_id}")

    await db.flush()
    return transcript


async def complete_guest_interview(
    db: AsyncSession,
    guest_id: UUID,
    transcript_entries: list[dict[str, Any]],
    conversation_history: list[dict],
) -> None:
    """Complete a guest's interview by saving transcript and updating status.

    Args:
        db: Database session.
        guest_id: UUID of the guest.
        transcript_entries: List of transcript entry dictionaries.
        conversation_history: List of conversation messages.
    """
    # Save transcript
    await save_transcript(db, guest_id, transcript_entries, conversation_history)

    # Update guest status to completed
    result = await db.execute(select(Guest).where(Guest.id == guest_id))
    guest = result.scalar_one_or_none()

    if guest:
        guest.status = GuestStatus.completed
        guest.completed_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(f"Guest {guest_id} marked as completed")


async def run_interview_task(guest_id: UUID) -> None:
    """Task wrapper for running a single interview.

    This function is spawned as an asyncio task for each interview.
    It handles the full lifecycle: start interview, save transcript, update status.

    Args:
        guest_id: UUID of the guest to interview.
    """
    try:
        # Fetch guest and interview data
        async with get_session_context() as db:
            result = await db.execute(
                select(Guest)
                .options(selectinload(Guest.interview))
                .where(Guest.id == guest_id)
            )
            guest = result.scalar_one_or_none()

            if not guest:
                logger.error(f"Guest {guest_id} not found")
                return

            if not guest.interview:
                logger.error(f"Guest {guest_id} has no interview")
                return

            # Cache the data we need (relationships won't be accessible outside session)
            interview = guest.interview
            room_name = guest.room_name
            room_token = guest.room_token

        # Create a minimal guest object for the interview
        # (We can't use the SQLAlchemy object outside the session)
        class GuestData:
            def __init__(self, id, room_name, room_token):
                self.id = id
                self.room_name = room_name
                self.room_token = room_token

        guest_data = GuestData(guest_id, room_name, room_token)

        # Run the interview (this blocks until complete)
        transcript_entries, conversation_history = await start_interview_for_guest(
            guest_data, interview
        )

        # Save results in a new session
        async with get_session_context() as db:
            await complete_guest_interview(
                db, guest_id, transcript_entries, conversation_history
            )

    except Exception as e:
        logger.exception(f"Interview failed for guest {guest_id}: {e}")
        # Don't mark as failed - leave as "started" so it can be retried
        # or manually resolved

    finally:
        # Remove from active interviews
        _active_interviews.pop(guest_id, None)
        logger.info(f"Interview task ended for guest {guest_id}")


async def find_pending_guests(db: AsyncSession) -> list[Guest]:
    """Find guests who are ready for an interview but don't have an active bot.

    Criteria:
    - status = "started"
    - room_name is not null
    - Not already in _active_interviews

    Args:
        db: Database session.

    Returns:
        List of Guest objects ready for interviews.
    """
    result = await db.execute(
        select(Guest)
        .options(selectinload(Guest.interview))
        .where(
            and_(
                Guest.status == GuestStatus.started,
                Guest.room_name.isnot(None),
            )
        )
    )
    guests = list(result.scalars().all())

    # Filter out guests with active interviews
    pending = [g for g in guests if g.id not in _active_interviews]

    return pending


async def run_voice_worker(
    poll_interval: int = 5,
    max_iterations: int | None = None,
) -> None:
    """Main voice worker loop.

    Polls for guests with status="started" and room_name set,
    then starts interview bots for each eligible guest.

    Args:
        poll_interval: Seconds to wait between polling when no guests found.
        max_iterations: Maximum number of poll iterations (None for infinite).
            Useful for testing.
    """
    logger.info(f"Starting voice worker (poll_interval={poll_interval}s)")
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        try:
            async with get_session_context() as db:
                pending_guests = await find_pending_guests(db)

                if pending_guests:
                    logger.info(f"Found {len(pending_guests)} pending guest(s)")

                for guest in pending_guests:
                    # Start interview task for this guest
                    logger.info(
                        f"Starting interview for guest {guest.id} "
                        f"(room={guest.room_name})"
                    )

                    # Create and track the task
                    task = asyncio.create_task(run_interview_task(guest.id))
                    _active_interviews[guest.id] = task

        except Exception as e:
            logger.exception(f"Voice worker error: {e}")

        # Wait before next poll
        await asyncio.sleep(poll_interval)

    logger.info("Voice worker stopped")


async def shutdown_voice_worker() -> None:
    """Gracefully shutdown all active interview tasks.

    Cancels all running interview tasks and waits for them to complete.
    """
    if not _active_interviews:
        logger.info("No active interviews to shutdown")
        return

    logger.info(f"Shutting down {len(_active_interviews)} active interview(s)")

    # Cancel all tasks
    for guest_id, task in _active_interviews.items():
        if not task.done():
            logger.info(f"Cancelling interview for guest {guest_id}")
            task.cancel()

    # Wait for all tasks to complete
    if _active_interviews:
        await asyncio.gather(*_active_interviews.values(), return_exceptions=True)

    _active_interviews.clear()
    logger.info("All interview tasks shutdown complete")


def get_active_interview_count() -> int:
    """Get the number of currently active interviews.

    Returns:
        Number of interviews currently running.
    """
    return len(_active_interviews)


def is_interview_active(guest_id: UUID) -> bool:
    """Check if an interview is currently active for a guest.

    Args:
        guest_id: UUID of the guest.

    Returns:
        True if an interview is active, False otherwise.
    """
    return guest_id in _active_interviews
