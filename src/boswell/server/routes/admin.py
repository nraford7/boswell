# src/boswell/server/routes/admin.py
"""Admin routes for dashboard and interview management."""

import csv
import io
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.database import get_session
from boswell.server.main import templates
from boswell.server.models import Guest, GuestStatus, Interview, InterviewTemplate, User
from boswell.server.routes.auth import get_current_user

logger = logging.getLogger(__name__)

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


# -----------------------------------------------------------------------------
# Guest Invite Routes
# -----------------------------------------------------------------------------


def parse_guest_csv(
    file_content: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV content for guest import.

    Args:
        file_content: The CSV file content as a string.

    Returns:
        A tuple of (valid_rows, errors) where valid_rows is a list of dicts
        with 'email' and 'name' keys, and errors is a list of error messages.
    """
    valid_rows = []
    errors = []

    reader = csv.DictReader(io.StringIO(file_content))

    # Check for required 'email' column
    if reader.fieldnames is None or "email" not in reader.fieldnames:
        return [], ["CSV must have an 'email' column"]

    for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
        email = row.get("email", "").strip()
        name = row.get("name", "").strip()

        if not email:
            errors.append(f"Row {row_num}: Missing email")
            continue

        # Basic email validation
        if "@" not in email or "." not in email:
            errors.append(f"Row {row_num}: Invalid email '{email}'")
            continue

        # Use email prefix as name if not provided
        if not name:
            name = email.split("@")[0]

        valid_rows.append({"email": email, "name": name})

    return valid_rows, errors


@router.get("/interviews/{interview_id}/invite")
async def invite_form(
    request: Request,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the invite guest form for an interview."""
    # Fetch interview
    result = await db.execute(
        select(Interview)
        .where(Interview.id == interview_id)
        .where(Interview.team_id == user.team_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    return templates.TemplateResponse(
        request=request,
        name="admin/invite.html",
        context={
            "user": user,
            "interview": interview,
        },
    )


@router.post("/interviews/{interview_id}/invite")
async def invite_submit(
    request: Request,
    interview_id: UUID,
    user: User = Depends(require_auth),
    email: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    csv_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
):
    """Invite guest(s) to an interview.

    Accepts either:
    - Single invite: email (required), name (optional)
    - CSV upload: file with email (required), name (optional) columns
    """
    # Fetch interview
    result = await db.execute(
        select(Interview)
        .where(Interview.id == interview_id)
        .where(Interview.team_id == user.team_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    guests_created = 0
    errors = []

    # Check if CSV was uploaded
    if csv_file and csv_file.filename:
        # Read and parse CSV
        content = await csv_file.read()
        try:
            csv_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded")

        valid_rows, parse_errors = parse_guest_csv(csv_text)
        errors.extend(parse_errors)

        # Create guests from valid rows
        for row in valid_rows:
            guest = Guest(
                interview_id=interview_id,
                email=row["email"],
                name=row["name"],
            )
            db.add(guest)
            guests_created += 1

        if errors:
            logger.warning(
                f"CSV import for interview {interview_id} had {len(errors)} errors: {errors}"
            )

    elif email:
        # Single invite
        email = email.strip()
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        # Basic email validation
        if "@" not in email or "." not in email:
            raise HTTPException(status_code=400, detail="Invalid email address")

        # Use email prefix as name if not provided
        guest_name = name.strip() if name else email.split("@")[0]

        guest = Guest(
            interview_id=interview_id,
            email=email,
            name=guest_name,
        )
        db.add(guest)
        guests_created += 1

    else:
        raise HTTPException(
            status_code=400, detail="Either email or CSV file is required"
        )

    await db.flush()

    return RedirectResponse(
        url=f"/admin/interviews/{interview_id}",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Bulk Import Routes
# -----------------------------------------------------------------------------


def parse_bulk_csv(
    file_content: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV content for bulk interview/guest import.

    Args:
        file_content: The CSV file content as a string.

    Returns:
        A tuple of (valid_rows, errors) where valid_rows is a list of dicts
        with 'email', 'name', and optionally 'interview_topic' or 'interview_id' keys.
    """
    valid_rows = []
    errors = []

    reader = csv.DictReader(io.StringIO(file_content))

    # Check for required 'email' column
    if reader.fieldnames is None or "email" not in reader.fieldnames:
        return [], ["CSV must have an 'email' column"]

    has_topic = "interview_topic" in (reader.fieldnames or [])
    has_id = "interview_id" in (reader.fieldnames or [])

    for row_num, row in enumerate(reader, start=2):
        email = row.get("email", "").strip()
        name = row.get("name", "").strip()
        interview_topic = row.get("interview_topic", "").strip()
        interview_id = row.get("interview_id", "").strip()

        if not email:
            errors.append(f"Row {row_num}: Missing email")
            continue

        # Basic email validation
        if "@" not in email or "." not in email:
            errors.append(f"Row {row_num}: Invalid email '{email}'")
            continue

        # Use email prefix as name if not provided
        if not name:
            name = email.split("@")[0]

        # Validate interview_id if provided
        if interview_id:
            try:
                UUID(interview_id)
            except ValueError:
                errors.append(f"Row {row_num}: Invalid interview_id '{interview_id}'")
                continue

        valid_rows.append({
            "email": email,
            "name": name,
            "interview_topic": interview_topic,
            "interview_id": interview_id,
        })

    return valid_rows, errors


@router.get("/bulk")
async def bulk_import_form(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the bulk import form."""
    # Fetch templates for the user's team
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.team_id == user.team_id)
        .order_by(InterviewTemplate.name)
    )
    interview_templates = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/bulk_import.html",
        context={
            "user": user,
            "templates": interview_templates,
        },
    )


@router.post("/bulk")
async def bulk_import_submit(
    request: Request,
    user: User = Depends(require_auth),
    csv_file: UploadFile = File(...),
    template_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Process bulk import of interviews and guests from CSV.

    CSV columns:
    - email (required): Guest email address
    - name (optional): Guest name (uses email prefix if not provided)
    - interview_topic (optional): Creates a new interview with this topic
    - interview_id (optional): Adds guest to existing interview
    """
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

    # Read and parse CSV
    content = await csv_file.read()
    try:
        csv_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded")

    valid_rows, parse_errors = parse_bulk_csv(csv_text)

    if parse_errors:
        logger.warning(f"Bulk import had {len(parse_errors)} errors: {parse_errors}")

    if not valid_rows:
        raise HTTPException(
            status_code=400,
            detail="No valid rows found in CSV. " + "; ".join(parse_errors[:5]),
        )

    # Track created interviews by topic to avoid duplicates
    topic_to_interview: dict[str, Interview] = {}
    interviews_created = 0
    guests_created = 0

    for row in valid_rows:
        interview_id = None

        # Determine which interview to add the guest to
        if row["interview_id"]:
            # Use existing interview
            interview_id = UUID(row["interview_id"])
            # Verify interview belongs to user's team
            result = await db.execute(
                select(Interview)
                .where(Interview.id == interview_id)
                .where(Interview.team_id == user.team_id)
            )
            if result.scalar_one_or_none() is None:
                logger.warning(
                    f"Skipping row: interview {interview_id} not found or not accessible"
                )
                continue

        elif row["interview_topic"]:
            # Create new interview or reuse one with same topic
            topic = row["interview_topic"]
            if topic in topic_to_interview:
                interview_id = topic_to_interview[topic].id
            else:
                interview = Interview(
                    team_id=user.team_id,
                    template_id=parsed_template_id,
                    topic=topic,
                    target_minutes=30,
                    created_by=user.id,
                )
                db.add(interview)
                await db.flush()
                topic_to_interview[topic] = interview
                interview_id = interview.id
                interviews_created += 1
        else:
            logger.warning(
                f"Skipping row: no interview_topic or interview_id provided for {row['email']}"
            )
            continue

        # Create guest
        guest = Guest(
            interview_id=interview_id,
            email=row["email"],
            name=row["name"],
        )
        db.add(guest)
        guests_created += 1

    await db.flush()

    logger.info(
        f"Bulk import complete: {interviews_created} interviews, {guests_created} guests created"
    )

    return RedirectResponse(url="/admin/", status_code=303)
