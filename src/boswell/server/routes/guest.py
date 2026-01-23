# src/boswell/server/routes/guest.py
"""Interview routes for magic token access (no auth required)."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Interview, InterviewStatus


def create_mock_daily_room(interview_id: str) -> dict:
    """Create a mock Daily.co room for development.

    In production, this will call the Daily.co API.

    Args:
        interview_id: The interview's UUID as a string.

    Returns:
        dict with room_name, room_url, and room_token.
    """
    room_name = f"boswell-{interview_id[:8]}"
    return {
        "room_name": room_name,
        "room_url": f"https://boswell.daily.co/{room_name}",
        "room_token": secrets.token_urlsafe(32),
    }

router = APIRouter()


@router.get("/i/{magic_token}", response_class=HTMLResponse)
async def interview_landing(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Interview landing page accessed via magic token.

    - Returns 404 if interview not found or expired
    - Redirects to thank you page if completed
    - Shows rejoin page if started with room_name
    - Shows landing page otherwise
    """
    # Fetch interview with project relationship
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    # Not found
    if not interview:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        interview.status == InterviewStatus.expired
        or (interview.expires_at and interview.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Completed - redirect to thank you page
    if interview.status == InterviewStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Started with room - show rejoin page
    if interview.status == InterviewStatus.started and interview.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}/rejoin",
            status_code=303,
        )

    # Default: show landing page with project details
    return templates.TemplateResponse(
        request=request,
        name="guest/landing.html",
        context={
            "project": interview.project,
            "interview": interview,
        },
    )


@router.post("/i/{magic_token}/start")
async def start_interview(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Start the interview.

    - Validates interview exists and is not expired/completed
    - Creates Daily.co room (mock for now)
    - Updates interview: status="started", room_name, room_token, started_at
    - Redirects to interview room page
    """
    # Fetch interview with project relationship
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    # Not found
    if not interview:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        interview.status == InterviewStatus.expired
        or (interview.expires_at and interview.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Already completed - redirect to thank you page
    if interview.status == InterviewStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Already started - redirect to room
    if interview.status == InterviewStatus.started and interview.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}/room",
            status_code=303,
        )

    # Create Daily.co room (mock for now)
    room_info = create_mock_daily_room(str(interview.id))

    # Update interview record
    interview.status = InterviewStatus.started
    interview.room_name = room_info["room_name"]
    interview.room_token = room_info["room_token"]
    interview.started_at = now

    await db.commit()

    # Redirect to room page
    return RedirectResponse(
        url=f"/i/{magic_token}/room",
        status_code=303,
    )


@router.get("/i/{magic_token}/room", response_class=HTMLResponse)
async def interview_room(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Show the interview room page with Daily.co embed.

    Only accessible if interview.status == "started" and room_name exists.
    """
    # Fetch interview with project relationship
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    # Not found
    if not interview:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        interview.status == InterviewStatus.expired
        or (interview.expires_at and interview.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Completed - redirect to thank you page
    if interview.status == InterviewStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Not started or no room - redirect to landing page
    if interview.status != InterviewStatus.started or not interview.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}",
            status_code=303,
        )

    # Build room URL with token
    room_url = f"https://boswell.daily.co/{interview.room_name}?t={interview.room_token}"

    return templates.TemplateResponse(
        request=request,
        name="guest/room.html",
        context={
            "project": interview.project,
            "interview": interview,
            "room_url": room_url,
        },
    )


@router.get("/i/{magic_token}/rejoin", response_class=HTMLResponse)
async def interview_rejoin(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Show rejoin page for interviewees who have started but left.

    Only accessible if interview.status == "started" and room_name exists.
    """
    # Fetch interview with project relationship
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    # Not found
    if not interview:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        interview.status == InterviewStatus.expired
        or (interview.expires_at and interview.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Completed - redirect to thank you page
    if interview.status == InterviewStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Not started or no room - redirect to landing page
    if interview.status != InterviewStatus.started or not interview.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}",
            status_code=303,
        )

    # Show rejoin page
    return templates.TemplateResponse(
        request=request,
        name="guest/rejoin.html",
        context={
            "project": interview.project,
            "interview": interview,
        },
    )


@router.get("/i/{magic_token}/thankyou", response_class=HTMLResponse)
async def interview_thankyou(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Show thank you page after interview completion.

    Accessible to any interview that exists (no status requirement).
    """
    # Fetch interview with project and analysis relationships
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project), selectinload(Interview.analysis))
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    # Not found
    if not interview:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Show thank you page
    return templates.TemplateResponse(
        request=request,
        name="guest/thankyou.html",
        context={
            "project": interview.project,
            "interview": interview,
        },
    )
