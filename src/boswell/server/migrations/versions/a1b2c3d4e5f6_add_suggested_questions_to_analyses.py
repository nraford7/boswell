"""Add suggested_questions to analyses

Revision ID: a1b2c3d4e5f6
Revises: 50f315d3bc02
Create Date: 2026-02-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '50f315d3bc02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add suggested_questions column to analyses table."""
    op.add_column('analyses', sa.Column('suggested_questions', postgresql.JSONB, nullable=True))


def downgrade() -> None:
    """Remove suggested_questions column from analyses table."""
    op.drop_column('analyses', 'suggested_questions')
