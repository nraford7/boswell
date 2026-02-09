"""Add processing_status to projects

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add processing_status column to interviews (projects) table."""
    op.add_column('interviews', sa.Column('processing_status', sa.String(20), nullable=False, server_default='ready'))


def downgrade() -> None:
    """Remove processing_status column from interviews (projects) table."""
    op.drop_column('interviews', 'processing_status')
