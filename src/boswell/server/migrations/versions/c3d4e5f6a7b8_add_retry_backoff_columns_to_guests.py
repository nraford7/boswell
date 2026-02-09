"""Add retry backoff columns to guests

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-02-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add failure_count and next_retry_at columns to guests table."""
    op.add_column('guests', sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('guests', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove failure_count and next_retry_at columns from guests table."""
    op.drop_column('guests', 'next_retry_at')
    op.drop_column('guests', 'failure_count')
