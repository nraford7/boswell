"""Interview model and lifecycle management for Boswell.

Handles interview creation, state tracking, and persistence.
"""

import secrets
import string
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class InterviewStatus(str, Enum):
    """Possible states of an interview."""

    PENDING = "pending"  # Interview created, waiting for guest
    WAITING = "waiting"  # Bot in meeting, waiting for guest to join
    IN_PROGRESS = "in_progress"  # Interview actively happening
    PROCESSING = "processing"  # Interview complete, generating outputs
    COMPLETE = "complete"  # All outputs ready
    NO_SHOW = "no_show"  # Guest didn't join within timeout
    ERROR = "error"  # Something went wrong


class Interview(BaseModel):
    """Model representing a single interview session."""

    id: str = Field(..., description="Unique interview identifier")
    topic: str = Field(..., description="Interview topic/subject")
    status: InterviewStatus = Field(default=InterviewStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    guest_name: str | None = Field(default=None)
    meeting_link: str | None = Field(default=None)
    research_docs: list[str] = Field(default_factory=list)
    research_urls: list[str] = Field(default_factory=list)
    generated_questions: list[str] = Field(default_factory=list)
    target_time_minutes: int = Field(default=30)
    max_time_minutes: int = Field(default=45)
    output_dir: str | None = Field(default=None)


def generate_interview_id() -> str:
    """Generate a unique interview ID like 'int_7x8f2k'.

    Uses cryptographically secure random characters for the suffix.

    Returns:
        A unique interview ID string.
    """
    # Use lowercase letters and digits for the suffix
    chars = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"int_{suffix}"


def get_interviews_dir() -> Path:
    """Get the interviews directory (~/.boswell/interviews/).

    Creates the directory if it doesn't exist.

    Returns:
        Path to the interviews directory.
    """
    interviews_dir = Path.home() / ".boswell" / "interviews"
    interviews_dir.mkdir(parents=True, exist_ok=True)
    return interviews_dir


def get_interview_path(interview_id: str) -> Path:
    """Get the path to an interview JSON file.

    Args:
        interview_id: The interview ID.

    Returns:
        Path to the interview JSON file.
    """
    return get_interviews_dir() / f"{interview_id}.json"


def create_interview(
    topic: str,
    docs: list[str] | None = None,
    urls: list[str] | None = None,
) -> Interview:
    """Create a new interview session.

    Creates the interview with a unique ID and persists it to disk.

    Args:
        topic: The interview topic.
        docs: List of paths to research documents.
        urls: List of URLs to scrape for research.

    Returns:
        A new Interview instance.
    """
    interview = Interview(
        id=generate_interview_id(),
        topic=topic,
        research_docs=docs or [],
        research_urls=urls or [],
    )
    save_interview(interview)
    return interview


def load_interview(interview_id: str) -> Interview | None:
    """Load an existing interview by ID.

    Args:
        interview_id: The interview ID to load.

    Returns:
        The Interview if found, None otherwise.
    """
    interview_path = get_interview_path(interview_id)
    if not interview_path.exists():
        return None
    return Interview.model_validate_json(interview_path.read_text())


def save_interview(interview: Interview) -> None:
    """Persist an interview to storage.

    Creates the interviews directory if it doesn't exist.

    Args:
        interview: The Interview to save.
    """
    interview_path = get_interview_path(interview.id)
    interview_path.parent.mkdir(parents=True, exist_ok=True)
    interview_path.write_text(interview.model_dump_json(indent=2))


def list_interviews() -> list[Interview]:
    """List all saved interviews.

    Returns:
        List of all Interview objects, sorted by creation date (newest first).
    """
    interviews_dir = get_interviews_dir()
    interviews = []

    for interview_file in interviews_dir.glob("int_*.json"):
        try:
            interview = Interview.model_validate_json(interview_file.read_text())
            interviews.append(interview)
        except Exception:
            # Skip invalid interview files
            continue

    # Sort by creation date, newest first
    interviews.sort(key=lambda i: i.created_at, reverse=True)
    return interviews


def update_interview_status(
    interview_id: str, status: InterviewStatus
) -> Interview | None:
    """Update the status of an interview and save it.

    Args:
        interview_id: The interview ID to update.
        status: The new status.

    Returns:
        The updated Interview, or None if not found.
    """
    interview = load_interview(interview_id)
    if interview is None:
        return None

    interview.status = status

    # Set timestamps based on status transitions
    now = datetime.now(UTC)
    if status == InterviewStatus.IN_PROGRESS and interview.started_at is None:
        interview.started_at = now
    elif status in (
        InterviewStatus.COMPLETE,
        InterviewStatus.NO_SHOW,
        InterviewStatus.ERROR,
    ):
        if interview.completed_at is None:
            interview.completed_at = now

    save_interview(interview)
    return interview
