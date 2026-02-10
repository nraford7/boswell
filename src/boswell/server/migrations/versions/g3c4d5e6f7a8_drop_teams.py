"""Drop teams table and all team_id columns.

Phase F of migration strategy.

Revision ID: g3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g3c4d5e6f7a8"
down_revision: Union[str, None] = "g2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop team_id from users (already nullable from g1 migration)
    op.drop_constraint("users_team_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "team_id")

    # Drop team_id from interviews (projects)
    op.drop_constraint("interviews_team_id_fkey", "interviews", type_="foreignkey")
    op.drop_column("interviews", "team_id")

    # Drop team_id from interview_templates
    op.drop_constraint("interview_templates_team_id_fkey", "interview_templates", type_="foreignkey")
    op.drop_column("interview_templates", "team_id")

    # Drop teams table
    op.drop_table("teams")


def downgrade() -> None:
    # Recreate teams table
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

    # Re-add team_id columns
    op.add_column("interview_templates",
                  sa.Column("team_id", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True))
    op.add_column("interviews",
                  sa.Column("team_id", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True))
    op.add_column("users",
                  sa.Column("team_id", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True))
