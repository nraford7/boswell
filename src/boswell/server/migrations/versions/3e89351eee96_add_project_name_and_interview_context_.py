"""add project name and interview context fields

Revision ID: 3e89351eee96
Revises: 2bed6a0aa001
Create Date: 2026-01-24 09:23:49.826678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3e89351eee96'
down_revision: Union[str, None] = '2bed6a0aa001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add name and research_links to Project (interviews table)
    op.add_column('interviews', sa.Column('name', sa.String(length=255), nullable=True))
    op.add_column('interviews', sa.Column('research_links', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Add context_notes and context_links to Interview (guests table)
    op.add_column('guests', sa.Column('context_notes', sa.Text(), nullable=True))
    op.add_column('guests', sa.Column('context_links', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    # Remove context_notes and context_links from Interview (guests table)
    op.drop_column('guests', 'context_links')
    op.drop_column('guests', 'context_notes')

    # Remove name and research_links from Project (interviews table)
    op.drop_column('interviews', 'research_links')
    op.drop_column('interviews', 'name')
