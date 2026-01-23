# src/boswell/server/routes/admin.py
"""Admin routes for dashboard and interview management."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Guest, GuestStatus, Interview, User
from boswell.server.routes.auth import get_current_user

router = APIRouter(prefix="/admin")


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------


async def require_auth(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Dependency that requires authentication.

    Redirects to login page if user is not authenticated.

    Args:
        request: The incoming request.
        user: The current user from get_current_user.

    Returns:
        The authenticated User object.

    Raises:
        RedirectResponse: If user is not authenticated.
    """
    if user is None:
        raise RedirectResponse(url="/admin/login", status_code=303)
    return user


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@router.get("/")
async def dashboard(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Dashboard home page showing list of interviews for the user's team."""
    # Query interviews for the user's team with related data
    result = await db.execute(
        select(Interview)
        .where(Interview.team_id == user.team_id)
        .options(
            selectinload(Interview.template),
            selectinload(Interview.guests),
        )
        .order_by(Interview.created_at.desc())
    )
    interviews = result.scalars().all()

    # Build interview data with guest counts
    interview_data = []
    for interview in interviews:
        guests = interview.guests
        total_guests = len(guests)
        completed_guests = sum(
            1 for g in guests if g.status == GuestStatus.completed
        )

        interview_data.append({
            "id": interview.id,
            "topic": interview.topic,
            "template_name": interview.template.name if interview.template else None,
            "total_guests": total_guests,
            "completed_guests": completed_guests,
            "created_at": interview.created_at,
        })

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "user": user,
            "interviews": interview_data,
        },
    )


@router.get("/interviews/{interview_id}")
async def interview_detail(
    request: Request,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Interview detail page showing interview info and guest list."""
    # Fetch interview with related data
    result = await db.execute(
        select(Interview)
        .where(Interview.id == interview_id)
        .options(
            selectinload(Interview.template),
            selectinload(Interview.guests).selectinload(Guest.transcript),
            selectinload(Interview.guests).selectinload(Guest.analysis),
        )
    )
    interview = result.scalar_one_or_none()

    # Check if interview exists and belongs to user's team
    if interview is None or interview.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Interview not found")

    return templates.TemplateResponse(
        request=request,
        name="admin/interview_detail.html",
        context={
            "user": user,
            "interview": interview,
            "guests": interview.guests,
        },
    )
