"""add session_count to interviews

Revision ID: cca0c543540a
Revises: 4a7c2d8e9f01
Create Date: 2026-01-25 09:32:46.487840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cca0c543540a'
down_revision: Union[str, None] = '4a7c2d8e9f01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('guests', sa.Column('session_count', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('guests', 'session_count')
