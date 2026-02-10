"""Backfill project_shares from legacy team ownership.

For each project:
1. created_by user gets 'owner' role
2. Other users in same team get 'view' role
3. If created_by is NULL, earliest team user becomes owner

Also adds created_by column to interview_templates.

Revision ID: g2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, None] = "g1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add created_by column to interview_templates
    op.add_column(
        "interview_templates",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    conn = op.get_bind()

    # Backfill template created_by from earliest team user
    conn.execute(sa.text("""
        UPDATE interview_templates t
        SET created_by = (
            SELECT u.id FROM users u
            WHERE u.team_id = t.team_id
            ORDER BY u.created_at, u.id
            LIMIT 1
        )
        WHERE t.created_by IS NULL
    """))

    # Get all projects with their team_id and created_by
    projects = conn.execute(sa.text("""
        SELECT id, team_id, created_by FROM interviews WHERE team_id IS NOT NULL
    """)).fetchall()

    for project in projects:
        project_id = project[0]
        team_id = project[1]
        created_by = project[2]

        # Get all users in this team
        team_users = conn.execute(sa.text("""
            SELECT id FROM users WHERE team_id = :team_id ORDER BY created_at, id
        """), {"team_id": team_id}).fetchall()

        if not team_users:
            continue

        # Determine owner
        owner_id = created_by if created_by else team_users[0][0]

        # Also fix created_by on the project if it was null
        if not created_by:
            conn.execute(sa.text("""
                UPDATE interviews SET created_by = :owner_id WHERE id = :project_id
            """), {"owner_id": owner_id, "project_id": project_id})

        # Insert owner share
        conn.execute(sa.text("""
            INSERT INTO project_shares (id, project_id, user_id, role, created_at, updated_at)
            VALUES (gen_random_uuid(), :project_id, :user_id, 'owner', NOW(), NOW())
            ON CONFLICT (project_id, user_id) DO NOTHING
        """), {"project_id": project_id, "user_id": owner_id})

        # Insert view shares for other team members
        for user_row in team_users:
            user_id = user_row[0]
            if user_id != owner_id:
                conn.execute(sa.text("""
                    INSERT INTO project_shares (id, project_id, user_id, role, created_at, updated_at)
                    VALUES (gen_random_uuid(), :project_id, :user_id, 'view', NOW(), NOW())
                    ON CONFLICT (project_id, user_id) DO NOTHING
                """), {"project_id": project_id, "user_id": user_id})

    # Verify invariant: every project has at least one owner
    orphans = conn.execute(sa.text("""
        SELECT i.id FROM interviews i
        WHERE i.team_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM project_shares ps
            WHERE ps.project_id = i.id AND ps.role = 'owner'
        )
    """)).fetchall()

    if orphans:
        raise Exception(
            f"MIGRATION FAILED: {len(orphans)} projects have no owner. "
            f"IDs: {[str(o[0]) for o in orphans[:10]]}"
        )


def downgrade() -> None:
    op.drop_column("interview_templates", "created_by")
    op.execute("DELETE FROM project_shares")
