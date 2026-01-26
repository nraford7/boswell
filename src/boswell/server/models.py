"""SQLAlchemy database models for Boswell server."""

import enum
import secrets
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class InterviewStatus(str, enum.Enum):
    """Status of an interview."""

    invited = "invited"
    started = "started"
    completed = "completed"
    expired = "expired"


class InterviewMode(str, enum.Enum):
    """Mode for returning guest interviews."""

    new = "new"  # First-time interview
    resume = "resume"  # Continue where left off
    add_detail = "add_detail"  # Review and refine previous answers
    fresh_start = "fresh_start"  # Delete old transcript, start over


class InterviewAngle(str, enum.Enum):
    """Style/angle for conducting an interview."""

    exploratory = "exploratory"
    interrogative = "interrogative"
    imaginative = "imaginative"
    documentary = "documentary"
    coaching = "coaching"
    custom = "custom"


class JobStatus(str, enum.Enum):
    """Status of a background job."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


def generate_magic_token() -> str:
    """Generate a secure magic token for guest access."""
    return secrets.token_urlsafe(48)


class Team(Base):
    """A team that owns projects, templates, and users."""

    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="team", cascade="all, delete-orphan"
    )
    templates: Mapped[list["InterviewTemplate"]] = relationship(
        "InterviewTemplate", back_populates="team", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="team", cascade="all, delete-orphan"
    )


class User(Base):
    """A user who can manage interviews within a team."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="users")


class InterviewTemplate(Base):
    """A reusable interview template with configuration."""

    __tablename__ = "interview_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_modifier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    angle: Mapped[Optional[InterviewAngle]] = mapped_column(
        Enum(InterviewAngle, name="interviewangle"), nullable=True
    )
    angle_secondary: Mapped[Optional[InterviewAngle]] = mapped_column(
        Enum(InterviewAngle, name="interviewangle", create_constraint=False), nullable=True
    )
    angle_custom: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="templates")
    interviews: Mapped[list["Interview"]] = relationship(
        "Interview", back_populates="template"
    )


class Project(Base):
    """A project containing one or more interviews."""

    __tablename__ = "interviews"  # Keep table name to avoid migration

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    target_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Public link token for generic interview links
    public_link_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    # Public description shown to guests on landing page (separate from topic which guides AI)
    public_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Short intro prompt for how Boswell greets guests (e.g., "your experience with our product")
    intro_prompt: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Template to use for public link interviews (content + style)
    public_template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="projects")
    interviews: Mapped[list["Interview"]] = relationship(
        "Interview", back_populates="project", cascade="all, delete-orphan"
    )
    public_template: Mapped[Optional["InterviewTemplate"]] = relationship(
        "InterviewTemplate", foreign_keys=[public_template_id]
    )


class Interview(Base):
    """A 1:1 interview with a specific person."""

    __tablename__ = "guests"  # Keep table name to avoid migration

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        "interview_id",  # Keep column name to avoid migration
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bio_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    context_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    angle: Mapped[Optional[InterviewAngle]] = mapped_column(
        Enum(InterviewAngle, name="interviewangle", create_constraint=False), nullable=True
    )
    angle_secondary: Mapped[Optional[InterviewAngle]] = mapped_column(
        Enum(InterviewAngle, name="interviewangle", create_constraint=False), nullable=True
    )
    angle_custom: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    magic_token: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, default=generate_magic_token
    )
    status: Mapped[InterviewStatus] = mapped_column(
        Enum(InterviewStatus, name="gueststatus"), default=InterviewStatus.invited, nullable=False
    )
    room_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    room_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    interview_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="interviews")
    template: Mapped[Optional["InterviewTemplate"]] = relationship(
        "InterviewTemplate", back_populates="interviews"
    )
    transcript: Mapped[Optional["Transcript"]] = relationship(
        "Transcript", back_populates="interview", uselist=False, cascade="all, delete-orphan"
    )
    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis", back_populates="interview", uselist=False, cascade="all, delete-orphan"
    )


class Transcript(Base):
    """Transcript of an interview conversation."""

    __tablename__ = "transcripts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    interview_id: Mapped[UUID] = mapped_column(
        "guest_id",  # Keep column name to avoid migration
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    entries: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    conversation_context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    interview: Mapped["Interview"] = relationship("Interview", back_populates="transcript")


class Analysis(Base):
    """AI-generated analysis of an interview transcript."""

    __tablename__ = "analyses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    interview_id: Mapped[UUID] = mapped_column(
        "guest_id",  # Keep column name to avoid migration
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    insights: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    interview: Mapped["Interview"] = relationship("Interview", back_populates="analysis")


class JobQueue(Base):
    """Background job queue for async processing."""

    __tablename__ = "job_queue"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.pending, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
