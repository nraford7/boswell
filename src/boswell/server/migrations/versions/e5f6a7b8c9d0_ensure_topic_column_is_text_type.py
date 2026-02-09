"""Ensure topic column is TEXT type

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-09 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change topic column from varchar(500) to TEXT."""
    op.alter_column("interviews", "topic", type_=sa.Text(), existing_type=sa.String(500))


def downgrade() -> None:
    """Revert topic column from TEXT to varchar(500)."""
    op.alter_column("interviews", "topic", type_=sa.String(500), existing_type=sa.Text())
