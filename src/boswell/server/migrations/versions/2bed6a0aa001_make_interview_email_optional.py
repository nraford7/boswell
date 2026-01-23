"""Make interview email optional

Revision ID: 2bed6a0aa001
Revises: 3513772ba486
Create Date: 2026-01-24 01:49:09.110727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2bed6a0aa001'
down_revision: Union[str, None] = '3513772ba486'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.alter_column('guests', 'email',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)


def downgrade() -> None:
    """Downgrade database schema."""
    op.alter_column('guests', 'email',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
