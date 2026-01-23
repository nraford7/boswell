# src/boswell/server/routes/admin.py
"""Admin routes for dashboard and interview management."""

import asyncio
import csv
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.config import get_settings
from boswell.server.database import get_session
from boswell.server.email import send_invitation_email
from boswell.server.main import templates
from boswell.server.models import Interview, InterviewStatus, Project, InterviewTemplate, Transcript, User
from boswell.server.routes.auth import get_current_user

# Import ingestion functions
try:
    from boswell.ingestion import read_document, fetch_url, generate_questions
    INGESTION_AVAILABLE = True
except ImportError:
    INGESTION_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------


class AuthRedirect(Exception):
    """Custom exception to trigger auth redirect."""
    def __init__(self, url: str):
        self.url = url


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
        HTTPException: 401 if user is not authenticated.
    """
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"Location": "/admin/login"},
        )
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
    """Dashboard home page showing list of projects for the user's team."""
    # Query projects for the user's team with related data
    result = await db.execute(
        select(Project)
        .where(Project.team_id == user.team_id)
        .options(
            selectinload(Project.template),
            selectinload(Project.interviews),
        )
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "user": user,
            "projects": projects,
        },
    )


@router.get("/projects/new")
async def project_new_form(
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
        name="admin/project_new.html",
        context={
            "user": user,
            "templates": interview_templates,
        },
    )


@router.post("/projects/new")
async def project_new_submit(
    request: Request,
    user: User = Depends(require_auth),
    guest_name: str = Form(...),
    guest_email: str = Form(...),
    topic: str = Form(...),
    template_id: Optional[str] = Form(None),
    target_minutes: int = Form(30),
    research_urls: Optional[str] = Form(None),
    research_files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_session),
):
    """Create a new interview with a guest."""
    # Validate guest info
    guest_name = guest_name.strip()
    guest_email = guest_email.strip().lower()
    if not guest_name:
        raise HTTPException(status_code=400, detail="Interview name is required")
    if not guest_email or "@" not in guest_email:
        raise HTTPException(status_code=400, detail="Valid guest email is required")

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

    # Process research materials
    research_parts = []
    questions = None

    # Process uploaded files
    if research_files and INGESTION_AVAILABLE:
        for upload_file in research_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                try:
                    # Save to temp file and process
                    suffix = Path(upload_file.filename).suffix
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        content = await upload_file.read()
                        tmp.write(content)
                        tmp_path = tmp.name

                    # Read the document
                    doc_content = await asyncio.to_thread(read_document, Path(tmp_path))
                    if doc_content:
                        research_parts.append(f"=== Document: {upload_file.filename} ===\n{doc_content}")

                    # Clean up temp file
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to process file {upload_file.filename}: {e}")

    # Process URLs
    if research_urls and INGESTION_AVAILABLE:
        urls = [u.strip() for u in research_urls.split("\n") if u.strip()]
        for url in urls:
            if url.startswith("http://") or url.startswith("https://"):
                try:
                    url_content = await asyncio.to_thread(fetch_url, url)
                    if url_content:
                        research_parts.append(f"=== URL: {url} ===\n{url_content}")
                except Exception as e:
                    logger.warning(f"Failed to fetch URL {url}: {e}")

    # Combine research summary
    research_summary = "\n\n".join(research_parts) if research_parts else None

    # Generate questions if we have research
    if research_summary and INGESTION_AVAILABLE:
        try:
            questions_list = await asyncio.to_thread(
                generate_questions, topic, research_summary, 12
            )
            if questions_list:
                questions = {
                    "questions": [
                        {"id": i + 1, "text": q, "type": "generated"}
                        for i, q in enumerate(questions_list)
                    ]
                }
        except Exception as e:
            logger.warning(f"Failed to generate questions: {e}")

    # Create the project
    project = Project(
        team_id=user.team_id,
        template_id=parsed_template_id,
        topic=topic,
        target_minutes=target_minutes,
        created_by=user.id,
        research_summary=research_summary,
        questions=questions,
    )
    db.add(project)
    await db.flush()

    # Create the interview (without sending email)
    interview = Interview(
        project_id=project.id,
        email=guest_email,
        name=guest_name,
    )
    db.add(interview)
    await db.flush()

    # Show the interview created confirmation page
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="admin/project_created.html",
        context={
            "user": user,
            "project": project,
            "interview": interview,
            "base_url": settings.base_url,
        },
    )


@router.get("/projects/{project_id}")
async def project_detail(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Project detail page showing project info and interview list."""
    # Fetch project with related data
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.template),
            selectinload(Project.interviews).selectinload(Interview.transcript),
            selectinload(Project.interviews).selectinload(Interview.analysis),
        )
    )
    project = result.scalar_one_or_none()

    # Check if project exists and belongs to user's team
    if project is None or project.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="admin/project_detail.html",
        context={
            "user": user,
            "project": project,
            "interviews": project.interviews,
            "base_url": settings.base_url,
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
# Interview Invite Routes
# -----------------------------------------------------------------------------


def parse_interview_csv(
    file_content: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV content for interview import.

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


@router.get("/projects/{project_id}/invite")
async def invite_form(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the invite form for a project."""
    # Fetch project
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return templates.TemplateResponse(
        request=request,
        name="admin/invite.html",
        context={
            "user": user,
            "project": project,
        },
    )


@router.post("/projects/{project_id}/invite")
async def invite_submit(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    email: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    csv_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
):
    """Invite interviewee(s) to a project.

    Accepts either:
    - Single invite: email (required), name (optional)
    - CSV upload: file with email (required), name (optional) columns
    """
    # Fetch project
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    new_interviews: list[Interview] = []
    errors = []

    # Check if CSV was uploaded
    if csv_file and csv_file.filename:
        # Read and parse CSV
        content = await csv_file.read()
        try:
            csv_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded")

        valid_rows, parse_errors = parse_interview_csv(csv_text)
        errors.extend(parse_errors)

        # Create interviews from valid rows
        for row in valid_rows:
            interview = Interview(
                project_id=project_id,
                email=row["email"],
                name=row["name"],
            )
            db.add(interview)
            new_interviews.append(interview)

        if errors:
            logger.warning(
                f"CSV import for project {project_id} had {len(errors)} errors: {errors}"
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
        interviewee_name = name.strip() if name else email.split("@")[0]

        interview = Interview(
            project_id=project_id,
            email=email,
            name=interviewee_name,
        )
        db.add(interview)
        new_interviews.append(interview)

    else:
        raise HTTPException(
            status_code=400, detail="Either email or CSV file is required"
        )

    await db.flush()

    # Send invitation emails to newly created interviews
    settings = get_settings()
    for interview_obj in new_interviews:
        magic_link = f"{settings.base_url}/i/{interview_obj.magic_token}"
        await send_invitation_email(
            to=interview_obj.email,
            guest_name=interview_obj.name,
            interview_topic=project.topic,
            magic_link=magic_link,
        )

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Bulk Import Routes
# -----------------------------------------------------------------------------


def parse_bulk_csv(
    file_content: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV content for bulk project/interview import.

    Args:
        file_content: The CSV file content as a string.

    Returns:
        A tuple of (valid_rows, errors) where valid_rows is a list of dicts
        with 'email', 'name', and optionally 'project_topic' or 'project_id' keys.
    """
    valid_rows = []
    errors = []

    reader = csv.DictReader(io.StringIO(file_content))

    # Check for required 'email' column
    if reader.fieldnames is None or "email" not in reader.fieldnames:
        return [], ["CSV must have an 'email' column"]

    has_topic = "project_topic" in (reader.fieldnames or [])
    has_id = "project_id" in (reader.fieldnames or [])

    for row_num, row in enumerate(reader, start=2):
        email = row.get("email", "").strip()
        name = row.get("name", "").strip()
        project_topic = row.get("project_topic", "").strip()
        project_id = row.get("project_id", "").strip()

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

        # Validate project_id if provided
        if project_id:
            try:
                UUID(project_id)
            except ValueError:
                errors.append(f"Row {row_num}: Invalid project_id '{project_id}'")
                continue

        valid_rows.append({
            "email": email,
            "name": name,
            "project_topic": project_topic,
            "project_id": project_id,
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
    """Process bulk import of projects and interviews from CSV.

    CSV columns:
    - email (required): Interviewee email address
    - name (optional): Interviewee name (uses email prefix if not provided)
    - project_topic (optional): Creates a new project with this topic
    - project_id (optional): Adds interview to existing project
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

    # Track created projects by topic to avoid duplicates
    topic_to_project: dict[str, Project] = {}
    projects_created = 0
    interviews_created = 0

    for row in valid_rows:
        project_id = None

        # Determine which project to add the interview to
        if row["project_id"]:
            # Use existing project
            project_id = UUID(row["project_id"])
            # Verify project belongs to user's team
            result = await db.execute(
                select(Project)
                .where(Project.id == project_id)
                .where(Project.team_id == user.team_id)
            )
            if result.scalar_one_or_none() is None:
                logger.warning(
                    f"Skipping row: project {project_id} not found or not accessible"
                )
                continue

        elif row["project_topic"]:
            # Create new project or reuse one with same topic
            topic = row["project_topic"]
            if topic in topic_to_project:
                project_id = topic_to_project[topic].id
            else:
                project = Project(
                    team_id=user.team_id,
                    template_id=parsed_template_id,
                    topic=topic,
                    target_minutes=30,
                    created_by=user.id,
                )
                db.add(project)
                await db.flush()
                topic_to_project[topic] = project
                project_id = project.id
                projects_created += 1
        else:
            logger.warning(
                f"Skipping row: no project_topic or project_id provided for {row['email']}"
            )
            continue

        # Create interview
        interview = Interview(
            project_id=project_id,
            email=row["email"],
            name=row["name"],
        )
        db.add(interview)
        interviews_created += 1

    await db.flush()

    logger.info(
        f"Bulk import complete: {projects_created} projects, {interviews_created} interviews created"
    )

    return RedirectResponse(url="/admin/", status_code=303)


# -----------------------------------------------------------------------------
# Follow-up Interview Routes
# -----------------------------------------------------------------------------


@router.post("/projects/{project_id}/interviews/{interview_id}/followup")
async def create_followup_interview(
    request: Request,
    project_id: UUID,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Create a follow-up interview for a completed interview.

    Creates a new Interview with the same email/name but a fresh magic_token.
    """
    # Fetch the original interview
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    original = result.scalar_one_or_none()

    if original is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify project belongs to user's team
    if original.project.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Create the follow-up interview (new magic_token generated automatically)
    followup = Interview(
        project_id=project_id,
        email=original.email,
        name=original.name,
    )
    db.add(followup)
    await db.flush()

    logger.info(
        f"Created follow-up interview {followup.id} for {original.email} "
        f"(original: {original.id})"
    )

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Delete Routes
# -----------------------------------------------------------------------------


@router.post("/projects/{project_id}/interviews/{interview_id}/delete")
async def delete_interview(
    request: Request,
    project_id: UUID,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Delete an interview.

    Also deletes associated transcript and analysis records (via CASCADE).
    """
    # Fetch the interview with project
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.project))
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify project belongs to user's team
    if interview.project.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Interview not found")

    await db.delete(interview)
    await db.flush()

    logger.info(f"Deleted interview {interview_id} from project {project_id}")

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/delete")
async def delete_project(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Delete a project and all associated interviews.

    Also deletes associated transcripts and analyses (via CASCADE).
    """
    # Fetch the project
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    await db.delete(project)
    await db.flush()

    logger.info(f"Deleted project {project_id}")

    return RedirectResponse(
        url="/admin/",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Transcript Routes
# -----------------------------------------------------------------------------


@router.get("/projects/{project_id}/interviews/{interview_id}/transcript")
async def view_transcript(
    request: Request,
    project_id: UUID,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """View the transcript for an interview."""
    # Fetch the interview with transcript and project
    result = await db.execute(
        select(Interview)
        .options(
            selectinload(Interview.project),
            selectinload(Interview.transcript),
        )
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify project belongs to user's team
    if interview.project.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Interview not found")

    if not interview.transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return templates.TemplateResponse(
        request=request,
        name="admin/transcript.html",
        context={
            "user": user,
            "project": interview.project,
            "interview": interview,
            "transcript": interview.transcript,
            "entries": interview.transcript.entries or [],
        },
    )


@router.get("/projects/{project_id}/interviews/{interview_id}/transcript/download")
async def download_transcript(
    request: Request,
    project_id: UUID,
    interview_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Download the transcript as JSON."""
    # Fetch the interview with transcript and project
    result = await db.execute(
        select(Interview)
        .options(
            selectinload(Interview.project),
            selectinload(Interview.transcript),
        )
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify project belongs to user's team
    if interview.project.team_id != user.team_id:
        raise HTTPException(status_code=404, detail="Interview not found")

    if not interview.transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Build download data
    download_data = {
        "interview": {
            "id": str(interview.id),
            "name": interview.name,
            "email": interview.email,
            "started_at": interview.started_at.isoformat() if interview.started_at else None,
            "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
        },
        "project": {
            "id": str(interview.project.id),
            "topic": interview.project.topic,
        },
        "transcript": interview.transcript.entries or [],
    }

    # Return as downloadable JSON
    filename = f"transcript-{interview.name.lower().replace(' ', '-')}-{interview_id}.json"
    return JSONResponse(
        content=download_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
