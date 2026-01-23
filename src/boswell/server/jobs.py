"""Background job processor for async task processing."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session_context
from boswell.server.models import (
    Analysis,
    Interview,
    Project,
    JobQueue,
    JobStatus,
    Transcript,
)

logger = logging.getLogger(__name__)

# Type alias for job handler functions
JobHandler = Callable[[dict, AsyncSession], Awaitable[Any]]

# Job handlers registry
JOB_HANDLERS: Dict[str, JobHandler] = {}


def register_job(job_type: str) -> Callable[[JobHandler], JobHandler]:
    """Decorator to register a job handler.

    Usage:
        @register_job("send_email")
        async def handle_send_email(payload: dict, db: AsyncSession) -> None:
            # Process the job
            pass
    """

    def decorator(func: JobHandler) -> JobHandler:
        JOB_HANDLERS[job_type] = func
        logger.info(f"Registered job handler for: {job_type}")
        return func

    return decorator


async def process_job(job: JobQueue, db: AsyncSession) -> None:
    """Process a single job by calling its registered handler.

    Args:
        job: The job to process.
        db: Database session for the handler to use.

    Raises:
        ValueError: If no handler is registered for the job type.
    """
    handler = JOB_HANDLERS.get(job.job_type)
    if not handler:
        raise ValueError(f"Unknown job type: {job.job_type}")

    await handler(job.payload or {}, db)


async def claim_next_job(db: AsyncSession) -> JobQueue | None:
    """Atomically claim the next pending job that is ready to run.

    Args:
        db: Database session.

    Returns:
        The claimed job, or None if no jobs are available.
    """
    now = datetime.now(timezone.utc)

    # Find the next pending job that's ready to run
    # Jobs with run_at=None or run_at <= now are ready
    stmt = (
        select(JobQueue)
        .where(
            and_(
                JobQueue.status == JobStatus.pending,
                JobQueue.attempts < JobQueue.max_attempts,
                (JobQueue.run_at.is_(None)) | (JobQueue.run_at <= now),
            )
        )
        .order_by(JobQueue.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    result = await db.execute(stmt)
    job = result.scalar_one_or_none()

    if job:
        # Mark as processing
        job.status = JobStatus.processing
        job.started_at = now
        job.attempts += 1
        await db.flush()

    return job


async def complete_job(job: JobQueue, db: AsyncSession) -> None:
    """Mark a job as completed.

    Args:
        job: The job to complete.
        db: Database session.
    """
    job.status = JobStatus.completed
    job.completed_at = datetime.now(timezone.utc)
    job.error = None
    await db.flush()


async def fail_job(job: JobQueue, error: str, db: AsyncSession) -> None:
    """Mark a job as failed, or return to pending for retry.

    Args:
        job: The job that failed.
        error: Error message describing the failure.
        db: Database session.
    """
    job.error = error

    if job.attempts >= job.max_attempts:
        # Max retries reached, mark as permanently failed
        job.status = JobStatus.failed
        job.completed_at = datetime.now(timezone.utc)
        logger.error(
            f"Job {job.id} permanently failed after {job.attempts} attempts: {error}"
        )
    else:
        # Return to pending for retry
        job.status = JobStatus.pending
        job.started_at = None
        logger.warning(
            f"Job {job.id} failed (attempt {job.attempts}/{job.max_attempts}): {error}"
        )

    await db.flush()


async def run_worker(
    poll_interval: int = 5,
    max_iterations: int | None = None,
) -> None:
    """Main worker loop that polls for and processes jobs.

    Args:
        poll_interval: Seconds to wait between polling when no jobs found.
        max_iterations: Maximum number of poll iterations (None for infinite).
            Useful for testing.
    """
    logger.info(f"Starting job worker (poll_interval={poll_interval}s)")
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        try:
            async with get_session_context() as db:
                job = await claim_next_job(db)

                if job:
                    logger.info(
                        f"Processing job {job.id} (type={job.job_type}, "
                        f"attempt={job.attempts}/{job.max_attempts})"
                    )

                    try:
                        await process_job(job, db)
                        await complete_job(job, db)
                        logger.info(f"Job {job.id} completed successfully")
                    except Exception as e:
                        logger.exception(f"Job {job.id} failed with error: {e}")
                        await fail_job(job, str(e), db)

                    # Immediately check for more jobs
                    continue

        except Exception as e:
            logger.exception(f"Worker error: {e}")

        # No job found or error occurred, wait before polling again
        await asyncio.sleep(poll_interval)

    logger.info("Job worker stopped")


async def enqueue_job(
    db: AsyncSession,
    job_type: str,
    payload: dict | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
) -> JobQueue:
    """Add a job to the queue.

    Args:
        db: Database session.
        job_type: Type of job (must have a registered handler).
        payload: Job-specific data passed to the handler.
        run_at: Optional scheduled time (None = run immediately).
        max_attempts: Maximum number of retry attempts.

    Returns:
        The created job.
    """
    job = JobQueue(
        job_type=job_type,
        payload=payload or {},
        run_at=run_at,
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()

    logger.info(
        f"Enqueued job {job.id} (type={job_type}, run_at={run_at})"
    )

    return job


# ============================================================================
# Job Handlers
# ============================================================================


@register_job("generate_questions")
async def handle_generate_questions(payload: dict, db: AsyncSession) -> None:
    """Generate interview questions for an interview.

    Fetches the interview from the database, generates questions based on
    the topic and any template settings, then updates the interview record.

    Expected payload:
        - interview_id: UUID of the interview

    Raises:
        ValueError: If interview_id is missing or interview not found.
    """
    interview_id_str = payload.get("interview_id")
    if not interview_id_str:
        raise ValueError("Missing required field: interview_id")

    try:
        interview_id = UUID(interview_id_str)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid interview_id format: {interview_id_str}") from e

    logger.info(f"Generating questions for interview: {interview_id}")

    # Fetch the interview with template relationship
    stmt = (
        select(Interview)
        .options(selectinload(Interview.template))
        .where(Interview.id == interview_id)
    )
    result = await db.execute(stmt)
    interview = result.scalar_one_or_none()

    if not interview:
        raise ValueError(f"Interview not found: {interview_id}")

    # Extract context for question generation
    topic = interview.topic
    target_minutes = interview.target_minutes
    prompt_modifier = None
    if interview.template:
        prompt_modifier = interview.template.prompt_modifier

    logger.info(
        f"Generating questions for topic='{topic}', "
        f"target_minutes={target_minutes}, "
        f"has_modifier={prompt_modifier is not None}"
    )

    # TODO: Call Claude API to generate questions
    # For now, generate stub questions
    stub_questions = _generate_stub_questions(topic, target_minutes)

    # Update the interview with generated questions
    interview.questions = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "questions": stub_questions,
        "topic": topic,
        "target_minutes": target_minutes,
    }
    await db.flush()

    logger.info(
        f"Generated {len(stub_questions)} questions for interview {interview_id}"
    )


def _generate_stub_questions(topic: str, target_minutes: int) -> list[dict]:
    """Generate stub questions for testing.

    Args:
        topic: The interview topic.
        target_minutes: Target interview duration.

    Returns:
        List of question dictionaries.
    """
    # Estimate ~3 minutes per question for pacing
    num_questions = max(3, target_minutes // 3)

    questions = [
        {
            "id": 1,
            "text": f"Can you tell me about your background and how you got involved with {topic}?",
            "type": "opening",
            "follow_ups": [
                "What initially drew you to this area?",
                "How has your perspective evolved over time?",
            ],
        },
        {
            "id": 2,
            "text": f"What do you see as the most significant challenges in {topic} today?",
            "type": "core",
            "follow_ups": [
                "How do you think these challenges might be addressed?",
                "Are there any that you find particularly concerning?",
            ],
        },
        {
            "id": 3,
            "text": f"What opportunities or developments in {topic} are you most excited about?",
            "type": "core",
            "follow_ups": [
                "What impact do you think this could have?",
                "When do you expect to see progress in this area?",
            ],
        },
    ]

    # Add more questions if needed for longer interviews
    if num_questions > 3:
        questions.append({
            "id": 4,
            "text": f"Based on your experience, what advice would you give to someone just starting in {topic}?",
            "type": "advice",
            "follow_ups": [
                "What mistakes do you see people commonly making?",
                "What resources would you recommend?",
            ],
        })

    if num_questions > 4:
        questions.append({
            "id": 5,
            "text": f"Looking ahead, where do you see {topic} in the next 5-10 years?",
            "type": "closing",
            "follow_ups": [
                "What would need to happen to achieve that vision?",
                "What are the biggest uncertainties?",
            ],
        })

    return questions[:num_questions]


@register_job("send_email")
async def handle_send_email(payload: dict, db: AsyncSession) -> None:
    """Send an email notification.

    Uses the email module to send emails via Resend API.

    Expected payload:
        - to: Email recipient address
        - subject: Email subject line
        - body: Email body content
        - template: (optional) Template name for rendering
        - context: (optional) Template context variables

    Raises:
        ValueError: If required fields are missing.
        RuntimeError: If email sending fails.
    """
    # Import here to avoid circular dependency
    from boswell.server.email import send_email

    to = payload.get("to")
    subject = payload.get("subject")
    body = payload.get("body")

    if not to:
        raise ValueError("Missing required field: to")
    if not subject:
        raise ValueError("Missing required field: subject")
    if not body:
        raise ValueError("Missing required field: body")

    template = payload.get("template")
    context = payload.get("context", {})

    logger.info(f"Sending email to: {to}, subject: {subject}")

    success = await send_email(
        to=to,
        subject=subject,
        body=body,
        template=template,
        context=context,
    )

    if not success:
        raise RuntimeError(f"Failed to send email to {to}")

    logger.info(f"Email sent successfully to: {to}")


@register_job("generate_analysis")
async def handle_generate_analysis(payload: dict, db: AsyncSession) -> None:
    """Generate AI analysis of an interview transcript.

    Fetches the interview and its transcript from the database, generates
    an analysis using Claude, then creates or updates the Analysis record.

    Expected payload:
        - guest_id: UUID of the interview whose transcript to analyze

    Raises:
        ValueError: If guest_id is missing, interview not found, or no transcript.
    """
    interview_id_str = payload.get("guest_id")  # Keep payload key for backward compatibility
    if not interview_id_str:
        raise ValueError("Missing required field: guest_id")

    try:
        interview_id = UUID(interview_id_str)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid interview_id format: {interview_id_str}") from e

    logger.info(f"Generating analysis for interview: {interview_id}")

    # Fetch interview with transcript and project relationships
    stmt = (
        select(Interview)
        .options(
            selectinload(Interview.transcript),
            selectinload(Interview.project),
            selectinload(Interview.analysis),
        )
        .where(Interview.id == interview_id)
    )
    result = await db.execute(stmt)
    interview = result.scalar_one_or_none()

    if not interview:
        raise ValueError(f"Interview not found: {interview_id}")

    if not interview.transcript:
        raise ValueError(f"No transcript found for interview: {interview_id}")

    # Extract transcript entries for analysis
    transcript_entries = interview.transcript.entries or []
    project_topic = interview.project.topic if interview.project else "Unknown Topic"

    logger.info(
        f"Analyzing transcript for '{interview.name}' "
        f"on topic '{project_topic}', "
        f"entries={len(transcript_entries)}"
    )

    # TODO: Call Claude API to generate analysis
    # For now, generate stub analysis
    stub_analysis = _generate_stub_analysis(
        interviewee_name=interview.name,
        topic=project_topic,
        transcript_entries=transcript_entries,
    )

    # Create or update Analysis record
    if interview.analysis:
        # Update existing analysis
        interview.analysis.insights = stub_analysis["insights"]
        interview.analysis.summary_md = stub_analysis["summary_md"]
        logger.info(f"Updated existing analysis for interview: {interview_id}")
    else:
        # Create new analysis
        analysis = Analysis(
            interview_id=interview_id,
            insights=stub_analysis["insights"],
            summary_md=stub_analysis["summary_md"],
        )
        db.add(analysis)
        logger.info(f"Created new analysis for interview: {interview_id}")

    await db.flush()
    logger.info(f"Analysis generation complete for interview: {interview_id}")


def _generate_stub_analysis(
    interviewee_name: str,
    topic: str,
    transcript_entries: list[dict],
) -> dict:
    """Generate stub analysis for testing.

    Args:
        interviewee_name: Name of the interviewee.
        topic: Topic of the interview.
        transcript_entries: List of transcript entry dictionaries.

    Returns:
        Dictionary with insights and summary_md fields.
    """
    num_entries = len(transcript_entries)

    insights = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interviewee_name": interviewee_name,
        "topic": topic,
        "transcript_length": num_entries,
        "key_themes": [
            f"Theme related to {topic}",
            "Personal experiences and background",
            "Future outlook and predictions",
        ],
        "notable_quotes": [
            "[Quote extraction will be implemented with Claude integration]"
        ],
        "sentiment": {
            "overall": "positive",
            "confidence": 0.75,
        },
        "topics_discussed": [
            {"topic": topic, "depth": "detailed"},
            {"topic": "background", "depth": "moderate"},
            {"topic": "future outlook", "depth": "brief"},
        ],
    }

    summary_md = f"""# Interview Analysis: {topic}

## Interviewee
**{interviewee_name}**

## Overview
This interview covered {topic} with {interviewee_name}. The conversation
included {num_entries} exchanges and touched on several key themes.

## Key Themes
1. **Theme related to {topic}** - Core discussion around the main topic
2. **Personal experiences** - Background and journey in this area
3. **Future outlook** - Predictions and expectations going forward

## Notable Insights
- [Detailed insights will be generated with Claude integration]

## Summary
The interview provided valuable perspectives on {topic}. The interviewee shared
their experiences and offered thoughtful commentary on current challenges
and future opportunities.

---
*Analysis generated at {datetime.now(timezone.utc).isoformat()}*
*Note: This is a stub analysis - full AI analysis coming soon*
"""

    return {
        "insights": insights,
        "summary_md": summary_md,
    }
