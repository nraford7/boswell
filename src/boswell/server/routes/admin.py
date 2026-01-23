# src/boswell/server/routes/admin.py
"""Admin routes for dashboard and interview management."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Guest, GuestStatus, Interview, InterviewTemplate, User
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


@router.get("/interviews/new")
async def interview_new_form(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the new interview form."""
    # Fetch templates for the user's team
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.team_id == user.team_id)
        .order_by(InterviewTemplate.name)
    )
    interview_templates = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/interview_new.html",
        context={
            "user": user,
            "templates": interview_templates,
        },
    )


@router.post("/interviews/new")
async def interview_new_submit(
    request: Request,
    user: User = Depends(require_auth),
    topic: str = Form(...),
    template_id: Optional[str] = Form(None),
    target_minutes: int = Form(30),
    db: AsyncSession = Depends(get_session),
):
    """Create a new interview."""
    # Validate topic
    topic = topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    # Parse template_id if provided
    parsed_template_id: Optional[UUID] = None
    if template_id and template_id.strip():
        try:
            parsed_template_id = UUID(template_id)
            # Verify the template belongs to the user's team
            result = await db.execute(
                select(InterviewTemplate)
                .where(InterviewTemplate.id == parsed_template_id)
                .where(InterviewTemplate.team_id == user.team_id)
            )
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=400, detail="Invalid template")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid template ID")

    # Validate target_minutes
    if target_minutes < 5 or target_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Duration must be between 5 and 120 minutes"
        )

    # Create the interview
    interview = Interview(
        team_id=user.team_id,
        template_id=parsed_template_id,
        topic=topic,
        target_minutes=target_minutes,
        created_by=user.id,
    )
    db.add(interview)
    await db.flush()

    # Redirect to the interview detail page
    return RedirectResponse(
        url=f"/admin/interviews/{interview.id}",
        status_code=303,
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


# -----------------------------------------------------------------------------
# Template Routes
# -----------------------------------------------------------------------------


@router.get("/templates")
async def templates_list(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """List all templates for the user's team."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.team_id == user.team_id)
        .order_by(InterviewTemplate.name)
    )
    interview_templates = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/templates_list.html",
        context={
            "user": user,
            "templates": interview_templates,
        },
    )


@router.get("/templates/new")
async def template_new_form(
    request: Request,
    user: User = Depends(require_auth),
):
    """Show the new template form."""
    return templates.TemplateResponse(
        request=request,
        name="admin/template_form.html",
        context={
            "user": user,
            "template": None,
            "mode": "new",
        },
    )


@router.post("/templates/new")
async def template_new_submit(
    request: Request,
    user: User = Depends(require_auth),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    prompt_modifier: Optional[str] = Form(None),
    default_minutes: int = Form(30),
    db: AsyncSession = Depends(get_session),
):
    """Create a new template."""
    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Clean optional fields
    description = description.strip() if description else None
    prompt_modifier = prompt_modifier.strip() if prompt_modifier else None

    # Validate default_minutes
    if default_minutes < 5 or default_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Default duration must be between 5 and 120 minutes"
        )

    # Create the template
    template = InterviewTemplate(
        team_id=user.team_id,
        name=name,
        description=description,
        prompt_modifier=prompt_modifier,
        default_minutes=default_minutes,
    )
    db.add(template)
    await db.flush()

    return RedirectResponse(url="/admin/templates", status_code=303)


@router.get("/templates/{template_id}/edit")
async def template_edit_form(
    request: Request,
    template_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the edit template form."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.id == template_id)
        .where(InterviewTemplate.team_id == user.team_id)
    )
    template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    return templates.TemplateResponse(
        request=request,
        name="admin/template_form.html",
        context={
            "user": user,
            "template": template,
            "mode": "edit",
        },
    )


@router.post("/templates/{template_id}/edit")
async def template_edit_submit(
    request: Request,
    template_id: UUID,
    user: User = Depends(require_auth),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    prompt_modifier: Optional[str] = Form(None),
    default_minutes: int = Form(30),
    db: AsyncSession = Depends(get_session),
):
    """Update an existing template."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.id == template_id)
        .where(InterviewTemplate.team_id == user.team_id)
    )
    template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Clean optional fields
    description = description.strip() if description else None
    prompt_modifier = prompt_modifier.strip() if prompt_modifier else None

    # Validate default_minutes
    if default_minutes < 5 or default_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Default duration must be between 5 and 120 minutes"
        )

    # Update the template
    template.name = name
    template.description = description
    template.prompt_modifier = prompt_modifier
    template.default_minutes = default_minutes

    await db.flush()

    return RedirectResponse(url="/admin/templates", status_code=303)


@router.post("/templates/{template_id}/delete")
async def template_delete(
    request: Request,
    template_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Delete a template."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.id == template_id)
        .where(InterviewTemplate.team_id == user.team_id)
    )
    template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    await db.delete(template)
    await db.flush()

    return RedirectResponse(url="/admin/templates", status_code=303)
