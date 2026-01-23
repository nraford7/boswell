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
    # Create ENUM types first using raw SQL with DO block for idempotency
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE gueststatus AS ENUM ('invited', 'started', 'completed', 'expired');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE jobstatus AS ENUM ('pending', 'processing', 'completed', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Reference the enum types for use in table columns
    guest_status = postgresql.ENUM(
        "invited", "started", "completed", "expired",
        name="gueststatus",
        create_type=False,
    )
    job_status = postgresql.ENUM(
        "pending", "processing", "completed", "failed",
        name="jobstatus",
        create_type=False,
    )

    # Teams
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Interview Templates
    op.create_table(
        "interview_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("prompt_modifier", sa.Text, nullable=True),
        sa.Column("default_minutes", sa.Integer, server_default="30", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Interviews
    op.create_table(
        "interviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("questions", postgresql.JSONB, nullable=True),
        sa.Column("research_summary", sa.Text, nullable=True),
        sa.Column("target_minutes", sa.Integer, server_default="30", nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Guests
    op.create_table(
        "guests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "interview_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("bio_url", sa.String(500), nullable=True),
        sa.Column("magic_token", sa.String(100), unique=True, nullable=False),
        sa.Column(
            "status",
            guest_status,
            server_default="invited",
            nullable=False,
        ),
        sa.Column("room_name", sa.String(255), nullable=True),
        sa.Column("room_token", sa.Text, nullable=True),
        sa.Column("claimed_by", sa.String(255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_guests_magic_token", "guests", ["magic_token"])
    op.create_index("idx_guests_status", "guests", ["status"])

    # Transcripts
    op.create_table(
        "transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "guest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guests.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("entries", postgresql.JSONB, nullable=True),
        sa.Column("conversation_context", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Analyses
    op.create_table(
        "analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "guest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guests.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("insights", postgresql.JSONB, nullable=True),
        sa.Column("summary_md", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Job Queue
    op.create_table(
        "job_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            job_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer, server_default="3", nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
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
    op.drop_table("analyses")
    op.drop_table("transcripts")
    op.drop_table("guests")
    op.drop_table("interviews")
    op.drop_table("interview_templates")
    op.drop_table("users")
    op.drop_table("teams")

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS gueststatus")
