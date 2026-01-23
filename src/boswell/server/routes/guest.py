# src/boswell/server/routes/guest.py
"""Guest routes for magic token access (no auth required)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Guest, GuestStatus

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
