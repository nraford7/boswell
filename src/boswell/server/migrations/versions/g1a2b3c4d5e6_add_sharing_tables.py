"""Add project_shares, account_invites tables and user auth columns.

Revision ID: g1a2b3c4d5e6
Revises: f6a7b8c9d0e1
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create projectrole ENUM type using raw SQL with DO block for idempotency
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE projectrole AS ENUM ('view', 'operate', 'collaborate', 'owner');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Reference the enum type for use in table columns
    project_role = postgresql.ENUM(
        "view", "operate", "collaborate", "owner",
        name="projectrole",
        create_type=False,
    )

    # Add password_hash column to users table
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text, nullable=True)
    )

    # Add email_verified_at column to users table
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Make users.team_id nullable
    op.alter_column(
        "users",
        "team_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True
    )

    # Create project_shares table
    op.create_table(
        "project_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", project_role, nullable=False),
        sa.Column(
            "granted_by",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add constraints and indexes for project_shares
    op.create_unique_constraint(
        "uq_project_shares_project_user",
        "project_shares",
        ["project_id", "user_id"]
    )
    op.create_index(
        "ix_project_shares_user_project",
        "project_shares",
        ["user_id", "project_id"]
    )
    op.create_index(
        "ix_project_shares_project_role",
        "project_shares",
        ["project_id", "role"]
    )

    # Create account_invites table
    op.create_table(
        "account_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("role", project_role, nullable=True),
        sa.Column(
            "claimed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add check constraint for account_invites
    op.create_check_constraint(
        "ck_invite_project_role_together",
        "account_invites",
        "(project_id IS NULL AND role IS NULL) OR (project_id IS NOT NULL AND role IS NOT NULL)"
    )

    # Add indexes for account_invites
    op.create_index(
        "ix_invite_email_status",
        "account_invites",
        ["email", "claimed_at", "revoked_at", "expires_at"]
    )
    op.create_index(
        "ix_invite_project_status",
        "account_invites",
        ["project_id", "claimed_at", "revoked_at"]
    )


def downgrade() -> None:
    # Drop account_invites table
    op.drop_table("account_invites")

    # Drop project_shares table
    op.drop_table("project_shares")

    # Make users.team_id NOT NULL again
    op.alter_column(
        "users",
        "team_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False
    )

    # Drop email_verified_at column from users
    op.drop_column("users", "email_verified_at")

    # Drop password_hash column from users
    op.drop_column("users", "password_hash")

    # Drop projectrole ENUM type
    op.execute("DROP TYPE IF EXISTS projectrole")
