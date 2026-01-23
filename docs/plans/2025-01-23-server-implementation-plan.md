# Boswell Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Boswell from a CLI tool into a web application with admin dashboard, guest self-service interviews, and bulk import capabilities.

**Architecture:** Two-container deployment - FastAPI web app (admin dashboard, guest pages, background jobs) and voice worker (Pipecat pipelines). PostgreSQL with JSONB for data. HTMX for interactive admin UI without a JS framework.

**Tech Stack:** FastAPI, HTMX, Jinja2, PostgreSQL, SQLAlchemy, Alembic, Pipecat, Resend

---

## Phase 1: Foundation (Database + Core Models)

### Task 1: Add Server Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add new dependencies to pyproject.toml**

Add a `[project.optional-dependencies]` section for server:

```toml
[project.optional-dependencies]
voice = [
    "pipecat-ai[daily,deepgram,elevenlabs,silero]>=0.0.100",
]
server = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.25",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "jinja2>=3.1.3",
    "python-multipart>=0.0.6",
    "resend>=0.8.0",
    "itsdangerous>=2.1.2",
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.26.0",
    "ruff>=0.1.0",
]
```

**Step 2: Install dependencies**

Run: `pip install -e ".[server,voice,dev]"`
Expected: Successfully installed packages

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add server dependencies (FastAPI, SQLAlchemy, etc.)"
```

---

### Task 2: Create Database Models

**Files:**
- Create: `src/boswell/server/__init__.py`
- Create: `src/boswell/server/models.py`

**Step 1: Create server package**

```python
# src/boswell/server/__init__.py
"""Boswell server - web application for interview management."""
```

**Step 2: Create SQLAlchemy models**

```python
# src/boswell/server/models.py
"""Database models for Boswell server."""

import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class GuestStatus(str, Enum):
    """Status of a guest's interview."""
    INVITED = "invited"
    STARTED = "started"
    COMPLETED = "completed"
    EXPIRED = "expired"


class JobStatus(str, Enum):
    """Status of a background job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Team(Base):
    """A team that manages interviews."""
    __tablename__ = "team"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    users: Mapped[list["User"]] = relationship(back_populates="team")
    templates: Mapped[list["InterviewTemplate"]] = relationship(back_populates="team")
    interviews: Mapped[list["Interview"]] = relationship(back_populates="team")


class User(Base):
    """An admin user who can manage interviews."""
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    team_id: Mapped[UUID] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    team: Mapped["Team"] = relationship(back_populates="users")


class InterviewTemplate(Base):
    """A template for a type of interview."""
    __tablename__ = "interview_template"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    team_id: Mapped[UUID] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_modifier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    team: Mapped["Team"] = relationship(back_populates="templates")
    interviews: Mapped[list["Interview"]] = relationship(back_populates="template")


class Interview(Base):
    """An interview on a specific topic."""
    __tablename__ = "interview"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    team_id: Mapped[UUID] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"))
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interview_template.id"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(500))
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    team: Mapped["Team"] = relationship(back_populates="interviews")
    template: Mapped[Optional["InterviewTemplate"]] = relationship(
        back_populates="interviews"
    )
    guests: Mapped[list["Guest"]] = relationship(back_populates="interview")


def generate_magic_token() -> str:
    """Generate a secure magic token for guest access."""
    return secrets.token_urlsafe(48)


class Guest(Base):
    """A guest invited to take an interview."""
    __tablename__ = "guest"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    interview_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    magic_token: Mapped[str] = mapped_column(
        String(64), unique=True, default=generate_magic_token
    )
    status: Mapped[str] = mapped_column(String(20), default=GuestStatus.INVITED.value)
    room_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    room_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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

    interview: Mapped["Interview"] = relationship(back_populates="guests")
    transcript: Mapped[Optional["Transcript"]] = relationship(back_populates="guest")
    analysis: Mapped[Optional["Analysis"]] = relationship(back_populates="guest")


class Transcript(Base):
    """Transcript of a completed interview."""
    __tablename__ = "transcript"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    guest_id: Mapped[UUID] = mapped_column(
        ForeignKey("guest.id", ondelete="CASCADE"), unique=True
    )
    entries: Mapped[dict] = mapped_column(JSONB)
    conversation_context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    guest: Mapped["Guest"] = relationship(back_populates="transcript")


class Analysis(Base):
    """AI-generated analysis of an interview."""
    __tablename__ = "analysis"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    guest_id: Mapped[UUID] = mapped_column(
        ForeignKey("guest.id", ondelete="CASCADE"), unique=True
    )
    insights: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    guest: Mapped["Guest"] = relationship(back_populates="analysis")


class JobQueue(Base):
    """Background job queue."""
    __tablename__ = "job_queue"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    job_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

**Step 3: Verify models import correctly**

Run: `python3 -c "from boswell.server.models import Team, User, Interview, Guest, Transcript; print('Models OK')"`
Expected: `Models OK`

**Step 4: Commit**

```bash
git add src/boswell/server/
git commit -m "feat(server): add SQLAlchemy database models"
```

---

### Task 3: Set Up Database Connection

**Files:**
- Create: `src/boswell/server/database.py`

**Step 1: Create database connection module**

```python
# src/boswell/server/database.py
"""Database connection and session management."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from boswell.server.models import Base


def get_database_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable not set")
    # Handle Railway's postgres:// vs postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# Engine and session factory (initialized on first use)
_engine = None
_session_factory = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_database_url(),
            echo=os.environ.get("SQL_ECHO", "").lower() == "true",
        )
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for getting a database session outside of FastAPI."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize the database (create tables)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
```

**Step 2: Verify database module imports**

Run: `python3 -c "from boswell.server.database import get_session, init_db; print('Database OK')"`
Expected: `Database OK`

**Step 3: Commit**

```bash
git add src/boswell/server/database.py
git commit -m "feat(server): add async database connection module"
```

---

### Task 4: Set Up Alembic Migrations

**Files:**
- Create: `alembic.ini`
- Create: `src/boswell/server/migrations/env.py`
- Create: `src/boswell/server/migrations/script.py.mako`
- Create: `src/boswell/server/migrations/versions/.gitkeep`

**Step 1: Create alembic.ini**

```ini
# alembic.ini
[alembic]
script_location = src/boswell/server/migrations
prepend_sys_path = .
version_path_separator = os

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Step 2: Create migrations directory structure**

```bash
mkdir -p src/boswell/server/migrations/versions
touch src/boswell/server/migrations/versions/.gitkeep
```

**Step 3: Create env.py**

```python
# src/boswell/server/migrations/env.py
"""Alembic migration environment."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from boswell.server.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4: Create script.py.mako**

```mako
# src/boswell/server/migrations/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

**Step 5: Commit**

```bash
git add alembic.ini src/boswell/server/migrations/
git commit -m "feat(server): set up Alembic migrations"
```

---

### Task 5: Create Initial Migration

**Files:**
- Create: `src/boswell/server/migrations/versions/001_initial.py`

**Step 1: Create initial migration manually**

```python
# src/boswell/server/migrations/versions/001_initial.py
"""Initial database schema.

Revision ID: 001
Revises:
Create Date: 2025-01-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Team
    op.create_table(
        "team",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # User
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("team.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Interview Template
    op.create_table(
        "interview_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("team.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("prompt_modifier", sa.Text, nullable=True),
        sa.Column("default_minutes", sa.Integer, default=30),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Interview
    op.create_table(
        "interview",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("team.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_template.id"),
            nullable=True,
        ),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("questions", postgresql.JSONB, nullable=True),
        sa.Column("research_summary", sa.Text, nullable=True),
        sa.Column("target_minutes", sa.Integer, default=30),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Guest
    op.create_table(
        "guest",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "interview_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("bio_url", sa.Text, nullable=True),
        sa.Column("magic_token", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(20), default="invited"),
        sa.Column("room_name", sa.String(255), nullable=True),
        sa.Column("room_token", sa.Text, nullable=True),
        sa.Column("claimed_by", sa.String(255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_guest_magic_token", "guest", ["magic_token"])
    op.create_index("idx_guest_status", "guest", ["status"])

    # Transcript
    op.create_table(
        "transcript",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "guest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guest.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("entries", postgresql.JSONB, nullable=False),
        sa.Column("conversation_context", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Analysis
    op.create_table(
        "analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "guest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guest.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("insights", postgresql.JSONB, nullable=True),
        sa.Column("summary_md", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Job Queue
    op.create_table(
        "job_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("attempts", sa.Integer, default=0),
        sa.Column("max_attempts", sa.Integer, default=3),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_job_queue_pending",
        "job_queue",
        ["status", "run_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("job_queue")
    op.drop_table("analysis")
    op.drop_table("transcript")
    op.drop_table("guest")
    op.drop_table("interview")
    op.drop_table("interview_template")
    op.drop_table("user")
    op.drop_table("team")
```

**Step 2: Commit**

```bash
git add src/boswell/server/migrations/versions/001_initial.py
git commit -m "feat(server): add initial database migration"
```

---

## Phase 2: FastAPI Application Core

### Task 6: Create FastAPI Application

**Files:**
- Create: `src/boswell/server/main.py`
- Create: `src/boswell/server/config.py`

**Step 1: Create config module**

```python
# src/boswell/server/config.py
"""Server configuration."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    """Application settings from environment variables."""

    # Database
    database_url: str

    # External services
    daily_api_key: str
    claude_api_key: str
    deepgram_api_key: str
    elevenlabs_api_key: str
    resend_api_key: str

    # App config
    secret_key: str
    base_url: str
    admin_emails: list[str]

    # Defaults
    session_expire_days: int = 7
    magic_link_expire_days: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        admin_emails_str = os.environ.get("ADMIN_EMAILS", "")
        admin_emails = [e.strip() for e in admin_emails_str.split(",") if e.strip()]

        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            daily_api_key=os.environ.get("DAILY_API_KEY", ""),
            claude_api_key=os.environ.get("CLAUDE_API_KEY", ""),
            deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
            elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
            base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
            admin_emails=admin_emails,
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings.from_env()
```

**Step 2: Create main FastAPI app**

```python
# src/boswell/server/main.py
"""FastAPI application for Boswell server."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from boswell.server.config import get_settings
from boswell.server.database import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()


app = FastAPI(
    title="Boswell",
    description="AI Research Interviewer",
    version="0.1.0",
    lifespan=lifespan,
)

# Templates
templates = Jinja2Templates(directory="src/boswell/server/templates")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root redirect to admin or guest info."""
    return {"message": "Boswell API", "docs": "/docs"}
```

**Step 3: Verify app runs**

Run: `python3 -c "from boswell.server.main import app; print('App OK')"`
Expected: `App OK`

**Step 4: Commit**

```bash
git add src/boswell/server/config.py src/boswell/server/main.py
git commit -m "feat(server): create FastAPI application with config"
```

---

### Task 7: Create Templates Directory Structure

**Files:**
- Create: `src/boswell/server/templates/base.html`
- Create: `src/boswell/server/templates/admin/login.html`
- Create: `src/boswell/server/templates/guest/landing.html`
- Create: `src/boswell/server/static/.gitkeep`

**Step 1: Create directory structure**

```bash
mkdir -p src/boswell/server/templates/admin
mkdir -p src/boswell/server/templates/guest
mkdir -p src/boswell/server/static
touch src/boswell/server/static/.gitkeep
```

**Step 2: Create base template**

```html
<!-- src/boswell/server/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Boswell{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        :root {
            --bg: #fafafa;
            --fg: #1a1a1a;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --border: #e5e7eb;
            --muted: #6b7280;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--fg);
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .card {
            background: white;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 2rem;
            margin-bottom: 1rem;
        }
        h1, h2, h3 { margin-bottom: 1rem; }
        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            cursor: pointer;
            text-decoration: none;
        }
        .btn:hover { background: var(--primary-hover); }
        .btn-outline {
            background: white;
            color: var(--primary);
            border: 1px solid var(--primary);
        }
        .btn-outline:hover { background: var(--primary); color: white; }
        input, select, textarea {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 1rem;
            margin-bottom: 1rem;
        }
        label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
        .text-muted { color: var(--muted); }
        .text-center { text-align: center; }
        .mb-2 { margin-bottom: 1rem; }
        .mb-4 { margin-bottom: 2rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
        th { font-weight: 600; }
        .status-invited { color: #f59e0b; }
        .status-started { color: #3b82f6; }
        .status-completed { color: #10b981; }
        .status-expired { color: #ef4444; }
        .nav { background: white; border-bottom: 1px solid var(--border); padding: 1rem 2rem; }
        .nav-content { max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
        .nav-brand { font-weight: 600; font-size: 1.25rem; text-decoration: none; color: var(--fg); }
        .nav-links a { margin-left: 1.5rem; text-decoration: none; color: var(--muted); }
        .nav-links a:hover { color: var(--fg); }
    </style>
    {% block head %}{% endblock %}
</head>
<body>
    {% block body %}{% endblock %}
</body>
</html>
```

**Step 3: Create admin login template**

```html
<!-- src/boswell/server/templates/admin/login.html -->
{% extends "base.html" %}

{% block title %}Login - Boswell{% endblock %}

{% block body %}
<div class="container" style="max-width: 400px; margin-top: 10vh;">
    <div class="card text-center">
        <h1 class="mb-4">Boswell</h1>
        <p class="text-muted mb-4">Enter your email to receive a login link.</p>

        <form method="post" action="/admin/login">
            <input type="email" name="email" placeholder="you@example.com" required>
            <button type="submit" class="btn" style="width: 100%;">Send Login Link</button>
        </form>

        {% if message %}
        <p class="text-muted" style="margin-top: 1rem;">{{ message }}</p>
        {% endif %}
    </div>
</div>
{% endblock %}
```

**Step 4: Create guest landing template**

```html
<!-- src/boswell/server/templates/guest/landing.html -->
{% extends "base.html" %}

{% block title %}Interview: {{ interview.topic }} - Boswell{% endblock %}

{% block body %}
<div class="container" style="max-width: 600px; margin-top: 5vh;">
    <div class="card">
        <h1 class="mb-2">{{ interview.topic }}</h1>
        <p class="text-muted mb-4">Duration: ~{{ interview.target_minutes }} minutes</p>

        <div class="mb-4">
            <h3>Before you begin:</h3>
            <ul style="margin-left: 1.5rem; margin-top: 0.5rem;">
                <li>This interview is <strong>anonymous by default</strong> - your name won't be associated unless you choose.</li>
                <li>You'll receive a <strong>full transcript by email</strong> right after.</li>
                <li>Say <strong>"forget that"</strong> anytime to remove something from the record.</li>
                <li>You can pause, stop, or ask to repeat any question.</li>
            </ul>
        </div>

        <form method="post" action="/i/{{ guest.magic_token }}/start">
            <button type="submit" class="btn" style="width: 100%; font-size: 1.25rem; padding: 1rem;">
                Start Interview
            </button>
        </form>
    </div>
</div>
{% endblock %}
```

**Step 5: Commit**

```bash
git add src/boswell/server/templates/ src/boswell/server/static/
git commit -m "feat(server): add base templates and directory structure"
```

---

## Phase 3: Admin Authentication

### Task 8: Create Auth Routes

**Files:**
- Create: `src/boswell/server/routes/__init__.py`
- Create: `src/boswell/server/routes/auth.py`

**Step 1: Create routes package**

```python
# src/boswell/server/routes/__init__.py
"""Route modules for Boswell server."""
```

**Step 2: Create auth routes**

```python
# src/boswell/server/routes/auth.py
"""Authentication routes."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boswell.server.config import get_settings
from boswell.server.database import get_session
from boswell.server.models import Team, User
from boswell.server.templates import templates

router = APIRouter()


def get_serializer() -> URLSafeTimedSerializer:
    """Get token serializer."""
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key)


def create_login_token(email: str) -> str:
    """Create a login token for the given email."""
    serializer = get_serializer()
    return serializer.dumps(email, salt="login")


def verify_login_token(token: str, max_age: int = 3600) -> str | None:
    """Verify a login token and return the email if valid."""
    serializer = get_serializer()
    try:
        return serializer.loads(token, salt="login", max_age=max_age)
    except Exception:
        return None


def create_session_token(user_id: str) -> str:
    """Create a session token for the given user."""
    serializer = get_serializer()
    return serializer.dumps(user_id, salt="session")


def verify_session_token(token: str, max_age: int = 604800) -> str | None:
    """Verify a session token and return the user ID if valid."""
    serializer = get_serializer()
    try:
        return serializer.loads(token, salt="session", max_age=max_age)
    except Exception:
        return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User | None:
    """Get the current logged-in user from session cookie."""
    session_token = request.cookies.get("session")
    if not session_token:
        return None

    user_id = verify_session_token(session_token)
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, message: str = ""):
    """Show login page."""
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "message": message},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_session),
):
    """Handle login form submission."""
    settings = get_settings()

    # Check if email is allowed
    if email.lower() not in [e.lower() for e in settings.admin_emails]:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "message": "Email not authorized."},
        )

    # Create or get user
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user:
        # Create team and user for first-time login
        team = Team(name="Default Team")
        db.add(team)
        await db.flush()

        user = User(email=email.lower(), team_id=team.id)
        db.add(user)
        await db.flush()

    # Generate login token
    token = create_login_token(email.lower())
    login_url = f"{settings.base_url}/admin/verify?token={token}"

    # TODO: Send email via Resend
    # For now, just show the link (dev mode)
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "message": f"Check your email! (Dev: {login_url})"},
    )


@router.get("/verify")
async def verify_login(
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Verify login token and create session."""
    email = verify_login_token(token)
    if not email:
        return RedirectResponse("/admin/login?message=Invalid+or+expired+link")

    # Get user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        return RedirectResponse("/admin/login?message=User+not+found")

    # Create session
    session_token = create_session_token(str(user.id))
    response = RedirectResponse("/admin/", status_code=303)
    response.set_cookie(
        "session",
        session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=604800,  # 7 days
    )
    return response


@router.post("/logout")
async def logout():
    """Log out and clear session."""
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("session")
    return response
```

**Step 3: Commit**

```bash
git add src/boswell/server/routes/
git commit -m "feat(server): add authentication routes with magic link"
```

---

## Phase 4-8: Remaining Tasks

Due to the size of this plan, the remaining phases are summarized. Each would follow the same detailed structure:

### Phase 4: Admin Dashboard
- Task 9: Create dashboard home page (list interviews)
- Task 10: Create interview detail page
- Task 11: Create new interview form
- Task 12: Create template management pages

### Phase 5: Guest Experience
- Task 13: Create guest landing page route
- Task 14: Create start interview endpoint (creates Daily room)
- Task 15: Create rejoin logic
- Task 16: Create thank you page

### Phase 6: Bulk Import
- Task 17: Create CSV upload endpoint
- Task 18: Create bulk interview creation logic
- Task 19: Create progress tracking

### Phase 7: Background Jobs
- Task 20: Create job queue processor
- Task 21: Implement question generation job
- Task 22: Implement email sending jobs
- Task 23: Implement analysis generation job

### Phase 8: Voice Worker
- Task 24: Create voice worker entry point
- Task 25: Integrate existing Pipecat pipeline
- Task 26: Add database save on completion

### Phase 9: Deployment
- Task 27: Create Dockerfiles
- Task 28: Create Railway configuration
- Task 29: Set up production environment

---

## Execution Order

1. **Phase 1** (Tasks 1-5): Foundation - can run locally with Postgres
2. **Phase 2** (Tasks 6-7): FastAPI core - can start server
3. **Phase 3** (Task 8): Auth - can log in
4. **Phase 4** (Tasks 9-12): Admin dashboard - can create interviews
5. **Phase 5** (Tasks 13-16): Guest experience - can take interviews
6. **Phase 6** (Tasks 17-19): Bulk import - can import CSV
7. **Phase 7** (Tasks 20-23): Background jobs - async processing
8. **Phase 8** (Tasks 24-26): Voice worker - interviews work
9. **Phase 9** (Tasks 27-29): Deploy to Railway

Each phase builds on the previous. Test locally before moving to the next phase.
