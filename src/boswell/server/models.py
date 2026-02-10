"""SQLAlchemy database models for Boswell server."""

import enum
import hashlib
import secrets
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
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


class ProjectRole(str, enum.Enum):
    """Role for project sharing. Ordered from least to most privilege."""
    view = "view"
    operate = "operate"
    collaborate = "collaborate"
    owner = "owner"

    @property
    def level(self) -> int:
        return _ROLE_LEVELS[self]

    def __ge__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level >= other.level

    def __gt__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level > other.level

    def __le__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level <= other.level

    def __lt__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level < other.level


_ROLE_LEVELS = {
    ProjectRole.view: 0,
    ProjectRole.operate: 1,
    ProjectRole.collaborate: 2,
    ProjectRole.owner: 3,
}


def generate_magic_token() -> str:
    """Generate a secure magic token for guest access."""
    return secrets.token_urlsafe(48)


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class ProjectShare(Base):
    """Per-project access grant. Authorization source of truth."""
    __tablename__ = "project_shares"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="projectrole"), nullable=False
    )
    granted_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="shares")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    granter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[granted_by])

    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_user"),
        sa.Index("ix_project_shares_user_project", "user_id", "project_id"),
        sa.Index("ix_project_shares_project_role", "project_id", "role"),
    )


class AccountInvite(Base):
    """Invite link for sharing a project and optionally creating an account."""
    __tablename__ = "account_invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[Optional[ProjectRole]] = mapped_column(
        Enum(ProjectRole, name="projectrole", create_constraint=False), nullable=True
    )
    claimed_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    inviter: Mapped["User"] = relationship("User", foreign_keys=[invited_by])
    project: Mapped[Optional["Project"]] = relationship("Project")
    claimed_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[claimed_by_user_id])

    __table_args__ = (
        sa.CheckConstraint(
            "(project_id IS NULL AND role IS NULL) OR (project_id IS NOT NULL AND role IS NOT NULL)",
            name="ck_invite_project_role_together",
        ),
        sa.Index("ix_invite_email_status", "email", "claimed_at", "revoked_at", "expires_at"),
        sa.Index("ix_invite_project_status", "project_id", "claimed_at", "revoked_at"),
    )


class User(Base):
    """A user who can manage interviews within a team."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InterviewTemplate(Base):
    """A reusable interview template with configuration."""

    __tablename__ = "interview_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
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
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    interviews: Mapped[list["Interview"]] = relationship(
        "Interview", back_populates="template"
    )


class Project(Base):
    """A project containing one or more interviews."""

    __tablename__ = "interviews"  # Keep table name to avoid migration

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
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

    processing_status: Mapped[str] = mapped_column(
        String(20), default="ready", server_default="ready", nullable=False
    )

    # Public link token for generic interview links
    public_link_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    # Public description shown to guests on landing page (separate from topic which guides AI)
    public_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Short intro prompt for how Boswell greets guests (e.g., "your experience with our product")
    intro_prompt: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Template to use for all interviews in this project (content + style)
    template_id: Mapped[Optional[UUID]] = mapped_column(
        "public_template_id",  # Keep existing column name to avoid migration
        ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    interviews: Mapped[list["Interview"]] = relationship(
        "Interview", back_populates="project", cascade="all, delete-orphan"
    )
    template: Mapped[Optional["InterviewTemplate"]] = relationship(
        "InterviewTemplate", foreign_keys=[template_id]
    )
    shares: Mapped[list["ProjectShare"]] = relationship(
        "ProjectShare", back_populates="project", cascade="all, delete-orphan"
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
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    suggested_questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
