"""Central authorization module.

project_shares is the single source of truth for project access.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boswell.server.models import ProjectRole, ProjectShare


async def get_project_role(
    user_id: UUID, project_id: UUID, db: AsyncSession
) -> Optional[ProjectRole]:
    """Look up the user's role on a project. Returns None if no access."""
    result = await db.execute(
        select(ProjectShare.role)
        .where(ProjectShare.project_id == project_id)
        .where(ProjectShare.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def check_project_access(
    user_id: UUID,
    project_id: UUID,
    min_role: ProjectRole,
    db: AsyncSession,
) -> ProjectRole:
    """Verify user has at least min_role on the project.

    Returns the actual role if access is granted.
    Raises 404 if no access at all (don't leak existence).
    Raises 403 if access exists but insufficient.
    """
    role = await get_project_role(user_id, project_id, db)
    if role is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not (role >= min_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return role


async def assert_not_last_owner(
    project_id: UUID, user_id: UUID, db: AsyncSession
) -> None:
    """Raise if user_id is the only owner. Call before downgrade/removal."""
    from sqlalchemy import func as sa_func

    result = await db.execute(
        select(sa_func.count())
        .select_from(ProjectShare)
        .where(ProjectShare.project_id == project_id)
        .where(ProjectShare.role == ProjectRole.owner)
        .where(ProjectShare.user_id != user_id)
    )
    other_owners = result.scalar_one()
    if other_owners == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove or downgrade the last owner",
        )
