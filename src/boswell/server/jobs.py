"""Background job processor for async task processing."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boswell.server.database import get_session_context
from boswell.server.models import JobQueue, JobStatus

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


# Example job handlers (can be moved to separate modules)


@register_job("generate_questions")
async def handle_generate_questions(payload: dict, db: AsyncSession) -> None:
    """Generate interview questions for an interview.

    Expected payload:
        - interview_id: UUID of the interview
    """
    # TODO: Implement question generation logic
    logger.info(f"Generating questions for interview: {payload.get('interview_id')}")


@register_job("send_email")
async def handle_send_email(payload: dict, db: AsyncSession) -> None:
    """Send an email notification.

    Expected payload:
        - to: Email recipient
        - subject: Email subject
        - body: Email body
    """
    # TODO: Implement email sending logic
    logger.info(f"Sending email to: {payload.get('to')}")


@register_job("generate_analysis")
async def handle_generate_analysis(payload: dict, db: AsyncSession) -> None:
    """Generate AI analysis of an interview transcript.

    Expected payload:
        - guest_id: UUID of the guest whose transcript to analyze
    """
    # TODO: Implement analysis generation logic
    logger.info(f"Generating analysis for guest: {payload.get('guest_id')}")
