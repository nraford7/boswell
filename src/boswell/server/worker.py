# src/boswell/server/worker.py
"""Voice worker for conducting interviews.

This worker polls for interviews that have started (status="started"
with a room_name) and launches the Pipecat voice pipeline to conduct the interview.
When the interview completes, it saves the transcript and updates the interview status.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session_context
from boswell.server.models import (
    Interview,
    InterviewAngle,
    InterviewStatus,
    InterviewTemplate,
    Project,
    Transcript,
)
from boswell.voice.pipeline import run_interview
from boswell.voice.prompts import build_system_prompt

logger = logging.getLogger(__name__)

DAILY_API_URL = "https://api.daily.co/v1"


async def create_bot_token(room_name: str, bot_name: str = "Boswell") -> str:
    """Create a Daily.co meeting token for the bot.

    Args:
        room_name: The Daily room name.
        bot_name: Display name for the bot.

    Returns:
        The meeting token string.

    Raises:
        RuntimeError: If token creation fails.
    """
    daily_api_key = os.environ.get("DAILY_API_KEY")
    if not daily_api_key:
        raise RuntimeError("DAILY_API_KEY environment variable not set")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{DAILY_API_URL}/meeting-tokens",
            headers={
                "Authorization": f"Bearer {daily_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "properties": {
                    "room_name": room_name,
                    "is_owner": True,  # Bot needs owner permissions for audio
                    "user_name": bot_name,
                    "start_video_off": True,
                    "start_audio_off": False,
                    "exp": int(time.time()) + 7200,  # 2 hours
                },
            },
        )

        if response.status_code not in (200, 201):
            error_text = response.text
            logger.error(f"Failed to create bot token: {error_text}")
            raise RuntimeError(f"Failed to create bot token: {error_text}")

        token_data = response.json()
        return token_data["token"]


def get_effective_interview_config(interview, template):
    """Resolve content and style from interview + template."""
    return {
        "questions": interview.questions or (template.questions if template else None),
        "research_summary": interview.research_summary or (template.research_summary if template else None),
        "angle": interview.angle or (template.angle if template else None),
        "angle_secondary": interview.angle_secondary or (template.angle_secondary if template else None),
        "angle_custom": interview.angle_custom or (template.angle_custom if template else None),
    }


# Track active interviews to prevent duplicate bot sessions
# Maps interview_id -> asyncio.Task
_active_interviews: dict[UUID, asyncio.Task] = {}


def _extract_questions_list(project: Project) -> list[str]:
    """Extract question text list from project.questions JSONB.

    The questions field has structure:
    {
        "questions": [
            {"id": 1, "text": "...", "type": "opening", "follow_ups": [...]},
            ...
        ]
    }

    Args:
        project: The Project model instance.

    Returns:
        List of question text strings.
    """
    if not project.questions:
        return []

    questions_data = project.questions.get("questions", [])
    return [q.get("text", "") for q in questions_data if q.get("text")]


async def start_voice_interview(
    interview: Interview,
    project: Project,
    is_returning: bool = False,
    previous_transcript: list[dict] | None = None,
    previous_context: list[dict] | None = None,
    angle: str | None = None,
    angle_secondary: str | None = None,
    angle_custom: str | None = None,
    effective_questions: dict | None = None,
) -> tuple[list[dict[str, Any]], list[dict], str | None]:
    """Start a voice interview.

    Args:
        interview: The Interview model instance with room_name and room_token.
        project: The Project model instance with topic and questions.
        is_returning: Whether this is a returning guest.
        previous_transcript: Previous transcript entries for returning guests.
        previous_context: Previous conversation context for returning guests.
        angle: Primary interview angle/style.
        angle_secondary: Secondary interview angle/style.
        angle_custom: Custom angle instructions.

    Returns:
        Tuple of (transcript entries, conversation history, detected_mode).

    Raises:
        ValueError: If interview is missing room credentials.
        RuntimeError: If the pipeline fails to start.
    """
    if not interview.room_name:
        raise ValueError(f"Interview {interview.id} has no room_name")

    # Build room URL from room_name
    # The room_name is like "boswell-{interview_id[:8]}"
    daily_domain = os.environ.get("DAILY_DOMAIN", "emirbot")
    room_url = f"https://{daily_domain}.daily.co/{interview.room_name}"

    # Create a fresh bot token with owner permissions
    # The bot needs its own token separate from the guest's token
    room_token = await create_bot_token(interview.room_name, "Boswell")

    # Extract questions
    # - If template is set: effective_questions contains template questions or generated questions
    # - If no template: falls back to project.questions
    if effective_questions:
        # Template questions come as JSONB: {"questions": [{"text": "...", ...}, ...]}
        questions_data = effective_questions.get("questions", [])
        questions = [q.get("text", "") for q in questions_data if q.get("text")]
    else:
        questions = _extract_questions_list(project)

    if not questions:
        logger.warning(
            f"Project {project.id} has no questions, using default greeting"
        )
        questions = [
            "Can you tell me a bit about yourself and your background?",
            "What brings you to this interview today?",
            "Is there anything specific you'd like to discuss?",
        ]

    # Get guest name and context
    guest_name = getattr(interview, 'name', None) or "Guest"
    interview_context = getattr(interview, 'context_notes', None)
    intro_prompt = getattr(project, 'intro_prompt', None)

    # Build the system prompt with interview context
    system_prompt = build_system_prompt(
        topic=project.topic,
        questions=questions,
        research_summary=project.research_summary,
        interview_context=interview_context,
        interviewee_name=guest_name,
        intro_prompt=intro_prompt,
        target_minutes=project.target_minutes,
        max_minutes=project.target_minutes + 15,  # Allow 15 min buffer
        angle=angle,
        angle_secondary=angle_secondary,
        angle_custom=angle_custom,
    )

    # Add returning guest prompt if applicable
    detected_mode = None
    if is_returning and previous_transcript:
        from boswell.voice.prompts import build_returning_guest_prompt
        returning_prompt = build_returning_guest_prompt(
            previous_transcript=previous_transcript,
            guest_name=guest_name,
        )
        system_prompt = system_prompt + "\n\n" + returning_prompt

    logger.info(
        f"Starting voice interview {interview.id} "
        f"(room={interview.room_name}, topic='{project.topic}')"
    )

    # Run the Pipecat pipeline (blocks until interview ends)
    transcript_entries, conversation_history, detected_mode = await run_interview(
        room_url=room_url,
        room_token=room_token,
        system_prompt=system_prompt,
        bot_name="Boswell",
        guest_name=guest_name,
    )

    logger.info(
        f"Interview completed for {interview.id}: "
        f"{len(transcript_entries)} transcript entries"
    )

    return transcript_entries, conversation_history, detected_mode


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


async def complete_interview(
    db: AsyncSession,
    interview_id: UUID,
    transcript_entries: list[dict[str, Any]],
    conversation_history: list[dict],
    mode: str | None = None,
) -> None:
    """Complete an interview by saving transcript and updating status.

    Args:
        db: Database session.
        interview_id: UUID of the interview.
        transcript_entries: List of transcript entry dictionaries.
        conversation_history: List of conversation messages.
        mode: Interview mode (resume, add_detail, fresh_start, or None for new).
    """
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


async def run_interview_task(interview_id: UUID) -> None:
    """Task wrapper for running a single interview.

    This function is spawned as an asyncio task for each interview.
    It handles the full lifecycle: start interview, save transcript, update status.

    Args:
        interview_id: UUID of the interview to run.
    """
    try:
        # Fetch interview and project data
        async with get_session_context() as db:
            result = await db.execute(
                select(Interview)
                .options(selectinload(Interview.project))
                .where(Interview.id == interview_id)
            )
            interview = result.scalar_one_or_none()

            if not interview:
                logger.error(f"Interview {interview_id} not found")
                return

            if not interview.project:
                logger.error(f"Interview {interview_id} has no project")
                return

            # Cache the data we need (relationships won't be accessible outside session)
            project = interview.project
            room_name = interview.room_name
            room_token = interview.room_token
            guest_name = interview.name
            context_notes = interview.context_notes
            interview_mode = interview.interview_mode

            # Check if this is a returning guest
            is_returning = interview_mode == "pending"
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

            # Fetch template if set
            template = None
            if interview.template_id:
                template_result = await db.execute(
                    select(InterviewTemplate).where(InterviewTemplate.id == interview.template_id)
                )
                template = template_result.scalar_one_or_none()

            # Get effective config (resolves interview vs template values)
            config = get_effective_interview_config(interview, template)

            # Get effective questions
            # Priority: 1) template/interview questions, 2) generate from template research, 3) project questions
            effective_questions = None
            if config["questions"]:
                effective_questions = config["questions"]
            elif template:
                # Template is set but has no pre-written questions
                # Generate questions using template's research content or project topic
                research_content = config["research_summary"] or ""
                try:
                    from boswell.ingestion import generate_questions
                    source = "template research" if research_content else "project topic"
                    logger.info(f"Generating questions from {source} for interview {interview_id}")
                    questions_list = await asyncio.to_thread(
                        generate_questions, project.topic, research_content, 12
                    )
                    if questions_list:
                        effective_questions = {
                            "questions": [
                                {"text": q, "type": "generated_from_template"}
                                for q in questions_list
                            ]
                        }
                        logger.info(f"Generated {len(questions_list)} questions from {source} for interview {interview_id}")
                except ImportError:
                    logger.warning("Ingestion module not available for question generation")
                except Exception as e:
                    logger.warning(f"Failed to generate questions from template: {e}")

            # Resolve angle values
            angle_value = config["angle"].value if config["angle"] else None
            angle_secondary_value = config["angle_secondary"].value if config["angle_secondary"] else None
            angle_custom_value = config["angle_custom"]

        # Create a minimal interview object for the voice session
        # (We can't use the SQLAlchemy object outside the session)
        class InterviewData:
            def __init__(self, id, room_name, room_token, name, context_notes):
                self.id = id
                self.room_name = room_name
                self.room_token = room_token
                self.name = name
                self.context_notes = context_notes

        interview_data = InterviewData(
            interview_id,
            room_name,
            room_token,
            guest_name,
            context_notes,
        )

        # Run the interview (this blocks until complete)
        transcript_entries, conversation_history, detected_mode = await start_voice_interview(
            interview_data,
            project,
            is_returning=is_returning,
            previous_transcript=previous_transcript,
            previous_context=previous_context,
            angle=angle_value,
            angle_secondary=angle_secondary_value,
            angle_custom=angle_custom_value,
            effective_questions=effective_questions,
        )

        # Save results in a new session
        async with get_session_context() as db:
            await complete_interview(
                db, interview_id, transcript_entries, conversation_history, detected_mode
            )

    except Exception as e:
        logger.exception(f"Interview failed for {interview_id}: {e}")
        # Don't mark as failed - leave as "started" so it can be retried
        # or manually resolved

    finally:
        # Remove from active interviews
        _active_interviews.pop(interview_id, None)
        logger.info(f"Interview task ended for {interview_id}")


async def find_pending_interviews(db: AsyncSession) -> list[Interview]:
    """Find interviews that are ready to run but don't have an active bot.

    Criteria:
    - status = "started"
    - room_name is not null
    - Not already in _active_interviews

    Args:
        db: Database session.

    Returns:
        List of Interview objects ready to run.
    """
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(
            and_(
                Interview.status == InterviewStatus.started,
                Interview.room_name.isnot(None),
            )
        )
    )
    interviews = list(result.scalars().all())

    # Filter out interviews that are already active
    pending = [i for i in interviews if i.id not in _active_interviews]

    return pending


async def run_voice_worker(
    poll_interval: int = 5,
    max_iterations: int | None = None,
) -> None:
    """Main voice worker loop.

    Polls for interviews with status="started" and room_name set,
    then starts interview bots for each eligible interview.

    Args:
        poll_interval: Seconds to wait between polling when no interviews found.
        max_iterations: Maximum number of poll iterations (None for infinite).
            Useful for testing.
    """
    logger.info(f"Starting voice worker (poll_interval={poll_interval}s)")
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        try:
            async with get_session_context() as db:
                pending_interviews = await find_pending_interviews(db)

                if pending_interviews:
                    logger.info(f"Found {len(pending_interviews)} pending interview(s)")

                for interview in pending_interviews:
                    # Start interview task
                    logger.info(
                        f"Starting interview {interview.id} "
                        f"(room={interview.room_name})"
                    )

                    # Create and track the task
                    task = asyncio.create_task(run_interview_task(interview.id))
                    _active_interviews[interview.id] = task

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
    for interview_id, task in _active_interviews.items():
        if not task.done():
            logger.info(f"Cancelling interview {interview_id}")
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


def is_interview_active(interview_id: UUID) -> bool:
    """Check if an interview is currently active.

    Args:
        interview_id: UUID of the interview.

    Returns:
        True if an interview is active, False otherwise.
    """
    return interview_id in _active_interviews
