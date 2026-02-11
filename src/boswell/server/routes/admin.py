# src/boswell/server/routes/admin.py
"""Admin routes for dashboard and interview management."""

import asyncio
import base64
import csv
import io
import logging
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from boswell.server.config import get_settings
from boswell.server.database import get_session
from boswell.server.email import send_invitation_email
from boswell.server.main import templates
from boswell.server.models import Analysis, Interview, InterviewAngle, InterviewStatus, Project, InterviewTemplate, ProjectRole, ProjectShare, Transcript, User
from boswell.server.authorization import check_project_access
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
    """Require authentication. Redirect passwordless users to set-password."""
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"Location": "/admin/login"},
        )
    # Gate: force password setup for migrating users
    if not user.password_hash and request.url.path not in ("/admin/set-password", "/admin/logout"):
        from fastapi.responses import RedirectResponse
        raise HTTPException(
            status_code=307,
            headers={"Location": "/admin/set-password"},
        )
    return user


async def require_admin(
    request: Request,
    user: User = Depends(require_auth),
) -> User:
    """Require admin access. Returns 403 for non-admins."""
    if not user.is_admin or user.deactivated_at is not None:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def _get_sole_owner_projects(user_id: UUID, db: AsyncSession) -> list:
    """Return projects where user_id is the only owner."""
    # Find projects where this user is an owner
    owned = await db.execute(
        select(ProjectShare.project_id)
        .where(ProjectShare.user_id == user_id)
        .where(ProjectShare.role == ProjectRole.owner)
    )
    owned_project_ids = [row[0] for row in owned.all()]

    sole_owner_projects = []
    for pid in owned_project_ids:
        count_result = await db.execute(
            select(func.count())
            .select_from(ProjectShare)
            .where(ProjectShare.project_id == pid)
            .where(ProjectShare.role == ProjectRole.owner)
        )
        if count_result.scalar_one() == 1:
            proj_result = await db.execute(select(Project).where(Project.id == pid))
            proj = proj_result.scalar_one_or_none()
            if proj:
                sole_owner_projects.append(proj)
    return sole_owner_projects


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@router.get("/")
async def dashboard(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Dashboard home page showing list of projects the user has access to."""
    # My Projects (owner)
    owned_result = await db.execute(
        select(Project)
        .join(ProjectShare, ProjectShare.project_id == Project.id)
        .where(ProjectShare.user_id == user.id)
        .where(ProjectShare.role == ProjectRole.owner)
        .order_by(Project.created_at.desc())
    )
    owned_projects = owned_result.scalars().all()

    # Shared with me
    shared_result = await db.execute(
        select(Project)
        .join(ProjectShare, ProjectShare.project_id == Project.id)
        .where(ProjectShare.user_id == user.id)
        .where(ProjectShare.role != ProjectRole.owner)
        .order_by(Project.created_at.desc())
    )
    shared_projects = shared_result.scalars().all()

    projects = owned_projects + shared_projects

    # Get interview counts per project in one aggregate query
    project_ids = [p.id for p in projects]
    counts_by_project = {}
    if project_ids:
        from sqlalchemy import func, case
        count_stmt = (
            select(
                Interview.project_id,
                func.count(Interview.id).label("total"),
                func.count(case((Interview.status == InterviewStatus.completed, 1))).label("completed"),
                func.count(case((Interview.status == InterviewStatus.invited, 1))).label("invited"),
                func.count(case((Interview.status == InterviewStatus.started, 1))).label("started"),
            )
            .where(Interview.project_id.in_(project_ids))
            .group_by(Interview.project_id)
        )
        count_result = await db.execute(count_stmt)
        counts_by_project = {row.project_id: row for row in count_result}

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "user": user,
            "owned_projects": owned_projects,
            "shared_projects": shared_projects,
            "counts_by_project": counts_by_project,
        },
    )


@router.get("/projects/new")
async def project_new_form(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the new interview form."""
    # Fetch templates created by this user
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
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
    name: str = Form(...),
    topic: str = Form(...),
    template_id: Optional[str] = Form(None),
    public_description: Optional[str] = Form(None),
    intro_prompt: Optional[str] = Form(None),
    target_minutes: int = Form(30),
    research_urls: Optional[str] = Form(None),
    research_files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_session),
):
    """Create a new project (without creating an interview)."""
    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    # Validate topic
    topic = topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    # Validate target_minutes
    if target_minutes < 5 or target_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Duration must be between 5 and 120 minutes"
        )

    # Read uploaded files into memory for async processing via job queue.
    # File content is stored as base64 in the job payload so it can be
    # processed by the jobs worker in a separate container.
    research_file_data = []
    if research_files and INGESTION_AVAILABLE:
        for upload_file in research_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                content = await upload_file.read()
                research_file_data.append({
                    "name": upload_file.filename,
                    "content_b64": base64.b64encode(content).decode("ascii"),
                })

    # Parse research URLs
    research_url_list = []
    if research_urls:
        research_url_list = [
            u.strip() for u in research_urls.split("\n")
            if u.strip() and (u.strip().startswith("http://") or u.strip().startswith("https://"))
        ]

    # Determine if async processing is needed
    has_research = bool(research_file_data or research_url_list)
    processing_status = "pending" if has_research else "ready"

    # Store URL list in research_links (just the URLs, not content)
    research_links = research_url_list if research_url_list else []

    # Clean optional string fields
    public_desc = public_description.strip() if public_description else None
    intro = intro_prompt.strip() if intro_prompt else None

    # Handle template_id first - this determines whether to generate questions
    parsed_template_id = None
    if template_id and template_id.strip():
        try:
            template_uuid = UUID(template_id)
            # Verify template belongs to user
            template_result = await db.execute(
                select(InterviewTemplate)
                .where(InterviewTemplate.id == template_uuid)
                .where(InterviewTemplate.created_by == user.id)
            )
            if template_result.scalar_one_or_none() is not None:
                parsed_template_id = template_uuid
        except ValueError:
            pass  # Invalid UUID, ignore

    # Create the project (WITHOUT interview)
    project = Project(
        name=name,
        topic=topic,
        template_id=parsed_template_id,
        public_description=public_desc if public_desc else None,
        intro_prompt=intro if intro else None,
        target_minutes=target_minutes,
        created_by=user.id,
        processing_status=processing_status,
        research_links=research_links if research_links else None,
    )
    db.add(project)
    await db.flush()
    # Create owner share
    db.add(ProjectShare(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.owner,
        granted_by=user.id,
    ))

    # Enqueue async research processing if needed
    if has_research:
        from boswell.server.jobs import enqueue_job
        await enqueue_job(
            db,
            job_type="process_project_research",
            payload={
                "project_id": str(project.id),
                "research_urls": research_url_list,
                "research_file_data": research_file_data,
                "topic": topic,
            },
        )

    await db.commit()

    # Redirect to project detail page
    return RedirectResponse(
        url=f"/admin/projects/{project.id}",
        status_code=303,
    )


@router.get("/projects/{project_id}")
async def project_detail(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Project detail page showing project info and interview list."""
    # Fetch project with interviews and transcripts (needed by template)
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.interviews).selectinload(Interview.transcript),
        )
    )
    project = result.scalar_one_or_none()

    # Check if project exists and user has access
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    role = await check_project_access(user.id, project.id, ProjectRole.view, db)

    # Fetch templates for public link configuration
    templates_result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
        .order_by(InterviewTemplate.name)
    )
    interview_templates = templates_result.scalars().all()

    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="admin/project_detail.html",
        context={
            "user": user,
            "project": project,
            "interviews": project.interviews,
            "base_url": settings.base_url,
            "templates": interview_templates,
            "is_owner": role == ProjectRole.owner,
        },
    )


@router.post("/projects/{project_id}/generate-public-link")
async def generate_public_link(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Generate or regenerate a public interview link for a project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.owner, db)

    # Generate a secure random token
    project.public_link_token = secrets.token_urlsafe(32)
    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/disable-public-link")
async def disable_public_link(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Disable the public interview link for a project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.owner, db)

    project.public_link_token = None
    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/set-template")
async def set_template(
    request: Request,
    project_id: UUID,
    template_id: Optional[str] = Form(None),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Set the default interview template for the project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Parse and validate template_id
    if template_id and template_id.strip():
        try:
            template_uuid = UUID(template_id)
            # Verify template belongs to user
            template_result = await db.execute(
                select(InterviewTemplate)
                .where(InterviewTemplate.id == template_uuid)
                .where(InterviewTemplate.created_by == user.id)
            )
            template = template_result.scalar_one_or_none()
            if template is None:
                raise HTTPException(status_code=404, detail="Template not found")
            project.template_id = template_uuid
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid template ID")
    else:
        project.template_id = None

    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Interview Creation Routes
# -----------------------------------------------------------------------------


@router.get("/projects/{project_id}/interviews/new")
async def interview_new_form(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the new interview form for a project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Fetch templates for this user
    templates_result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
        .order_by(InterviewTemplate.name)
    )
    team_templates = templates_result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/interview_new.html",
        context={
            "user": user,
            "project": project,
            "templates": team_templates,
        },
    )


@router.post("/projects/{project_id}/interviews/new")
async def interview_new_submit(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    name: str = Form(...),
    email: Optional[str] = Form(None),
    template_id: Optional[str] = Form(None),
    # "Other" content fields
    questions_text: Optional[str] = Form(None),
    research_urls: Optional[str] = Form(None),
    angle: Optional[str] = Form(None),
    angle_secondary: Optional[str] = Form(None),
    angle_custom: Optional[str] = Form(None),
    # Save as template
    save_as_template: Optional[str] = Form(None),
    new_template_name: Optional[str] = Form(None),
    # Person context
    context_notes: Optional[str] = Form(None),
    context_urls: Optional[str] = Form(None),
    context_files: list[UploadFile] = File(default=[]),
    action: str = Form("create"),
    db: AsyncSession = Depends(get_session),
):
    """Create a new interview for a project."""
    # Fetch project
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Clean email
    email = email.strip().lower() if email else None

    # Process person context materials
    context_parts = []
    context_links = []

    if context_notes and context_notes.strip():
        context_parts.append(context_notes.strip())

    if context_urls and INGESTION_AVAILABLE:
        urls = [u.strip() for u in context_urls.split("\n") if u.strip()]
        for url in urls:
            if url.startswith("http://") or url.startswith("https://"):
                context_links.append(url)
                try:
                    url_content = await asyncio.to_thread(fetch_url, url)
                    if url_content:
                        context_parts.append(f"=== {url} ===\n{url_content}")
                except Exception as e:
                    logger.warning(f"Failed to fetch URL {url}: {e}")

    if context_files and INGESTION_AVAILABLE:
        for upload_file in context_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                try:
                    suffix = Path(upload_file.filename).suffix
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        content = await upload_file.read()
                        tmp.write(content)
                        tmp_path = tmp.name

                    doc_content = await asyncio.to_thread(read_document, Path(tmp_path))
                    if doc_content:
                        context_parts.append(f"=== {upload_file.filename} ===\n{doc_content}")

                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to process file {upload_file.filename}: {e}")

    combined_context = "\n\n".join(context_parts) if context_parts else None

    # Parse template selection
    parsed_template_id = None
    if template_id and template_id.strip():
        try:
            parsed_template_id = UUID(template_id)
        except ValueError:
            pass

    # Parse questions (always available, overrides template if provided)
    interview_questions = None
    if questions_text and questions_text.strip():
        questions_list = [q.strip() for q in questions_text.strip().split("\n") if q.strip()]
        if questions_list:
            interview_questions = {"questions": [{"text": q} for q in questions_list]}

    # Parse style (only for Custom template)
    interview_angle = None
    interview_angle_secondary = None
    interview_angle_custom = None

    if not parsed_template_id:
        # Custom - parse style settings
        if angle and angle.strip():
            try:
                interview_angle = InterviewAngle(angle)
            except ValueError:
                interview_angle = InterviewAngle.exploratory

        if angle_secondary and angle_secondary.strip():
            try:
                interview_angle_secondary = InterviewAngle(angle_secondary)
            except ValueError:
                pass

        if angle_custom and angle == "custom":
            interview_angle_custom = angle_custom.strip()

        # Save as template if requested
        if save_as_template and new_template_name and new_template_name.strip():
            new_template = InterviewTemplate(
                created_by=user.id,
                name=new_template_name.strip(),
                questions=interview_questions,
                angle=interview_angle or InterviewAngle.exploratory,
                angle_secondary=interview_angle_secondary,
                angle_custom=interview_angle_custom,
                default_minutes=30,
            )
            db.add(new_template)
            await db.flush()
            # Use the new template
            parsed_template_id = new_template.id
            # Clear interview-level overrides since template now has them
            interview_questions = None
            interview_angle = None
            interview_angle_secondary = None
            interview_angle_custom = None

    # If no template selected for this interview, inherit from project
    final_template_id = parsed_template_id or project.template_id

    # Create interview
    interview = Interview(
        project_id=project_id,
        name=name,
        email=email,
        template_id=final_template_id,
        questions=interview_questions,
        angle=interview_angle,
        angle_secondary=interview_angle_secondary,
        angle_custom=interview_angle_custom,
        context_notes=combined_context,
        context_links=context_links if context_links else None,
    )
    db.add(interview)
    await db.flush()

    # Send invitation email if requested and email provided
    if action == "create_and_invite" and email:
        settings = get_settings()
        magic_link = f"{settings.base_url}/i/{interview.magic_token}"
        await send_invitation_email(
            to=email,
            guest_name=name,
            interview_topic=project.topic,
            magic_link=magic_link,
        )
        logger.info(f"Sent invitation email to {email} for interview {interview.id}")

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
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
    """List all templates for the user."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
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
    default_minutes: int = Form(30),
    questions_text: Optional[str] = Form(None),
    research_urls: Optional[str] = Form(None),
    research_files: list[UploadFile] = File(default=[]),
    angle: str = Form("exploratory"),
    angle_secondary: Optional[str] = Form(None),
    angle_custom: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Create a new template."""
    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Clean optional fields
    description = description.strip() if description else None

    # Validate default_minutes
    if default_minutes < 5 or default_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Default duration must be between 5 and 120 minutes"
        )

    # Parse questions
    questions = None
    if questions_text and questions_text.strip():
        questions_list = [q.strip() for q in questions_text.strip().split("\n") if q.strip()]
        if questions_list:
            questions = {"questions": [{"text": q} for q in questions_list]}

    # Parse research URLs and process files
    research_links = None
    research_summary_parts = []

    if research_urls and research_urls.strip():
        urls = [u.strip() for u in research_urls.strip().split("\n") if u.strip() and u.strip().startswith("http")]
        if urls:
            research_links = urls
            # Fetch URL content if ingestion is available
            if INGESTION_AVAILABLE:
                for url in urls:
                    try:
                        url_content = await asyncio.to_thread(fetch_url, url)
                        if url_content:
                            research_summary_parts.append(f"=== URL: {url} ===\n{url_content}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch URL {url}: {e}")

    # Process uploaded files
    if research_files and INGESTION_AVAILABLE:
        for upload_file in research_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                try:
                    suffix = Path(upload_file.filename).suffix
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        content = await upload_file.read()
                        tmp.write(content)
                        tmp_path = tmp.name

                    doc_content = await asyncio.to_thread(read_document, Path(tmp_path))
                    if doc_content:
                        research_summary_parts.append(f"=== Document: {upload_file.filename} ===\n{doc_content}")

                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to process file {upload_file.filename}: {e}")

    research_summary = "\n\n".join(research_summary_parts) if research_summary_parts else None

    # Parse angle
    try:
        angle_enum = InterviewAngle(angle)
    except ValueError:
        angle_enum = InterviewAngle.exploratory

    # Parse secondary angle
    angle_secondary_enum = None
    if angle_secondary and angle_secondary.strip():
        try:
            angle_secondary_enum = InterviewAngle(angle_secondary)
        except ValueError:
            pass

    # Clean custom angle
    angle_custom_text = angle_custom.strip() if angle_custom and angle == "custom" else None

    # Create the template
    template = InterviewTemplate(
        created_by=user.id,
        name=name,
        description=description,
        default_minutes=default_minutes,
        questions=questions,
        research_summary=research_summary,
        research_links=research_links,
        angle=angle_enum,
        angle_secondary=angle_secondary_enum,
        angle_custom=angle_custom_text,
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
        .where(InterviewTemplate.created_by == user.id)
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
    default_minutes: int = Form(30),
    questions_text: Optional[str] = Form(None),
    research_urls: Optional[str] = Form(None),
    research_files: list[UploadFile] = File(default=[]),
    angle: str = Form("exploratory"),
    angle_secondary: Optional[str] = Form(None),
    angle_custom: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Update an existing template."""
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.id == template_id)
        .where(InterviewTemplate.created_by == user.id)
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

    # Validate default_minutes
    if default_minutes < 5 or default_minutes > 120:
        raise HTTPException(
            status_code=400, detail="Default duration must be between 5 and 120 minutes"
        )

    # Parse questions
    questions = None
    if questions_text and questions_text.strip():
        questions_list = [q.strip() for q in questions_text.strip().split("\n") if q.strip()]
        if questions_list:
            questions = {"questions": [{"text": q} for q in questions_list]}

    # Parse research URLs and process files
    research_links = None
    research_summary_parts = []

    # Keep existing research summary if no new files/urls provided
    if template.research_summary:
        research_summary_parts.append(template.research_summary)

    if research_urls and research_urls.strip():
        urls = [u.strip() for u in research_urls.strip().split("\n") if u.strip() and u.strip().startswith("http")]
        if urls:
            research_links = urls
            # Fetch URL content if ingestion is available
            if INGESTION_AVAILABLE:
                for url in urls:
                    try:
                        url_content = await asyncio.to_thread(fetch_url, url)
                        if url_content:
                            research_summary_parts.append(f"=== URL: {url} ===\n{url_content}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch URL {url}: {e}")

    # Process uploaded files
    if research_files and INGESTION_AVAILABLE:
        for upload_file in research_files:
            if upload_file.filename and upload_file.size and upload_file.size > 0:
                try:
                    suffix = Path(upload_file.filename).suffix
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        content = await upload_file.read()
                        tmp.write(content)
                        tmp_path = tmp.name

                    doc_content = await asyncio.to_thread(read_document, Path(tmp_path))
                    if doc_content:
                        research_summary_parts.append(f"=== Document: {upload_file.filename} ===\n{doc_content}")

                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to process file {upload_file.filename}: {e}")

    research_summary = "\n\n".join(research_summary_parts) if research_summary_parts else None

    # Parse angle
    try:
        angle_enum = InterviewAngle(angle)
    except ValueError:
        angle_enum = InterviewAngle.exploratory

    # Parse secondary angle
    angle_secondary_enum = None
    if angle_secondary and angle_secondary.strip():
        try:
            angle_secondary_enum = InterviewAngle(angle_secondary)
        except ValueError:
            pass

    # Clean custom angle
    angle_custom_text = angle_custom.strip() if angle_custom and angle == "custom" else None

    # Update the template
    template.name = name
    template.description = description
    template.default_minutes = default_minutes
    template.questions = questions
    template.research_summary = research_summary
    template.research_links = research_links
    template.angle = angle_enum
    template.angle_secondary = angle_secondary_enum
    template.angle_custom = angle_custom_text

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
        .where(InterviewTemplate.created_by == user.id)
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
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    return templates.TemplateResponse(
        request=request,
        name="admin/project_bulk_import.html",
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
    csv_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
):
    """Bulk import interviews from CSV and send invitations."""
    # Fetch project
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Read and parse CSV
    content = await csv_file.read()
    try:
        csv_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded")

    valid_rows, parse_errors = parse_interview_csv(csv_text)

    if parse_errors:
        logger.warning(
            f"CSV import for project {project_id} had {len(parse_errors)} errors: {parse_errors}"
        )

    if not valid_rows:
        raise HTTPException(
            status_code=400,
            detail="No valid rows found in CSV. " + "; ".join(parse_errors[:5]),
        )

    new_interviews: list[Interview] = []
    for row in valid_rows:
        interview = Interview(
            project_id=project_id,
            email=row["email"],
            name=row["name"],
        )
        db.add(interview)
        new_interviews.append(interview)

    await db.flush()

    # Enqueue invitation emails via job queue
    from boswell.server.jobs import enqueue_job

    settings = get_settings()
    for interview_obj in new_interviews:
        if interview_obj.email:
            magic_link = f"{settings.base_url}/i/{interview_obj.magic_token}"
            await enqueue_job(
                db,
                job_type="send_invitation_email",
                payload={
                    "to": interview_obj.email,
                    "guest_name": interview_obj.name,
                    "interview_topic": project.topic,
                    "magic_link": magic_link,
                },
            )

    await db.commit()

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
    # Fetch templates for the user
    result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
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
    db: AsyncSession = Depends(get_session),
):
    """Process bulk import of projects and interviews from CSV.

    CSV columns:
    - email (required): Interviewee email address
    - name (optional): Interviewee name (uses email prefix if not provided)
    - project_topic (optional): Creates a new project with this topic
    - project_id (optional): Adds interview to existing project
    """
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
            # Verify user has collaborate access to the project
            try:
                await check_project_access(user.id, project_id, ProjectRole.collaborate, db)
            except HTTPException:
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
                    topic=topic,
                    target_minutes=30,
                    created_by=user.id,
                )
                db.add(project)
                await db.flush()
                # Create owner share
                db.add(ProjectShare(
                    project_id=project.id,
                    user_id=user.id,
                    role=ProjectRole.owner,
                    granted_by=user.id,
                ))
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

    # Verify user has access to the project
    await check_project_access(user.id, original.project_id, ProjectRole.collaborate, db)

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

    # Verify user has access to the project
    await check_project_access(user.id, interview.project_id, ProjectRole.collaborate, db)

    await db.delete(interview)
    await db.flush()

    logger.info(f"Deleted interview {interview_id} from project {project_id}")

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/interviews/bulk-delete")
async def bulk_delete_interviews(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Delete multiple interviews at once."""
    # Parse JSON body
    body = await request.json()
    interview_ids = body.get("interview_ids", [])

    if not interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    # Validate UUIDs
    try:
        uuids = [UUID(id_str) for id_str in interview_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interview ID format")

    # Fetch project to verify access
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Delete interviews that belong to this project
    result = await db.execute(
        select(Interview)
        .where(Interview.id.in_(uuids))
        .where(Interview.project_id == project_id)
    )
    interviews = result.scalars().all()

    deleted_count = 0
    for interview in interviews:
        await db.delete(interview)
        deleted_count += 1

    await db.flush()

    logger.info(f"Bulk deleted {deleted_count} interviews from project {project_id}")

    return JSONResponse({"deleted": deleted_count})


@router.post("/projects/{project_id}/interviews/bulk-remind")
async def bulk_remind_interviews(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Send reminder emails to multiple interviews."""
    body = await request.json()
    interview_ids = body.get("interview_ids", [])

    if not interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    try:
        uuids = [UUID(id_str) for id_str in interview_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interview ID format")

    # Fetch project
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.operate, db)

    # Fetch eligible interviews (invited or started, with email)
    result = await db.execute(
        select(Interview)
        .where(Interview.id.in_(uuids))
        .where(Interview.project_id == project_id)
        .where(Interview.status.in_([InterviewStatus.invited, InterviewStatus.started]))
        .where(Interview.email.isnot(None))
    )
    interviews = result.scalars().all()

    from boswell.server.jobs import enqueue_job

    settings = get_settings()
    enqueue_count = 0
    for interview in interviews:
        if interview.email:
            magic_link = f"{settings.base_url}/i/{interview.magic_token}"
            await enqueue_job(
                db,
                job_type="send_invitation_email",
                payload={
                    "to": interview.email,
                    "guest_name": interview.name,
                    "interview_topic": project.topic,
                    "magic_link": magic_link,
                },
            )
            enqueue_count += 1

    await db.commit()

    logger.info(f"Queued {enqueue_count} reminder emails for project {project_id}")

    return JSONResponse({"queued": enqueue_count, "total": len(interview_ids)})


@router.post("/projects/{project_id}/interviews/bulk-followup")
async def bulk_followup_interviews(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Create follow-up interviews for multiple completed interviews."""
    body = await request.json()
    interview_ids = body.get("interview_ids", [])

    if not interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    try:
        uuids = [UUID(id_str) for id_str in interview_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interview ID format")

    # Fetch project
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Fetch completed interviews only
    result = await db.execute(
        select(Interview)
        .where(Interview.id.in_(uuids))
        .where(Interview.project_id == project_id)
        .where(Interview.status == InterviewStatus.completed)
    )
    interviews = result.scalars().all()

    created_count = 0
    for original in interviews:
        followup = Interview(
            project_id=project_id,
            email=original.email,
            name=original.name,
        )
        db.add(followup)
        created_count += 1

    await db.flush()

    logger.info(f"Created {created_count} follow-up interviews for project {project_id}")

    return JSONResponse({"created": created_count, "total": len(interview_ids)})


@router.get("/projects/{project_id}/transcripts/bulk-download")
async def bulk_download_transcripts(
    request: Request,
    project_id: UUID,
    ids: str,  # Comma-separated interview IDs
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Download transcripts for selected interviews as JSON."""
    # Parse comma-separated IDs
    id_strings = [s.strip() for s in ids.split(",") if s.strip()]
    if not id_strings:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    try:
        uuids = [UUID(id_str) for id_str in id_strings]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid interview ID format")

    # Fetch project
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.view, db)

    # Fetch interviews with transcripts
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.transcript))
        .where(Interview.id.in_(uuids))
        .where(Interview.project_id == project_id)
        .where(Interview.status == InterviewStatus.completed)
    )
    interviews = result.scalars().all()

    # Build download data
    all_transcripts = []
    for interview in interviews:
        if interview.transcript:
            all_transcripts.append({
                "interview": {
                    "id": str(interview.id),
                    "name": interview.name,
                    "email": interview.email,
                    "started_at": interview.started_at.isoformat() if interview.started_at else None,
                    "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
                },
                "transcript": interview.transcript.entries or [],
            })

    if not all_transcripts:
        raise HTTPException(status_code=404, detail="No transcripts found for selected interviews")

    download_data = {
        "project": {
            "id": str(project.id),
            "topic": project.topic,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "interviews": all_transcripts,
    }

    filename = f"transcripts-{project.topic.lower().replace(' ', '-')[:30]}-selected.json"
    return JSONResponse(
        content=download_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
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
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.owner, db)

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
    # Fetch the interview with transcript, analysis, and project
    result = await db.execute(
        select(Interview)
        .options(
            selectinload(Interview.project),
            selectinload(Interview.transcript),
            selectinload(Interview.analysis),
        )
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    interview = result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify user has access to the project
    await check_project_access(user.id, interview.project_id, ProjectRole.view, db)

    if not interview.transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Extract suggested questions if analysis exists
    suggested_questions = None
    if interview.analysis and interview.analysis.suggested_questions:
        suggested_questions = interview.analysis.suggested_questions.get("questions", [])

    return templates.TemplateResponse(
        request=request,
        name="admin/transcript.html",
        context={
            "user": user,
            "project": interview.project,
            "interview": interview,
            "transcript": interview.transcript,
            "entries": interview.transcript.entries or [],
            "analysis": interview.analysis,
            "suggested_questions": suggested_questions,
        },
    )


@router.get("/projects/{project_id}/interviews/{interview_id}/transcript/download")
async def download_transcript(
    request: Request,
    project_id: UUID,
    interview_id: UUID,
    format: str = "json",
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Download the transcript as JSON, Markdown, or plain text."""
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

    # Verify user has access to the project
    await check_project_access(user.id, interview.project_id, ProjectRole.view, db)

    if not interview.transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Sanitize name for filename
    safe_name = interview.name.lower().replace(' ', '-').replace('/', '-')

    if format == "md":
        # Build Markdown content
        lines = [
            f"# Interview Transcript: {interview.name}",
            "",
            f"**Topic:** {interview.project.topic}",
            "",
        ]
        if interview.email:
            lines.append(f"**Email:** {interview.email}")
        if interview.completed_at:
            lines.append(f"**Date:** {interview.completed_at.strftime('%B %d, %Y at %I:%M %p')}")
        lines.extend(["", "---", ""])

        entries = interview.transcript.entries or []
        for entry in entries:
            if entry.get("struck"):
                continue  # Skip struck entries
            speaker = entry.get("speaker", "Unknown")
            text = entry.get("text", "")
            # Format speaker name nicely
            if speaker.lower() == "boswell":
                lines.append(f"**Boswell:** {text}")
            else:
                lines.append(f"**{speaker}:** {text}")
            lines.append("")

        content = "\n".join(lines)
        filename = f"transcript-{safe_name}-{interview_id}.md"

        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    if format == "txt":
        # Build plain text content
        lines = [
            f"Interview Transcript: {interview.name}",
            f"Topic: {interview.project.topic}",
        ]
        if interview.email:
            lines.append(f"Email: {interview.email}")
        if interview.completed_at:
            lines.append(f"Date: {interview.completed_at.strftime('%B %d, %Y at %I:%M %p')}")
        lines.extend(["", "=" * 50, ""])

        entries = interview.transcript.entries or []
        for entry in entries:
            if entry.get("struck"):
                continue  # Skip struck entries
            speaker = entry.get("speaker", "Unknown")
            text = entry.get("text", "")
            lines.append(f"{speaker}: {text}")
            lines.append("")

        content = "\n".join(lines)
        filename = f"transcript-{safe_name}-{interview_id}.txt"

        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    # Default: JSON format
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

    filename = f"transcript-{safe_name}-{interview_id}.json"
    return JSONResponse(
        content=download_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.get("/projects/{project_id}/edit")
async def edit_project_form(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the project edit form."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Fetch templates for public link configuration
    templates_result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.created_by == user.id)
        .order_by(InterviewTemplate.name)
    )
    interview_templates = templates_result.scalars().all()

    # Get questions as a list of strings
    questions_list = []
    if project.questions and isinstance(project.questions, dict):
        raw_questions = project.questions.get("questions", [])
        for q in raw_questions:
            if isinstance(q, dict):
                questions_list.append(q.get("text", ""))
            else:
                questions_list.append(str(q))

    return templates.TemplateResponse(
        "admin/project_edit.html",
        {
            "request": request,
            "user": user,
            "project": project,
            "questions_text": "\n".join(questions_list),
            "templates": interview_templates,
        },
    )


@router.post("/projects/{project_id}/edit")
async def edit_project(
    request: Request,
    project_id: UUID,
    name: str = Form(...),
    topic: str = Form(...),
    public_description: str = Form(""),
    intro_prompt: str = Form(""),
    research_summary: str = Form(""),
    questions_text: str = Form(""),
    template_id: Optional[str] = Form(None),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Save project edits."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Update fields
    project.name = name.strip()
    project.topic = topic.strip()
    project.public_description = public_description.strip() if public_description.strip() else None
    project.intro_prompt = intro_prompt.strip() if intro_prompt.strip() else None
    project.research_summary = research_summary.strip() if research_summary.strip() else None

    # Parse questions (one per line)
    if questions_text.strip():
        questions_lines = [q.strip() for q in questions_text.strip().split("\n") if q.strip()]
        project.questions = {"questions": [{"text": q} for q in questions_lines]}
    else:
        project.questions = None

    # Handle template_id
    if template_id and template_id.strip():
        try:
            template_uuid = UUID(template_id)
            # Verify template belongs to user
            template_result = await db.execute(
                select(InterviewTemplate)
                .where(InterviewTemplate.id == template_uuid)
                .where(InterviewTemplate.created_by == user.id)
            )
            if template_result.scalar_one_or_none() is not None:
                project.template_id = template_uuid
        except ValueError:
            pass  # Invalid UUID, ignore
    else:
        project.template_id = None

    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/add-questions")
async def add_questions_from_interview(
    request: Request,
    project_id: UUID,
    interview_id: UUID = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Add suggested questions from an interview's analysis to the project.

    Merges the suggested questions from the interview's analysis into the
    project's existing question set, avoiding duplicates.
    """
    # Fetch project
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.collaborate, db)

    # Fetch interview with analysis
    interview_result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.analysis))
        .where(Interview.id == interview_id)
        .where(Interview.project_id == project_id)
    )
    interview = interview_result.scalar_one_or_none()

    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    if not interview.analysis or not interview.analysis.suggested_questions:
        raise HTTPException(status_code=400, detail="No suggested questions available for this interview")

    # Get existing project questions
    existing_questions = []
    if project.questions and isinstance(project.questions, dict):
        existing_questions = project.questions.get("questions", [])

    # Extract text from existing questions for duplicate detection
    existing_texts = set()
    for q in existing_questions:
        if isinstance(q, dict):
            existing_texts.add(q.get("text", "").lower().strip())
        elif isinstance(q, str):
            existing_texts.add(q.lower().strip())

    # Get suggested questions from the analysis
    suggested = interview.analysis.suggested_questions.get("questions", [])

    # Add new questions that aren't duplicates
    added_count = 0
    next_id = len(existing_questions) + 1
    for sq in suggested:
        question_text = sq.get("question", "") if isinstance(sq, dict) else str(sq)
        if question_text.lower().strip() not in existing_texts:
            new_question = {
                "id": next_id,
                "text": question_text,
                "type": "suggested",
                "source": f"interview:{interview_id}",
            }
            if isinstance(sq, dict) and sq.get("rationale"):
                new_question["rationale"] = sq["rationale"]
            existing_questions.append(new_question)
            existing_texts.add(question_text.lower().strip())
            next_id += 1
            added_count += 1

    # Update project questions
    project.questions = {"questions": existing_questions}
    await db.commit()

    logger.info(
        f"Added {added_count} suggested questions from interview {interview_id} "
        f"to project {project_id}"
    )

    return RedirectResponse(
        url=f"/admin/projects/{project_id}/interviews/{interview_id}/transcript",
        status_code=303,
    )


@router.get("/projects/{project_id}/transcripts/download-all")
async def download_all_transcripts(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Download all completed transcripts as a single JSON file."""
    import json

    # Fetch project with all interviews and transcripts
    result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.interviews).selectinload(Interview.transcript)
        )
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_access(user.id, project.id, ProjectRole.view, db)

    # Collect all completed interviews with transcripts
    all_transcripts = []
    for interview in project.interviews:
        if interview.status == InterviewStatus.completed and interview.transcript:
            all_transcripts.append({
                "interview": {
                    "id": str(interview.id),
                    "name": interview.name,
                    "email": interview.email,
                    "started_at": interview.started_at.isoformat() if interview.started_at else None,
                    "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
                },
                "transcript": interview.transcript.entries or [],
            })

    if not all_transcripts:
        raise HTTPException(status_code=404, detail="No completed transcripts found")

    download_data = {
        "project": {
            "id": str(project.id),
            "topic": project.topic,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "interviews": all_transcripts,
    }

    filename = f"transcripts-{project.topic.lower().replace(' ', '-')[:30]}-{project_id}.json"
    return JSONResponse(
        content=download_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# -----------------------------------------------------------------------------
# Project Sharing Routes
# -----------------------------------------------------------------------------


@router.get("/projects/{project_id}/sharing")
async def project_sharing(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """View project sharing settings (owner only)."""
    await check_project_access(user.id, project_id, ProjectRole.owner, db)

    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    # Get collaborators
    shares_result = await db.execute(
        select(ProjectShare)
        .options(selectinload(ProjectShare.user))
        .where(ProjectShare.project_id == project_id)
        .order_by(ProjectShare.created_at)
    )
    shares = shares_result.scalars().all()

    # Get pending invites
    from boswell.server.models import AccountInvite
    invites_result = await db.execute(
        select(AccountInvite)
        .where(AccountInvite.project_id == project_id)
        .where(AccountInvite.claimed_at.is_(None))
        .where(AccountInvite.revoked_at.is_(None))
        .order_by(AccountInvite.created_at.desc())
    )
    pending_invites = invites_result.scalars().all()

    invite_link = request.query_params.get("invite_link")

    return templates.TemplateResponse(
        request=request,
        name="admin/project_share.html",
        context={
            "user": user,
            "project": project,
            "shares": shares,
            "pending_invites": pending_invites,
            "roles": [r.value for r in ProjectRole],
            "invite_link": invite_link,
        },
    )


@router.post("/projects/{project_id}/sharing")
async def share_project(
    request: Request,
    project_id: UUID,
    email: str = Form(...),
    role: str = Form("view"),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Share a project with a user by email."""
    from datetime import timedelta
    from boswell.server.models import AccountInvite, _hash_token

    await check_project_access(user.id, project_id, ProjectRole.owner, db)

    normalized_email = email.strip().lower()
    share_role = ProjectRole(role)

    # Check if user exists
    target_result = await db.execute(
        select(User).where(User.email == normalized_email)
    )
    target_user = target_result.scalar_one_or_none()

    invite_link = None

    if target_user:
        # Direct share — upsert
        existing = await db.execute(
            select(ProjectShare)
            .where(ProjectShare.project_id == project_id)
            .where(ProjectShare.user_id == target_user.id)
        )
        share = existing.scalar_one_or_none()
        if share:
            share.role = share_role
            share.updated_at = datetime.now(timezone.utc)
        else:
            db.add(ProjectShare(
                project_id=project_id,
                user_id=target_user.id,
                role=share_role,
                granted_by=user.id,
            ))
    else:
        # Create invite
        raw_token = secrets.token_urlsafe(48)
        settings = get_settings()

        db.add(AccountInvite(
            token_hash=_hash_token(raw_token),
            token_prefix=raw_token[:12],
            email=normalized_email,
            invited_by=user.id,
            project_id=project_id,
            role=share_role,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))

        invite_link = f"{settings.base_url}/admin/invite/{raw_token}"

    await db.commit()

    redirect_url = f"/admin/projects/{project_id}/sharing"
    if invite_link:
        import urllib.parse
        redirect_url += f"?invite_link={urllib.parse.quote(invite_link)}"

    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/projects/{project_id}/sharing/{share_id}/update")
async def update_share(
    request: Request,
    project_id: UUID,
    share_id: UUID,
    role: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Change a collaborator's role."""
    from boswell.server.authorization import assert_not_last_owner

    await check_project_access(user.id, project_id, ProjectRole.owner, db)

    result = await db.execute(
        select(ProjectShare)
        .where(ProjectShare.id == share_id)
        .where(ProjectShare.project_id == project_id)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    new_role = ProjectRole(role)

    # If downgrading from owner, check last-owner invariant
    if share.role == ProjectRole.owner and new_role != ProjectRole.owner:
        await assert_not_last_owner(project_id, share.user_id, db)

    share.role = new_role
    share.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return RedirectResponse(url=f"/admin/projects/{project_id}/sharing", status_code=303)


@router.post("/projects/{project_id}/sharing/{share_id}/revoke")
async def revoke_share(
    request: Request,
    project_id: UUID,
    share_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Revoke a collaborator's access."""
    from boswell.server.authorization import assert_not_last_owner

    await check_project_access(user.id, project_id, ProjectRole.owner, db)

    result = await db.execute(
        select(ProjectShare)
        .where(ProjectShare.id == share_id)
        .where(ProjectShare.project_id == project_id)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    # Can't revoke last owner
    if share.role == ProjectRole.owner:
        await assert_not_last_owner(project_id, share.user_id, db)

    await db.delete(share)
    await db.commit()

    return RedirectResponse(url=f"/admin/projects/{project_id}/sharing", status_code=303)


# -----------------------------------------------------------------------------
# Account Settings Routes
# -----------------------------------------------------------------------------


@router.get("/settings")
async def account_settings(
    request: Request,
    user: User = Depends(require_auth),
):
    """Account settings page."""
    return templates.TemplateResponse(
        request=request,
        name="admin/account_settings.html",
        context={"user": user, "message": None, "active_tab": "account"},
    )


@router.post("/settings")
async def update_account(
    request: Request,
    name: str = Form(...),
    current_password: str = Form(""),
    new_password: str = Form(""),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Update account name and/or password."""
    from boswell.server.auth_utils import hash_password, verify_password

    user.name = name.strip()

    if new_password:
        if not current_password or not user.password_hash or not verify_password(current_password, user.password_hash):
            return templates.TemplateResponse(
                request=request,
                name="admin/account_settings.html",
                context={"user": user, "message": "Current password is incorrect.", "active_tab": "account"},
            )
        if len(new_password) < 8:
            return templates.TemplateResponse(
                request=request,
                name="admin/account_settings.html",
                context={"user": user, "message": "New password must be at least 8 characters.", "active_tab": "account"},
            )
        if len(new_password.encode("utf-8")) > 72:
            return templates.TemplateResponse(
                request=request,
                name="admin/account_settings.html",
                context={"user": user, "message": "New password must be 72 bytes or fewer.", "active_tab": "account"},
            )
        user.password_hash = hash_password(new_password)

    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="admin/account_settings.html",
        context={"user": user, "message": "Settings updated.", "active_tab": "account"},
    )


# -----------------------------------------------------------------------------
# Admin User Management Routes
# -----------------------------------------------------------------------------


@router.get("/settings/users")
async def admin_users_list(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Admin user management dashboard."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.project_shares).selectinload(ProjectShare.project))
        .order_by(User.created_at.desc())
    )
    all_users = result.scalars().unique().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/settings_users.html",
        context={
            "user": user,
            "all_users": all_users,
            "active_tab": "users",
        },
    )


@router.post("/settings/users/{user_id}/edit")
async def admin_edit_user(
    request: Request,
    user_id: UUID,
    name: str = Form(...),
    email: str = Form(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Update a user's name and email."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    normalized_email = email.strip().lower()
    if normalized_email != target.email:
        existing = await db.execute(select(User).where(User.email == normalized_email))
        if existing.scalar_one_or_none():
            return RedirectResponse(
                url="/admin/settings/users?error=Email+already+in+use",
                status_code=303,
            )
    target.name = name.strip()
    target.email = normalized_email
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=User+updated", status_code=303)


@router.post("/settings/users/{user_id}/reset-password")
async def admin_reset_password(
    request: Request,
    user_id: UUID,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Admin sets a new password for a user."""
    from boswell.server.auth_utils import hash_password

    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if new_password != confirm_password:
        return RedirectResponse(
            url="/admin/settings/users?error=Passwords+do+not+match",
            status_code=303,
        )
    if len(new_password) < 8:
        return RedirectResponse(
            url="/admin/settings/users?error=Password+must+be+at+least+8+characters",
            status_code=303,
        )
    if len(new_password.encode("utf-8")) > 72:
        return RedirectResponse(
            url="/admin/settings/users?error=Password+must+be+72+bytes+or+fewer",
            status_code=303,
        )

    target.password_hash = hash_password(new_password)
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=Password+reset", status_code=303)


@router.post("/settings/users/{user_id}/deactivate")
async def admin_deactivate_user(
    request: Request,
    user_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Soft-deactivate a user."""
    if user_id == user.id:
        return RedirectResponse(
            url="/admin/settings/users?error=Cannot+deactivate+your+own+account",
            status_code=303,
        )

    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Check last-admin guard (only for active admins)
    if target.is_admin and target.deactivated_at is None:
        count = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_admin == True)
            .where(User.deactivated_at.is_(None))
        )
        if count.scalar_one() <= 1:
            return RedirectResponse(
                url="/admin/settings/users?error=Cannot+deactivate+the+last+admin",
                status_code=303,
            )

    # Check sole-owner guard
    sole_projects = await _get_sole_owner_projects(user_id, db)
    if sole_projects:
        from urllib.parse import quote_plus
        names = ", ".join(p.name or p.topic for p in sole_projects)
        return RedirectResponse(
            url=f"/admin/settings/users?error={quote_plus(f'User is sole owner of: {names}. Transfer ownership first.')}",
            status_code=303,
        )

    target.deactivated_at = datetime.now(timezone.utc)
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=User+deactivated", status_code=303)


@router.post("/settings/users/{user_id}/reactivate")
async def admin_reactivate_user(
    request: Request,
    user_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Reactivate a deactivated user."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.deactivated_at = None
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=User+reactivated", status_code=303)


@router.post("/settings/users/{user_id}/delete")
async def admin_delete_user(
    request: Request,
    user_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Permanently delete a user and cascade their access."""
    if user_id == user.id:
        return RedirectResponse(
            url="/admin/settings/users?error=Cannot+delete+your+own+account",
            status_code=303,
        )

    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Check last-admin guard (only for active admins)
    if target.is_admin and target.deactivated_at is None:
        count = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_admin == True)
            .where(User.deactivated_at.is_(None))
        )
        if count.scalar_one() <= 1:
            return RedirectResponse(
                url="/admin/settings/users?error=Cannot+delete+the+last+admin",
                status_code=303,
            )

    # Check sole-owner guard
    sole_projects = await _get_sole_owner_projects(user_id, db)
    if sole_projects:
        from urllib.parse import quote_plus
        names = ", ".join(p.name or p.topic for p in sole_projects)
        return RedirectResponse(
            url=f"/admin/settings/users?error={quote_plus(f'User is sole owner of: {names}. Transfer ownership first.')}",
            status_code=303,
        )

    # Revoke pending invites sent to this user's email
    from boswell.server.models import AccountInvite
    await db.execute(
        update(AccountInvite)
        .where(AccountInvite.email == target.email)
        .where(AccountInvite.claimed_at.is_(None))
        .where(AccountInvite.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )

    await db.delete(target)
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=User+deleted", status_code=303)


@router.post("/settings/users/invite")
async def admin_invite_user(
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Create a standalone account invite (no project attached)."""
    from boswell.server.models import AccountInvite, _hash_token

    normalized_email = email.strip().lower()

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == normalized_email))
    if existing.scalar_one_or_none():
        return RedirectResponse(
            url="/admin/settings/users?error=User+already+has+an+account",
            status_code=303,
        )

    raw_token = secrets.token_urlsafe(48)
    invite = AccountInvite(
        token_hash=_hash_token(raw_token),
        token_prefix=raw_token[:12],
        email=normalized_email,
        invited_by=user.id,
        project_id=None,
        role=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()

    settings = get_settings()
    invite_link = f"{settings.base_url}/admin/invite/{raw_token}"

    return RedirectResponse(
        url=f"/admin/settings/users?message=Invite+created&invite_link={invite_link}",
        status_code=303,
    )
