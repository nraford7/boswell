"""Add public_link_token to projects

Revision ID: 3513772ba486
Revises: 001
Create Date: 2026-01-24 01:46:43.175995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3513772ba486'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('interviews', sa.Column('public_link_token', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_interviews_public_link_token'), 'interviews', ['public_link_token'], unique=True)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(op.f('ix_interviews_public_link_token'), table_name='interviews')
    op.drop_column('interviews', 'public_link_token')
