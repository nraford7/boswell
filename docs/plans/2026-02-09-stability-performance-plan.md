# Boswell Stability & Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stabilize the execution model (jobs worker, interview claiming, bounded concurrency), move slow work off the request path, cut data/token bloat, and optimize runtime delivery.

**Architecture:** Add a dedicated jobs worker service alongside the existing voice worker. Add DB-backed lease/claim columns to the guests table so voice workers atomically claim interviews. Move ingestion, question generation, and email sends into the job queue. Refactor dashboard/detail queries to use aggregate counts and avoid loading full transcript/analysis payloads. Gate debug audio logging behind an env flag.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Alembic, Pipecat-AI, Vite/React

---

## Phase 1: Worker Reliability (Week 1)

### Task 1: Create dedicated jobs worker entrypoint

The `jobs.run_worker()` loop exists but is never started. Only `run_voice_worker()` runs via `__main__.py`. We need a separate entrypoint and docker-compose service for the jobs worker.

**Files:**
- Create: `src/boswell/server/jobs_main.py`
- Modify: `scripts/start_worker.sh:16-21`
- Create: `scripts/start_jobs.sh`
- Modify: `docker-compose.yml:83` (add jobs service after worker)

**Step 1: Write the failing test**

Create `tests/test_jobs_worker.py`:

```python
"""Tests for the jobs worker entrypoint and service."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from boswell.server.jobs import enqueue_job, run_worker, claim_next_job, JobStatus


@pytest.mark.asyncio
async def test_run_worker_processes_enqueued_job():
    """Jobs worker should pick up and process a pending job."""
    processed = []

    # Patch the generate_analysis handler to track calls
    with patch("boswell.server.jobs.JOB_HANDLERS", {
        "test_job": AsyncMock(side_effect=lambda payload, db: processed.append(payload))
    }):
        from boswell.server.database import get_session_context
        async with get_session_context() as db:
            await enqueue_job(db, "test_job", {"key": "value"})
            await db.commit()

        # Run worker for 1 iteration
        await run_worker(poll_interval=0, max_iterations=1)

    assert len(processed) == 1
    assert processed[0]["key"] == "value"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_jobs_worker.py::test_run_worker_processes_enqueued_job -v`
Expected: FAIL (test infrastructure may need DB setup — adjust if needed)

**Step 3: Create jobs_main.py entrypoint**

Create `src/boswell/server/jobs_main.py`:

```python
"""Entry point for running the jobs worker.

This module allows running the jobs worker as a module:
    python -m boswell.server.jobs_main

The worker polls the job_queue table for pending jobs and processes them.
"""

import asyncio
import logging
import signal
import sys

from boswell.server.jobs import run_worker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point for the jobs worker."""
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    logger.info("Starting Boswell jobs worker")

    worker_task = asyncio.create_task(run_worker())

    await shutdown_event.wait()

    logger.info("Initiating graceful shutdown...")
    worker_task.cancel()

    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    logger.info("Jobs worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Create start_jobs.sh**

Create `scripts/start_jobs.sh`:

```bash
#!/bin/bash
# Boswell Jobs Worker Startup Script
#
# Processes background jobs: analysis generation, email sending, etc.

set -e

echo "Starting Boswell jobs worker..."
exec python -m boswell.server.jobs_main
```

**Step 5: Add jobs service to docker-compose.yml**

Add after the `worker` service block (after line 82):

```yaml
  # ==========================================================================
  # Jobs Worker Service
  # ==========================================================================
  # Processes background jobs: analysis generation, email, question generation.
  jobs:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: boswell-jobs
    command: ["./scripts/start_jobs.sh"]
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+asyncpg://boswell:boswell@db:5432/boswell
    volumes:
      - ./src:/app/src:ro
    depends_on:
      db:
        condition: service_healthy
      web:
        condition: service_started
    restart: unless-stopped
```

**Step 6: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_jobs_worker.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/boswell/server/jobs_main.py scripts/start_jobs.sh docker-compose.yml tests/test_jobs_worker.py
git commit -m "feat: add dedicated jobs worker entrypoint and service"
```

---

### Task 2: Add DB-backed interview claim/lease mechanism

Currently `worker.py:526` uses in-memory `_active_interviews` dict to prevent duplicates, but this doesn't work across multiple worker instances. The `guests` table already has `claimed_by` and `claimed_at` columns (from initial migration, lines 160-161) but they're never used.

**Files:**
- Modify: `src/boswell/server/worker.py:95-97` (remove `_active_interviews` dict)
- Modify: `src/boswell/server/worker.py:512-541` (`find_pending_interviews` → atomic claim)
- Modify: `src/boswell/server/worker.py:501-508` (failure handling)
- Create: `tests/test_worker_claim.py`

**Step 1: Write the failing test**

Create `tests/test_worker_claim.py`:

```python
"""Tests for worker interview claim/lease mechanism."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_claim_interview_atomic():
    """Only one worker should be able to claim an interview."""
    from boswell.server.worker import claim_interview

    # This test verifies the SQL uses FOR UPDATE SKIP LOCKED
    # so two concurrent claims on the same interview only succeed once
    # (Requires integration test with real DB — mark as such)
    pass  # Placeholder — real test in integration suite


@pytest.mark.asyncio
async def test_failed_interview_marked_with_error_status():
    """Failed interviews should transition to a backoff state, not stay 'started'."""
    from boswell.server.worker import handle_interview_failure

    # Verify that after failure, status is set appropriately
    # and claimed_by is cleared
    pass  # Placeholder — real test in integration suite
```

**Step 2: Implement atomic claim in worker.py**

Replace `find_pending_interviews` (lines 512-541) and the `_active_interviews` dict approach with an atomic claim function. In `src/boswell/server/worker.py`:

Remove the global `_active_interviews` dict (line 95-97). Replace with:

```python
import socket
import os

# Worker identity for claim tracking
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

# Maximum concurrent interview tasks per worker
MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "3"))
```

Replace `find_pending_interviews` with:

```python
async def claim_next_interview(db: AsyncSession) -> Interview | None:
    """Atomically claim the next interview ready to run.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent duplicate claims
    across multiple worker instances.

    Returns:
        Claimed Interview or None if nothing available.
    """
    stmt = (
        select(Interview)
        .options(selectinload(Interview.project))
        .where(
            and_(
                Interview.status == InterviewStatus.started,
                Interview.room_name.isnot(None),
                Interview.claimed_by.is_(None),
            )
        )
        .order_by(Interview.started_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    interview = result.scalar_one_or_none()

    if interview:
        interview.claimed_by = WORKER_ID
        interview.claimed_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(f"Claimed interview {interview.id} (worker={WORKER_ID})")

    return interview
```

Update `run_voice_worker` to use bounded concurrency:

```python
async def run_voice_worker(
    poll_interval: int = 5,
    max_iterations: int | None = None,
) -> None:
    """Main voice worker loop with bounded concurrency."""
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
```

Update the failure handler in `run_interview_task` (lines 501-508) to release the claim:

```python
    except Exception as e:
        logger.exception(f"Interview failed for {interview_id}: {e}")
        # Release claim and set error state
        try:
            async with get_session_context() as db:
                result = await db.execute(
                    select(Interview).where(Interview.id == interview_id)
                )
                interview = result.scalar_one_or_none()
                if interview:
                    interview.claimed_by = None
                    interview.claimed_at = None
                    # Leave as "started" for manual resolution
                    await db.commit()
        except Exception as release_err:
            logger.error(f"Failed to release claim for {interview_id}: {release_err}")
```

Also remove `_active_interviews.pop(interview_id, None)` from the `finally` block.

**Step 3: Run tests**

Run: `PYTHONPATH=src pytest tests/test_worker_claim.py -v`
Expected: PASS (placeholder tests pass; real validation is integration)

**Step 4: Commit**

```bash
git add src/boswell/server/worker.py tests/test_worker_claim.py
git commit -m "feat: add DB-backed interview claim with bounded concurrency"
```

---

### Task 3: Add retry backoff for failed interviews

Currently failed interviews stay as `started` and get immediately re-polled. Add a backoff mechanism.

**Files:**
- Create: new Alembic migration (add `failure_count` and `next_retry_at` columns to guests)
- Modify: `src/boswell/server/models.py` (add columns)
- Modify: `src/boswell/server/worker.py` (filter by next_retry_at, increment failure_count)

**Step 1: Generate migration**

Run: `cd /Users/noahraford/Projects/boswell && PYTHONPATH=src alembic revision --autogenerate -m "Add retry backoff columns to guests"`

**Step 2: Verify and adjust migration**

The migration should add:
- `failure_count` INTEGER DEFAULT 0
- `next_retry_at` DATETIME(timezone=True) NULLABLE

**Step 3: Add columns to models.py**

In `src/boswell/server/models.py`, add to the Interview class (after `interview_mode` field):

```python
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Step 4: Update claim query to respect backoff**

In `claim_next_interview`, add filter:

```python
from datetime import timedelta

# In the where clause, add:
(Interview.next_retry_at.is_(None)) | (Interview.next_retry_at <= datetime.now(timezone.utc)),
```

**Step 5: Update failure handler to set backoff**

```python
# In the except block of run_interview_task:
BACKOFF_SECONDS = [30, 120, 600, 1800]  # 30s, 2m, 10m, 30m
MAX_FAILURES = 4

if interview:
    interview.claimed_by = None
    interview.claimed_at = None
    interview.failure_count = (interview.failure_count or 0) + 1

    if interview.failure_count >= MAX_FAILURES:
        interview.status = InterviewStatus.expired
        logger.error(f"Interview {interview_id} failed {MAX_FAILURES} times, marking expired")
    else:
        backoff_idx = min(interview.failure_count - 1, len(BACKOFF_SECONDS) - 1)
        interview.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=BACKOFF_SECONDS[backoff_idx])
        logger.warning(f"Interview {interview_id} failed (count={interview.failure_count}), retry after {BACKOFF_SECONDS[backoff_idx]}s")
```

**Step 6: Run migration**

Run: `PYTHONPATH=src alembic upgrade head`

**Step 7: Run tests**

Run: `PYTHONPATH=src pytest tests/ -v`
Expected: All pass

**Step 8: Commit**

```bash
git add src/boswell/server/models.py src/boswell/server/worker.py src/boswell/server/migrations/versions/
git commit -m "feat: add retry backoff for failed interviews with bounded failures"
```

---

## Phase 2: Move Slow Request Work to Jobs (Week 2)

### Task 4: Move project ingestion + question generation to job queue

Currently `admin.py:172-253` does file reading, URL fetching, and question generation inline during the POST request. Move this to the jobs queue.

**Files:**
- Modify: `src/boswell/server/routes/admin.py:136-254`
- Modify: `src/boswell/server/jobs.py` (add `process_project_research` handler)
- Create: new Alembic migration (add `processing_status` to interviews/projects table)
- Modify: `src/boswell/server/models.py` (add processing_status column)

**Step 1: Add processing_status column**

Generate migration to add `processing_status` (String(20), default="ready") to the `interviews` (projects) table. Values: "pending", "processing", "ready", "failed".

In `models.py`, add to Project class:

```python
    processing_status: Mapped[str] = mapped_column(
        String(20), default="ready", server_default="ready", nullable=False
    )
```

**Step 2: Add job handler in jobs.py**

```python
@register_job("process_project_research")
async def handle_process_project_research(payload: dict, db: AsyncSession) -> None:
    """Process research materials and generate questions for a project.

    Expected payload:
        - project_id: UUID of the project
        - research_urls: list of URL strings
        - research_file_paths: list of temp file paths with original names
        - topic: project topic string
    """
    project_id = UUID(payload["project_id"])

    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if not project:
        raise ValueError(f"Project not found: {project_id}")

    project.processing_status = "processing"
    await db.flush()

    try:
        research_parts = []

        # Process files
        for file_info in payload.get("research_file_paths", []):
            try:
                doc_content = await asyncio.to_thread(read_document, Path(file_info["path"]))
                if doc_content:
                    research_parts.append(f"=== Document: {file_info['name']} ===\n{doc_content}")
            except Exception as e:
                logger.warning(f"Failed to process file {file_info['name']}: {e}")
            finally:
                Path(file_info["path"]).unlink(missing_ok=True)

        # Process URLs
        for url in payload.get("research_urls", []):
            try:
                url_content = await asyncio.to_thread(fetch_url, url)
                if url_content:
                    research_parts.append(f"=== URL: {url} ===\n{url_content}")
            except Exception as e:
                logger.warning(f"Failed to fetch URL {url}: {e}")

        research_summary = "\n\n".join(research_parts) if research_parts else None
        project.research_summary = research_summary

        # Generate questions if no template
        if not project.public_template_id:
            try:
                research_content = research_summary or ""
                questions_list = await asyncio.to_thread(
                    generate_questions, payload["topic"], research_content, 12
                )
                if questions_list:
                    project.questions = {
                        "questions": [
                            {"id": i + 1, "text": q, "type": "generated"}
                            for i, q in enumerate(questions_list)
                        ]
                    }
            except Exception as e:
                logger.warning(f"Failed to generate questions: {e}")

        project.processing_status = "ready"
    except Exception as e:
        project.processing_status = "failed"
        raise
```

**Step 3: Update admin.py project creation to enqueue instead**

Replace the inline processing in `admin.py:172-253` with:

```python
    # Save temp files for async processing
    research_file_paths = []
    if research_files and INGESTION_AVAILABLE:
        for upload_file in research_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                suffix = Path(upload_file.filename).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    content = await upload_file.read()
                    tmp.write(content)
                    research_file_paths.append({"path": tmp.name, "name": upload_file.filename})

    # Parse URLs
    research_url_list = []
    if research_urls:
        research_url_list = [u.strip() for u in research_urls.split("\n")
                            if u.strip() and (u.strip().startswith("http://") or u.strip().startswith("https://"))]

    # ... create project with processing_status="pending" if has research ...

    # Enqueue research processing if there's work to do
    has_research = bool(research_file_paths or research_url_list)
    processing_status = "pending" if has_research else "ready"

    # [create project with processing_status=processing_status]

    if has_research:
        from boswell.server.jobs import enqueue_job
        await enqueue_job(
            db,
            job_type="process_project_research",
            payload={
                "project_id": str(project.id),
                "research_urls": research_url_list,
                "research_file_paths": research_file_paths,
                "topic": topic,
            },
        )
```

**Step 4: Run migration and tests**

Run: `PYTHONPATH=src alembic upgrade head`
Run: `PYTHONPATH=src pytest tests/ -v`

**Step 5: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/jobs.py src/boswell/server/models.py src/boswell/server/migrations/versions/
git commit -m "feat: move project research processing to async job queue"
```

---

### Task 5: Move bulk email sends to job queue

Currently `admin.py:1504-1514` sends emails sequentially in a loop during the request.

**Files:**
- Modify: `src/boswell/server/routes/admin.py:1494-1518` (bulk remind)
- Modify: `src/boswell/server/routes/admin.py:1057-1124` (bulk invite)

**Step 1: Replace inline email loop with job enqueue**

In the bulk remind handler, replace the email loop with:

```python
    from boswell.server.jobs import enqueue_job

    settings = get_settings()
    enqueue_count = 0
    for interview in interviews:
        if interview.email:
            magic_link = f"{settings.base_url}/i/{interview.magic_token}"
            await enqueue_job(
                db,
                job_type="send_invitation_email",
                payload={
                    "to": interview.email,
                    "guest_name": interview.name,
                    "interview_topic": project.topic,
                    "magic_link": magic_link,
                },
            )
            enqueue_count += 1

    await db.commit()
    return JSONResponse({"queued": enqueue_count, "total": len(interview_ids)})
```

**Step 2: Add send_invitation_email job handler**

In `jobs.py`, add:

```python
@register_job("send_invitation_email")
async def handle_send_invitation_email(payload: dict, db: AsyncSession) -> None:
    """Send an invitation email via the job queue."""
    from boswell.server.email import send_invitation_email

    success = await send_invitation_email(
        to=payload["to"],
        guest_name=payload["guest_name"],
        interview_topic=payload["interview_topic"],
        magic_link=payload["magic_link"],
    )
    if not success:
        raise RuntimeError(f"Failed to send invitation email to {payload['to']}")
```

**Step 3: Apply same pattern to bulk invite in CSV import**

**Step 4: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/jobs.py
git commit -m "feat: move bulk email sends to async job queue"
```

---

### Task 6: Make email sending non-blocking

`email.py:67` calls `resend.Emails.send()` synchronously from async code.

**Files:**
- Modify: `src/boswell/server/email.py:55-67`

**Step 1: Wrap sync call in asyncio.to_thread**

Replace line 67:

```python
# Old:
response = resend.Emails.send(params)

# New:
response = await asyncio.to_thread(resend.Emails.send, params)
```

Add `import asyncio` at the top of the file.

**Step 2: Run tests**

Run: `PYTHONPATH=src pytest tests/ -v`

**Step 3: Commit**

```bash
git add src/boswell/server/email.py
git commit -m "fix: wrap sync resend email call in asyncio.to_thread"
```

---

## Phase 3: Database and Query Performance (Week 2-3)

### Task 7: Add missing indexes for hot query paths

**Files:**
- Create: new Alembic migration

**Step 1: Generate migration**

The initial migration only has `idx_guests_magic_token` and `idx_guests_status`. We need:

```python
def upgrade():
    # Guest queries by project (interview_id is the FK to interviews/projects)
    op.create_index("idx_guests_interview_id", "guests", ["interview_id"])

    # Composite for filtering by project + status (dashboard counts)
    op.create_index("idx_guests_interview_id_status", "guests", ["interview_id", "status"])

    # Worker claims: started interviews with no claim and room_name
    op.create_index("idx_guests_status_claimed", "guests", ["status", "claimed_by"],
                     postgresql_where=sa.text("status = 'started' AND claimed_by IS NULL"))

    # Job queue: improve pending job polling
    op.create_index("idx_job_queue_status_created", "job_queue", ["status", "created_at"],
                     postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_index("idx_job_queue_status_created")
    op.drop_index("idx_guests_status_claimed")
    op.drop_index("idx_guests_interview_id_status")
    op.drop_index("idx_guests_interview_id")
```

**Step 2: Run migration**

Run: `PYTHONPATH=src alembic upgrade head`

**Step 3: Commit**

```bash
git add src/boswell/server/migrations/versions/
git commit -m "perf: add indexes for guest project lookups and worker claims"
```

---

### Task 8: Replace over-fetching with aggregate queries

**Files:**
- Modify: `src/boswell/server/routes/admin.py:84-108` (dashboard)
- Modify: `src/boswell/server/routes/admin.py:279-321` (project detail)

**Step 1: Fix dashboard query**

Replace `admin.py:91-99`. Instead of loading all interviews with `selectinload`, use a subquery for counts:

```python
from sqlalchemy import func, case

# Query projects with interview counts (no eager loading of interviews)
result = await db.execute(
    select(Project)
    .where(Project.team_id == user.team_id)
    .order_by(Project.created_at.desc())
)
projects = result.scalars().all()

# Get interview counts per project in one query
project_ids = [p.id for p in projects]
if project_ids:
    count_stmt = (
        select(
            Interview.project_id,
            func.count(Interview.id).label("total"),
            func.count(case((Interview.status == InterviewStatus.completed, 1))).label("completed"),
            func.count(case((Interview.status == InterviewStatus.invited, 1))).label("invited"),
            func.count(case((Interview.status == InterviewStatus.started, 1))).label("started"),
            func.count(case((Interview.status == InterviewStatus.in_progress, 1))).label("in_progress"),
        )
        .where(Interview.project_id.in_(project_ids))
        .group_by(Interview.project_id)
    )
    count_result = await db.execute(count_stmt)
    counts_by_project = {row.project_id: row for row in count_result}
else:
    counts_by_project = {}
```

Pass `counts_by_project` to the template context and update the dashboard template to use it.

**Step 2: Fix project detail query**

Replace `admin.py:288-296`. Don't load transcript/analysis for the list page:

```python
result = await db.execute(
    select(Project)
    .where(Project.id == project_id)
    .options(
        selectinload(Project.interviews),  # Load interviews but NOT their transcripts/analyses
    )
)
```

Only load transcript/analysis on the individual interview detail/transcript view pages (which already exist).

**Step 3: Update templates if needed**

Check `admin/dashboard.html` and `admin/project_detail.html` to ensure they work with the new data shape.

**Step 4: Run tests**

Run: `PYTHONPATH=src pytest tests/ -v`

**Step 5: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "perf: replace eager interview loading with aggregate count queries"
```

---

## Phase 4: Intelligence/Latency Quality (Week 3)

### Task 9: Gate debug audio diagnostics behind env flag

`pipeline.py:159,183` and `audio_diagnostics.py` add per-frame logging overhead.

**Files:**
- Modify: `src/boswell/voice/audio_diagnostics.py:38+`
- Modify: `src/boswell/voice/pipeline.py:159,183`

**Step 1: Add env flag guard**

In `audio_diagnostics.py`, wrap the diagnostic processor's logging:

```python
import os

AUDIO_DEBUG = os.environ.get("AUDIO_DEBUG", "").lower() in ("1", "true", "yes")
```

In the processor's frame handler, guard with:

```python
if not AUDIO_DEBUG:
    await self.push_frame(frame, direction)
    return
```

In `pipeline.py`, conditionally add the diagnostics processor:

```python
if os.environ.get("AUDIO_DEBUG", "").lower() in ("1", "true", "yes"):
    # Add audio diagnostics to pipeline
    ...
```

**Step 2: Commit**

```bash
git add src/boswell/voice/audio_diagnostics.py src/boswell/voice/pipeline.py
git commit -m "perf: gate audio diagnostics behind AUDIO_DEBUG env flag"
```

---

### Task 10: Add context budgeting for system prompts

`prompts.py:81-87` injects raw research text directly into the system prompt, which can be very large.

**Files:**
- Modify: `src/boswell/voice/prompts.py:51-241`

**Step 1: Add token budget helper**

Add to `prompts.py`:

```python
# Maximum characters for research context in system prompt
# ~4 chars per token, budget 2000 tokens for research
MAX_RESEARCH_CHARS = 8000
MAX_TRANSCRIPT_CHARS = 4000

def _truncate_context(text: str, max_chars: int) -> str:
    """Truncate text to fit within character budget."""
    if not text or len(text) <= max_chars:
        return text or ""
    # Truncate at sentence boundary if possible
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    if last_period > max_chars * 0.7:
        truncated = truncated[:last_period + 1]
    return truncated + "\n[... research truncated for context budget ...]"
```

**Step 2: Apply budget in build_system_prompt**

Replace line 81-87 in the research section:

```python
# Old:
if research_summary:
    parts.append(f"PROJECT RESEARCH:\n{research_summary}")

# New:
if research_summary:
    budgeted = _truncate_context(research_summary, MAX_RESEARCH_CHARS)
    parts.append(f"PROJECT RESEARCH:\n{budgeted}")
```

Apply same for returning transcript context in `build_returning_guest_prompt` (line 259).

**Step 3: Run tests**

Run: `PYTHONPATH=src pytest tests/ -v`

**Step 4: Commit**

```bash
git add src/boswell/voice/prompts.py
git commit -m "perf: add token budget for research/transcript context in prompts"
```

---

## Phase 5: Runtime and Frontend Performance (Week 4)

### Task 11: Remove runtime DDL from app startup

`main.py:24-41` runs an ALTER TABLE on every startup.

**Files:**
- Modify: `src/boswell/server/main.py:21-45`
- Create: new Alembic migration to formalize the topic column change

**Step 1: Create proper migration**

```python
"""Ensure topic column is TEXT type.

Revision ID: <auto>
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # This was previously done as runtime DDL in main.py lifespan
    op.alter_column("interviews", "topic", type_=sa.Text(), existing_type=sa.String(500))

def downgrade():
    op.alter_column("interviews", "topic", type_=sa.String(500), existing_type=sa.Text())
```

**Step 2: Remove runtime DDL from main.py**

Replace `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield
    await close_db()
```

**Step 3: Run migration and test**

Run: `PYTHONPATH=src alembic upgrade head`
Run: `PYTHONPATH=src pytest tests/ -v`

**Step 4: Commit**

```bash
git add src/boswell/server/main.py src/boswell/server/migrations/versions/
git commit -m "refactor: replace runtime DDL with proper Alembic migration"
```

---

### Task 12: Fix hardcoded Daily domain in guest.py

`guest.py:72` hardcodes `emirbot.daily.co` instead of using `settings.daily_domain`.

**Files:**
- Modify: `src/boswell/server/routes/guest.py:72`

**Step 1: Fix the hardcoded URL**

Replace line 72:

```python
# Old:
room_url = f"https://emirbot.daily.co/{room_name}"

# New:
settings = get_settings()
room_url = f"https://{settings.daily_domain}.daily.co/{room_name}"
```

**Step 2: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "fix: use settings.daily_domain instead of hardcoded emirbot"
```

---

### Task 13: Enable HTTP compression for static assets

**Files:**
- Modify: `src/boswell/server/main.py`

**Step 1: Add GZip middleware**

In `main.py`, after app creation:

```python
from starlette.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=500)
```

**Step 2: Add cache headers for static files**

The `StaticFiles` mount on line 66 doesn't set cache headers. Create a custom middleware or use StaticFiles' built-in `headers`:

```python
# Mount static files with cache headers
app.mount(
    "/static",
    StaticFiles(
        directory=str(_TEMPLATE_DIR.parent / "static"),
        headers={"Cache-Control": "public, max-age=86400"},
    ),
    name="static",
)
```

Note: Starlette's `StaticFiles` doesn't support a `headers` kwarg natively. Instead, add as response middleware or handle via reverse proxy. For now, GZip middleware is the main win.

**Step 3: Commit**

```bash
git add src/boswell/server/main.py
git commit -m "perf: enable gzip compression middleware"
```

---

## Phase 6: Test Hardening (Parallel)

### Task 14: Fix failing tests and establish CI baseline

**Files:**
- Modify: files in `tests/` as needed
- Potentially modify: `pyproject.toml` test configuration

**Step 1: Run the existing test suite and capture failures**

Run: `PYTHONPATH=src pytest tests/ -v 2>&1 | head -100`

**Step 2: Fix each failure**

Address each test failure individually. Common issues:
- Import paths changed (legacy CLI vs server models)
- Missing test fixtures or mock setup
- Stale test data assumptions

**Step 3: Verify all pass**

Run: `PYTHONPATH=src pytest tests/ -v`
Expected: All green

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: fix failing tests and establish green CI baseline"
```

---

### Task 15: Add integration tests for worker claim semantics

**Files:**
- Create: `tests/test_worker_integration.py`

**Step 1: Write integration tests**

```python
"""Integration tests for worker claim and job queue semantics.

These tests require a running PostgreSQL database.
Skip if DATABASE_URL is not set.
"""

import asyncio
import os
from uuid import uuid4

import pytest

# Skip all tests if no database
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set"
)


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_wins():
    """Two workers claiming simultaneously should result in exactly one claim."""
    # Create a started interview
    # Run two claim_next_interview calls concurrently
    # Assert exactly one returns the interview
    pass


@pytest.mark.asyncio
async def test_failed_interview_not_reclaimed_before_backoff():
    """A failed interview should not be claimable before its backoff period."""
    pass


@pytest.mark.asyncio
async def test_jobs_worker_processes_analysis_after_completion():
    """generate_analysis job should be processed after interview completion."""
    pass
```

**Step 2: Commit**

```bash
git add tests/test_worker_integration.py
git commit -m "test: add integration test skeletons for worker claim semantics"
```

---

## PR Sequence (Recommended)

| PR | Tasks | Title |
|----|-------|-------|
| 1  | 1     | `feat: jobs worker process + service wiring` |
| 2  | 2, 3  | `feat: interview claim/lease + retry backoff` |
| 3  | 4, 5, 6 | `feat: async job queue for ingestion + email` |
| 4  | 7, 8  | `perf: index migration + query optimization` |
| 5  | 9, 10 | `perf: audio debug gating + prompt context budget` |
| 6  | 11, 12, 13 | `refactor: runtime startup cleanup + compression` |
| 7  | 14, 15 | `test: CI hardening + integration test skeletons` |

---

## Target Outcomes (Verification Criteria)

After all PRs merge:

1. **Project creation p95 < 2s** for non-trivial uploads — research processing happens async
2. **Interview start to first bot question p95 < 3s** — prompt is token-budgeted
3. **Duplicate interview runs = 0** under multi-worker — DB-backed FOR UPDATE SKIP LOCKED
4. **Analysis completion SLA < 2 min** after interview end — dedicated jobs worker processes queue
5. **Dashboard/project detail p95 < 500ms** for large projects — aggregate counts, no transcript loading
