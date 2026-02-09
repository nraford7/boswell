# src/boswell/server/worker.py
"""Voice worker for conducting interviews.

This worker polls for interviews that have started (status="started"
with a room_name) and launches the Pipecat voice pipeline to conduct the interview.
When the interview completes, it saves the transcript and updates the interview status.
"""

import asyncio
import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import and_, or_, select
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


# Worker identity for claim tracking
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

# Retry backoff configuration
BACKOFF_SECONDS = [30, 120, 600, 1800]  # 30s, 2m, 10m, 30m
MAX_FAILURES = 4

# Maximum concurrent interview tasks per worker
MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "3"))

# Stale claim timeout: if a claim is older than this, treat it as abandoned
# (covers hard crashes where shutdown_voice_worker never runs)
STALE_CLAIM_SECONDS = int(os.environ.get("WORKER_STALE_CLAIM_SECONDS", "1800"))  # 30 minutes


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
    # Import here to avoid circular imports
    from boswell.server.jobs import enqueue_job

    # Save transcript with mode
    await save_transcript(db, interview_id, transcript_entries, conversation_history, mode)

    # Update interview status and mode
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()

    if interview:
        interview.status = InterviewStatus.completed
        interview.completed_at = datetime.now(timezone.utc)
        interview.failure_count = 0
        interview.next_retry_at = None
        interview.claimed_by = None
        interview.claimed_at = None
        if mode:
            interview.interview_mode = mode
        await db.flush()
        logger.info(f"Interview {interview_id} marked as completed (mode={mode})")

        # Enqueue analysis job to generate insights and suggested questions
        await enqueue_job(
            db,
            job_type="generate_analysis",
            payload={"guest_id": str(interview_id)},
        )
        logger.info(f"Enqueued generate_analysis job for interview {interview_id}")


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
        try:
            async with get_session_context() as db:
                result = await db.execute(
                    select(Interview).where(Interview.id == interview_id)
                )
                interview = result.scalar_one_or_none()
                if interview:
                    interview.claimed_by = None
                    interview.claimed_at = None
                    interview.failure_count = (interview.failure_count or 0) + 1

                    if interview.failure_count >= MAX_FAILURES:
                        interview.status = InterviewStatus.expired
                        logger.error(
                            f"Interview {interview_id} failed {MAX_FAILURES} times, marking expired"
                        )
                    else:
                        backoff_idx = min(interview.failure_count - 1, len(BACKOFF_SECONDS) - 1)
                        interview.next_retry_at = datetime.now(timezone.utc) + timedelta(
                            seconds=BACKOFF_SECONDS[backoff_idx]
                        )
                        logger.warning(
                            f"Interview {interview_id} failed (count={interview.failure_count}), "
                            f"retry after {BACKOFF_SECONDS[backoff_idx]}s"
                        )
                    await db.commit()
        except Exception as release_err:
            logger.error(f"Failed to update failure state for {interview_id}: {release_err}")

    finally:
        logger.info(f"Interview task ended for {interview_id}")


async def claim_next_interview(db: AsyncSession) -> Interview | None:
    """Atomically claim the next interview ready to run.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent duplicate claims
    across multiple worker instances. Also reclaims interviews with stale
    claims (older than STALE_CLAIM_SECONDS) to recover from hard crashes.

    Args:
        db: Database session.

    Returns:
        The claimed Interview, or None if nothing is available.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=STALE_CLAIM_SECONDS)

    stmt = (
        select(Interview)
        .where(
            and_(
                Interview.status == InterviewStatus.started,
                Interview.room_name.isnot(None),
                or_(
                    # Unclaimed interviews
                    Interview.claimed_by.is_(None),
                    # Stale claims from crashed workers
                    Interview.claimed_at < stale_cutoff,
                ),
                (Interview.next_retry_at.is_(None)) | (Interview.next_retry_at <= now),
            )
        )
        .order_by(Interview.started_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    interview = result.scalar_one_or_none()

    if interview:
        if interview.claimed_by and interview.claimed_by != WORKER_ID:
            logger.warning(
                f"Reclaiming stale interview {interview.id} "
                f"(was claimed by {interview.claimed_by} at {interview.claimed_at})"
            )
        interview.claimed_by = WORKER_ID
        interview.claimed_at = now
        await db.flush()
        logger.info(f"Claimed interview {interview.id} (worker={WORKER_ID})")

    return interview


async def run_voice_worker(
    poll_interval: int = 5,
    max_iterations: int | None = None,
) -> None:
    """Main voice worker loop with bounded concurrency.

    Polls for interviews with status="started" and room_name set,
    atomically claims them via DB lock, then starts interview bots
    up to MAX_CONCURRENT at a time.

    Args:
        poll_interval: Seconds to wait between polling when no interviews found.
        max_iterations: Maximum number of poll iterations (None for infinite).
            Useful for testing.
    """
    logger.info(f"Starting voice worker (id={WORKER_ID}, max_concurrent={MAX_CONCURRENT})")
    iterations = 0
    active_tasks: dict[UUID, asyncio.Task] = {}

    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        # Clean up finished tasks
        done = [iid for iid, task in active_tasks.items() if task.done()]
        for iid in done:
            active_tasks.pop(iid)

        # Only claim if under capacity
        if len(active_tasks) < MAX_CONCURRENT:
            try:
                async with get_session_context() as db:
                    interview = await claim_next_interview(db)
                    if interview:
                        logger.info(f"Starting interview {interview.id} (room={interview.room_name})")
                        task = asyncio.create_task(run_interview_task(interview.id))
                        active_tasks[interview.id] = task
                        continue  # Check for more immediately
            except Exception as e:
                logger.exception(f"Voice worker error: {e}")

        await asyncio.sleep(poll_interval)

    # Cancel remaining tasks on shutdown
    for task in active_tasks.values():
        task.cancel()

    logger.info("Voice worker stopped")


async def shutdown_voice_worker() -> None:
    """Gracefully shutdown the voice worker.

    With the new DB-backed claim mechanism, active task cancellation is
    handled by run_voice_worker when it exits its loop. This function
    releases any stale claims owned by this worker so they can be
    picked up by another instance.
    """
    logger.info(f"Releasing stale claims for worker {WORKER_ID}")
    try:
        async with get_session_context() as db:
            result = await db.execute(
                select(Interview).where(
                    and_(
                        Interview.claimed_by == WORKER_ID,
                        Interview.status == InterviewStatus.started,
                    )
                )
            )
            stale = list(result.scalars().all())
            for interview in stale:
                interview.claimed_by = None
                interview.claimed_at = None
                logger.info(f"Released stale claim on interview {interview.id}")
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to release stale claims: {e}")

    logger.info("Voice worker shutdown complete")
