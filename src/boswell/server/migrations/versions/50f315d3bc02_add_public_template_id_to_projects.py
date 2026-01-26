"""Add public_template_id to projects

Revision ID: 50f315d3bc02
Revises: b1d2e3f4a5b6
Create Date: 2026-01-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '50f315d3bc02'
down_revision: Union[str, None] = 'b1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add public_template_id column to projects (interviews table)."""
    op.add_column('interviews', sa.Column('public_template_id', postgresql.UUID, nullable=True))
    op.create_foreign_key(
        'fk_interviews_public_template_id',
        'interviews', 'interview_templates',
        ['public_template_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove public_template_id column from projects (interviews table)."""
    op.drop_constraint('fk_interviews_public_template_id', 'interviews', type_='foreignkey')
    op.drop_column('interviews', 'public_template_id')
