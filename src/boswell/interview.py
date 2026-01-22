"""Interview model and lifecycle management for Boswell.

Handles interview creation, state tracking, and persistence.
"""

from datetime import datetime, timezone
from enum import Enum

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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


def create_interview(
    topic: str,
    docs: list[str] | None = None,
    urls: list[str] | None = None,
) -> Interview:
    """Create a new interview session.

    Args:
        topic: The interview topic
        docs: List of paths to research documents
        urls: List of URLs to scrape for research

    Returns:
        A new Interview instance
    """
    # TODO: Implement interview creation
    raise NotImplementedError("Interview creation not yet implemented")


def load_interview(interview_id: str) -> Interview | None:
    """Load an existing interview by ID.

    Args:
        interview_id: The interview ID to load

    Returns:
        The Interview if found, None otherwise
    """
    # TODO: Implement interview loading
    raise NotImplementedError("Interview loading not yet implemented")


def save_interview(interview: Interview) -> None:
    """Persist an interview to storage.

    Args:
        interview: The Interview to save
    """
    # TODO: Implement interview persistence
    raise NotImplementedError("Interview saving not yet implemented")
