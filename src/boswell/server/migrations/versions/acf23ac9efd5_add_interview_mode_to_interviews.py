"""add interview_mode to interviews

Revision ID: acf23ac9efd5
Revises: cca0c543540a
Create Date: 2026-01-25 09:36:35.755852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acf23ac9efd5'
down_revision: Union[str, None] = 'cca0c543540a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('guests', sa.Column('interview_mode', sa.String(20), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('guests', 'interview_mode')
