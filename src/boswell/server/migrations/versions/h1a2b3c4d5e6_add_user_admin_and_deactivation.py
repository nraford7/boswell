"""Add is_admin and deactivated_at to users.

Revision ID: h1a2b3c4d5e6
Revises: g3c4d5e6f7a8
Create Date: 2026-02-11
"""
from typing import Sequence, Union
import os

from alembic import op
import sqlalchemy as sa

revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, None] = "g3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))

    # One-time bootstrap: promote initial admin by email
    admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    if admin_email:
        conn = op.get_bind()
        conn.execute(
            sa.text("UPDATE users SET is_admin = true WHERE email = :email"),
            {"email": admin_email.strip().lower()},
        )


def downgrade() -> None:
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_admin")
