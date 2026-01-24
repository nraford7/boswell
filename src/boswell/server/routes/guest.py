# src/boswell/server/routes/guest.py
"""Interview routes for magic token access (no auth required)."""

import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.config import get_settings
from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Interview, InterviewStatus, Project

logger = logging.getLogger(__name__)

DAILY_API_URL = "https://api.daily.co/v1"


async def create_daily_room(interview_id: str, guest_name: str = "Guest") -> dict:
    """Create a Daily.co room for the interview.

    Args:
        interview_id: The interview's UUID as a string.
        guest_name: The name to display for the guest in the room.

    Returns:
        dict with room_name, room_url, and room_token.

    Raises:
        RuntimeError: If room creation fails.
    """
    settings = get_settings()
    room_name = f"boswell-{interview_id[:8]}"

    async with httpx.AsyncClient() as client:
        # Create the room
        response = await client.post(
            f"{DAILY_API_URL}/rooms",
            headers={
                "Authorization": f"Bearer {settings.daily_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "name": room_name,
                "properties": {
                    "max_participants": 10,
                    "enable_chat": False,
                    "enable_knocking": False,
                    "start_video_off": True,
                    "start_audio_off": False,
                    "exp": int(time.time()) + 7200,  # 2 hours
                },
            },
        )

        if response.status_code not in (200, 201):
            # Room might already exist, try to get it
            if "already exists" in response.text.lower():
                logger.info(f"Room {room_name} already exists, reusing")
            else:
                error_text = response.text
                logger.error(f"Failed to create Daily room: {error_text}")
                raise RuntimeError(f"Failed to create Daily room: {error_text}")

        # Get room URL (create response or fetch existing)
        room_url = f"https://emirbot.daily.co/{room_name}"

        # Create a meeting token for the guest
        token_response = await client.post(
            f"{DAILY_API_URL}/meeting-tokens",
            headers={
                "Authorization": f"Bearer {settings.daily_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "properties": {
                    "room_name": room_name,
                    "is_owner": False,
                    "user_name": guest_name,
                    "start_video_off": True,  # Audio-only by default
                },
            },
        )

        if token_response.status_code not in (200, 201):
            error_text = token_response.text
            logger.error(f"Failed to create meeting token: {error_text}")
            raise RuntimeError(f"Failed to create meeting token: {error_text}")

        token_data = token_response.json()

        return {
            "room_name": room_name,
            "room_url": room_url,
            "room_token": token_data["token"],
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

    # Create Daily.co room
    room_info = await create_daily_room(str(interview.id), interview.name)

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
    room_url = f"https://emirbot.daily.co/{interview.room_name}?t={interview.room_token}"

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


@router.post("/i/{magic_token}/reset")
async def reset_interview(
    request: Request,
    magic_token: str,
    db: AsyncSession = Depends(get_session),
):
    """Reset an interview to start over.

    Clears room_name, room_token, and resets status to invited.
    """
    # Fetch interview
    result = await db.execute(
        select(Interview)
        .where(Interview.magic_token == magic_token)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        return RedirectResponse(url=f"/i/{magic_token}", status_code=303)

    # Only allow reset if not completed
    if interview.status == InterviewStatus.completed:
        return RedirectResponse(url=f"/i/{magic_token}/thankyou", status_code=303)

    # Reset interview state
    interview.status = InterviewStatus.invited
    interview.room_name = None
    interview.room_token = None
    interview.started_at = None

    await db.commit()

    # Redirect to landing page
    return RedirectResponse(url=f"/i/{magic_token}", status_code=303)


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


@router.get("/join/{token}")
async def public_join_landing(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Landing page for public/generic interview links.

    Shows a welcome screen where guest enters their name.
    """
    # Find project by public_link_token
    result = await db.execute(
        select(Project).where(Project.public_link_token == token)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Interview link not found")

    return templates.TemplateResponse(
        "guest/public_welcome.html",
        {
            "request": request,
            "project": project,
            "token": token,
        },
    )


@router.post("/join/{token}/start")
async def start_public_interview(
    request: Request,
    token: str,
    guest_name: str = Form(...),
    db: AsyncSession = Depends(get_session),
):
    """Start an interview from a public link.

    Creates a new Interview record, Daily.co room, and redirects to room.
    """
    # Validate guest name
    guest_name = guest_name.strip()
    if not guest_name or len(guest_name) < 2:
        raise HTTPException(status_code=400, detail="Please enter your name")

    if len(guest_name) > 100:
        guest_name = guest_name[:100]

    # Find project by public_link_token
    result = await db.execute(
        select(Project).where(Project.public_link_token == token)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Interview link not found")

    # Create new Interview record
    interview = Interview(
        project_id=project.id,
        name=guest_name,
        email=None,  # No email for public interviews
        status=InterviewStatus.started,
        started_at=datetime.now(timezone.utc),
    )
    db.add(interview)
    await db.flush()  # Get the interview ID

    # Create Daily.co room with guest's name
    room_info = await create_daily_room(str(interview.id), guest_name)

    interview.room_name = room_info["room_name"]
    interview.room_token = room_info["room_token"]

    await db.commit()

    # Redirect to interview room
    return RedirectResponse(
        url=f"/i/{interview.magic_token}/room",
        status_code=303,
    )
