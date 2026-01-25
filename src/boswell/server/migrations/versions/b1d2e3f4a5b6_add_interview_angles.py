"""add interview angles and template content fields

Revision ID: b1d2e3f4a5b6
Revises: acf23ac9efd5
Create Date: 2026-01-25 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1d2e3f4a5b6'
down_revision: Union[str, None] = 'acf23ac9efd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create the interview angle enum type
    interview_angle_enum = postgresql.ENUM(
        'exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom',
        name='interviewangle',
        create_type=True
    )
    interview_angle_enum.create(op.get_bind(), checkfirst=True)

    # Add new columns to interview_templates
    op.add_column('interview_templates', sa.Column('questions', postgresql.JSONB, nullable=True))
    op.add_column('interview_templates', sa.Column('research_summary', sa.Text, nullable=True))
    op.add_column('interview_templates', sa.Column('research_links', postgresql.JSONB, nullable=True))
    op.add_column('interview_templates', sa.Column('angle', sa.Enum('exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom', name='interviewangle', create_constraint=False), nullable=True))
    op.add_column('interview_templates', sa.Column('angle_secondary', sa.Enum('exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom', name='interviewangle', create_constraint=False), nullable=True))
    op.add_column('interview_templates', sa.Column('angle_custom', sa.Text, nullable=True))

    # Add new columns to guests (interviews)
    op.add_column('guests', sa.Column('template_id', postgresql.UUID, nullable=True))
    op.add_column('guests', sa.Column('questions', postgresql.JSONB, nullable=True))
    op.add_column('guests', sa.Column('research_summary', sa.Text, nullable=True))
    op.add_column('guests', sa.Column('research_links', postgresql.JSONB, nullable=True))
    op.add_column('guests', sa.Column('angle', sa.Enum('exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom', name='interviewangle', create_constraint=False), nullable=True))
    op.add_column('guests', sa.Column('angle_secondary', sa.Enum('exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom', name='interviewangle', create_constraint=False), nullable=True))
    op.add_column('guests', sa.Column('angle_custom', sa.Text, nullable=True))

    # Add foreign key constraint for template_id
    op.create_foreign_key(
        'fk_guests_template_id',
        'guests', 'interview_templates',
        ['template_id'], ['id'],
        ondelete='SET NULL'
    )

    # Remove template_id from interviews (projects) table
    # First drop the foreign key constraint
    op.drop_constraint('interviews_template_id_fkey', 'interviews', type_='foreignkey')
    # Then drop the column
    op.drop_column('interviews', 'template_id')


def downgrade() -> None:
    """Downgrade database schema."""
    # Add template_id back to interviews (projects) table
    op.add_column('interviews', sa.Column('template_id', postgresql.UUID, nullable=True))
    op.create_foreign_key(
        'interviews_template_id_fkey',
        'interviews', 'interview_templates',
        ['template_id'], ['id'],
        ondelete='SET NULL'
    )

    # Drop foreign key and columns from guests (interviews)
    op.drop_constraint('fk_guests_template_id', 'guests', type_='foreignkey')
    op.drop_column('guests', 'angle_custom')
    op.drop_column('guests', 'angle_secondary')
    op.drop_column('guests', 'angle')
    op.drop_column('guests', 'research_links')
    op.drop_column('guests', 'research_summary')
    op.drop_column('guests', 'questions')
    op.drop_column('guests', 'template_id')

    # Drop columns from interview_templates
    op.drop_column('interview_templates', 'angle_custom')
    op.drop_column('interview_templates', 'angle_secondary')
    op.drop_column('interview_templates', 'angle')
    op.drop_column('interview_templates', 'research_links')
    op.drop_column('interview_templates', 'research_summary')
    op.drop_column('interview_templates', 'questions')

    # Drop the enum type
    interview_angle_enum = postgresql.ENUM(
        'exploratory', 'interrogative', 'imaginative', 'documentary', 'coaching', 'custom',
        name='interviewangle'
    )
    interview_angle_enum.drop(op.get_bind(), checkfirst=True)
