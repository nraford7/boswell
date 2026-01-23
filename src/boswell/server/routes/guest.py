# src/boswell/server/routes/guest.py
"""Guest routes for magic token access (no auth required)."""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Guest, GuestStatus


def create_mock_daily_room(guest_id: str) -> dict:
    """Create a mock Daily.co room for development.

    In production, this will call the Daily.co API.

    Args:
        guest_id: The guest's UUID as a string.

    Returns:
        dict with room_name, room_url, and room_token.
    """
    room_name = f"boswell-{guest_id[:8]}"
    return {
        "room_name": room_name,
        "room_url": f"https://boswell.daily.co/{room_name}",
        "room_token": secrets.token_urlsafe(32),
    }

router = APIRouter()


@router.get("/i/{magic_token}", response_class=HTMLResponse)
async def guest_landing(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Guest landing page accessed via magic token.

    - Returns 404 if guest not found or expired
    - Redirects to thank you page if completed
    - Shows rejoin page if started with room_name
    - Shows landing page otherwise
    """
    # Fetch guest with interview relationship
    result = await db.execute(
        select(Guest)
        .options(selectinload(Guest.interview))
        .where(Guest.magic_token == magic_token)
    )
    guest = result.scalar_one_or_none()

    # Not found
    if not guest:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        guest.status == GuestStatus.expired
        or (guest.expires_at and guest.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Completed - redirect to thank you page
    if guest.status == GuestStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Started with room - show rejoin page
    if guest.status == GuestStatus.started and guest.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}/rejoin",
            status_code=303,
        )

    # Default: show landing page with interview details
    return templates.TemplateResponse(
        request=request,
        name="guest/landing.html",
        context={
            "interview": guest.interview,
            "guest": guest,
        },
    )


@router.post("/i/{magic_token}/start")
async def start_interview(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Start the interview for a guest.

    - Validates guest exists and is not expired/completed
    - Creates Daily.co room (mock for now)
    - Updates guest: status="started", room_name, room_token, started_at
    - Redirects to interview room page
    """
    # Fetch guest with interview relationship
    result = await db.execute(
        select(Guest)
        .options(selectinload(Guest.interview))
        .where(Guest.magic_token == magic_token)
    )
    guest = result.scalar_one_or_none()

    # Not found
    if not guest:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        guest.status == GuestStatus.expired
        or (guest.expires_at and guest.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Already completed - redirect to thank you page
    if guest.status == GuestStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Already started - redirect to room
    if guest.status == GuestStatus.started and guest.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}/room",
            status_code=303,
        )

    # Create Daily.co room (mock for now)
    room_info = create_mock_daily_room(str(guest.id))

    # Update guest record
    guest.status = GuestStatus.started
    guest.room_name = room_info["room_name"]
    guest.room_token = room_info["room_token"]
    guest.started_at = now

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

    Only accessible if guest.status == "started" and room_name exists.
    """
    # Fetch guest with interview relationship
    result = await db.execute(
        select(Guest)
        .options(selectinload(Guest.interview))
        .where(Guest.magic_token == magic_token)
    )
    guest = result.scalar_one_or_none()

    # Not found
    if not guest:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "Interview not found."},
            status_code=404,
        )

    # Check if expired (by status or expires_at)
    now = datetime.now(timezone.utc)
    is_expired = (
        guest.status == GuestStatus.expired
        or (guest.expires_at and guest.expires_at < now)
    )

    if is_expired:
        return templates.TemplateResponse(
            request=request,
            name="guest/landing.html",
            context={"error": "This interview link has expired."},
            status_code=404,
        )

    # Completed - redirect to thank you page
    if guest.status == GuestStatus.completed:
        return RedirectResponse(
            url=f"/i/{magic_token}/thankyou",
            status_code=303,
        )

    # Not started or no room - redirect to landing page
    if guest.status != GuestStatus.started or not guest.room_name:
        return RedirectResponse(
            url=f"/i/{magic_token}",
            status_code=303,
        )

    # Build room URL with token
    room_url = f"https://boswell.daily.co/{guest.room_name}?t={guest.room_token}"

    return templates.TemplateResponse(
        request=request,
        name="guest/room.html",
        context={
            "interview": guest.interview,
            "guest": guest,
            "room_url": room_url,
        },
    )
