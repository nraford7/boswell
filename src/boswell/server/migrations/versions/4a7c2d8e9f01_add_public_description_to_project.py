"""add public_description and intro_prompt to project

Revision ID: 4a7c2d8e9f01
Revises: 3e89351eee96
Create Date: 2026-01-24 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4a7c2d8e9f01'
down_revision: Union[str, None] = '3e89351eee96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add public_description to Project (interviews table)
    # This is the description shown to guests on the public landing page
    # Separate from topic which provides private instructions for Claude
    op.add_column('interviews', sa.Column('public_description', sa.Text(), nullable=True))
    # Add intro_prompt for how Boswell greets guests
    op.add_column('interviews', sa.Column('intro_prompt', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('interviews', 'intro_prompt')
    op.drop_column('interviews', 'public_description')
