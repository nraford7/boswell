"""Add indexes for hot query paths.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # Guest queries by project (interview_id is the FK to interviews/projects)
    op.create_index("idx_guests_interview_id", "guests", ["interview_id"])

    # Composite for filtering by project + status (dashboard counts)
    op.create_index("idx_guests_interview_id_status", "guests", ["interview_id", "status"])

    # Worker claims: started interviews with no claim and room_name set
    op.create_index(
        "idx_guests_status_claimed",
        "guests",
        ["status", "claimed_by"],
        postgresql_where=sa.text("status = 'started' AND claimed_by IS NULL"),
    )

    # Job queue: improve pending job polling
    op.create_index(
        "idx_job_queue_status_created",
        "job_queue",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("idx_job_queue_status_created")
    op.drop_index("idx_guests_status_claimed")
    op.drop_index("idx_guests_interview_id_status")
    op.drop_index("idx_guests_interview_id")
