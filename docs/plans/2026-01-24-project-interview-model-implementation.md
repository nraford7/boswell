# Project vs Interview Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate Project (research container) from Interview (personalized conversation instance), enabling both generic public interviews and highly personalized invite-based interviews.

**Architecture:** Add `name` field to Project, add interview-level context fields, update UI to show project name as title, redesign project creation to not require person info, update voice pipeline to use interview context for personalization.

**Tech Stack:** SQLAlchemy, Alembic, FastAPI, Jinja2, Pipecat

---

## Task 1: Database Migration - Add New Fields

**Files:**
- Create: `migrations/versions/XXXX_add_project_name_and_interview_context.py`
- Modify: `src/boswell/server/models.py:109-145` (Project class)
- Modify: `src/boswell/server/models.py:147-193` (Interview class)

**Step 1: Update Project model**

Add `name` and `research_links` fields to the Project class in `src/boswell/server/models.py`:

```python
class Project(Base):
    """A project containing one or more interviews."""

    __tablename__ = "interviews"  # Keep table name to avoid migration

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # NEW
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # NEW
    target_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # ... rest unchanged
```

**Step 2: Update Interview model**

Add `context_notes` and `context_links` fields to the Interview class:

```python
class Interview(Base):
    """A 1:1 interview with a specific person."""

    __tablename__ = "guests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        "interview_id",
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bio_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    context_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # NEW
    context_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # NEW
    # ... rest unchanged
```

**Step 3: Create Alembic migration**

Run: `cd /Users/noahraford/Projects/boswell && alembic revision --autogenerate -m "add project name and interview context fields"`

**Step 4: Apply migration**

Run: `alembic upgrade head`

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add project name and interview context fields

- Add name and research_links to Project model
- Add context_notes and context_links to Interview model
- Migration to add columns to database

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Update Dashboard to Show Project Name

**Files:**
- Modify: `src/boswell/server/templates/admin/dashboard.html:188-211`

**Step 1: Update project card to show name with topic fallback**

In `dashboard.html`, change the project card title display:

```html
<a href="/admin/projects/{{ project.id }}" class="project-card">
    <div class="project-topic">{{ project.name or project.topic }}</div>
    <div class="project-meta">
        {% if project.name %}
        <span style="color: var(--fg-muted);">{{ project.topic[:60] }}{% if project.topic|length > 60 %}...{% endif %}</span> &middot;
        {% endif %}
        {{ project.target_minutes }} min &middot; Created {{ project.created_at.strftime('%b %d, %Y') }}
    </div>
    <div class="project-stats">
        <div class="project-stat">
            <span class="stat-value">{{ total_interviews }}</span>
            <span class="stat-label">Interviews</span>
        </div>
        <div class="project-stat">
            <span class="stat-value completed">{{ completed }}</span>
            <span class="stat-label">Completed</span>
        </div>
        <div class="project-stat">
            <span class="stat-value pending">{{ pending }}</span>
            <span class="stat-label">Pending</span>
        </div>
    </div>
</a>
```

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: show project name on dashboard cards

Falls back to topic if name not set for backwards compatibility.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Redesign Project Creation Form

**Files:**
- Modify: `src/boswell/server/templates/admin/project_new.html`
- Modify: `src/boswell/server/routes/admin.py:137-276`

**Step 1: Update project_new.html template**

Remove "Interviewee Information" section, add "Name" field to "Project Details":

```html
{% extends "base.html" %}

{% block title %}New Project - Boswell{% endblock %}

{% block head %}
<style>
    .page-header {
        padding-top: 2rem;
        margin-bottom: 2rem;
    }

    .form-card {
        max-width: 680px;
    }

    .form-section {
        margin-bottom: 2rem;
    }

    .form-section-title {
        font-family: var(--font-display);
        font-size: 1.25rem;
        font-weight: 500;
        color: var(--fg);
        margin-bottom: 0.5rem;
    }

    .form-section-desc {
        color: var(--fg-dim);
        font-size: 0.875rem;
        margin-bottom: 1.5rem;
    }

    .form-group {
        margin-bottom: 1.5rem;
    }

    .form-group label {
        display: block;
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--fg);
        margin-bottom: 0.5rem;
    }

    .form-group .required {
        color: var(--accent);
    }

    .form-hint {
        font-size: 0.8125rem;
        color: var(--fg-dim);
        margin-top: 0.5rem;
    }

    .form-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 2rem 0;
    }

    input[type="number"] {
        max-width: 140px;
    }

    .file-upload {
        border: 2px dashed var(--border);
        border-radius: var(--radius-md);
        padding: 1.5rem;
        text-align: center;
        cursor: pointer;
        transition: all var(--transition-fast);
    }

    .file-upload:hover {
        border-color: var(--accent);
        background-color: var(--accent-subtle);
    }

    .file-upload input[type="file"] {
        border: none;
        padding: 0;
        background: transparent;
        text-align: center;
    }

    .file-upload-label {
        display: block;
        color: var(--fg-muted);
        font-size: 0.875rem;
        margin-bottom: 0.5rem;
    }

    .submit-btn {
        width: 100%;
        padding: 1rem 1.5rem;
        font-size: 1rem;
    }
</style>
{% endblock %}

{% block body %}
<nav class="nav">
    <div class="nav-content">
        <a href="/admin/" class="nav-brand">Boswell x EMIR</a>
        <div class="nav-links">
            <a href="/admin/">Projects</a>
            <a href="/admin/templates">Interview Types</a>
            <span class="text-muted">{{ user.name }}</span>
            <form method="post" action="/admin/logout" style="display: inline;">
                <button type="submit">Logout</button>
            </form>
        </div>
    </div>
</nav>

<div class="container">
    <div class="page-header">
        <a href="/admin/" class="back-link">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8z"/>
            </svg>
            Back to Dashboard
        </a>
    </div>

    <div class="card form-card">
        <h1 style="font-family: var(--font-display); font-size: 2rem; font-weight: 400; margin-bottom: 2rem;">New Project</h1>

        <form method="post" action="/admin/projects/new" enctype="multipart/form-data">
            <div class="form-section">
                <h3 class="form-section-title">Project Details</h3>
                <p class="form-section-desc">Define your research project.</p>

                <div class="form-group">
                    <label for="name">Project Name <span class="required">*</span></label>
                    <input type="text" id="name" name="name" required placeholder="Q1 Customer Research">
                    <p class="form-hint">A short, memorable name for this project.</p>
                </div>

                <div class="form-group">
                    <label for="topic">Research Topic / Intent <span class="required">*</span></label>
                    <textarea id="topic" name="topic" required rows="3" placeholder="Understanding customer pain points with onboarding and identifying opportunities for improvement."></textarea>
                    <p class="form-hint">Describe the purpose and goals of this research.</p>
                </div>

                <div class="form-group">
                    <label for="template_id">Interview Type</label>
                    <select id="template_id" name="template_id">
                        <option value="">No interview type</option>
                        {% for template in templates %}
                        <option value="{{ template.id }}">{{ template.name }}</option>
                        {% endfor %}
                    </select>
                    <p class="form-hint">Optional: Select an interview type to pre-configure settings.</p>
                </div>

                <div class="form-group">
                    <label for="target_minutes">Target Duration (minutes)</label>
                    <input type="number" id="target_minutes" name="target_minutes" value="30" min="5" max="120" required>
                    <p class="form-hint">The target length for interviews (5-120 minutes).</p>
                </div>
            </div>

            <hr class="form-divider">

            <div class="form-section">
                <h3 class="form-section-title">Research Materials</h3>
                <p class="form-section-desc">Optional: Give Boswell background information for all interviews in this project.</p>

                <div class="form-group">
                    <label for="research_files">Upload Documents</label>
                    <div class="file-upload">
                        <span class="file-upload-label">PDFs, text files, markdown</span>
                        <input type="file" id="research_files" name="research_files" multiple accept=".pdf,.txt,.md,.doc,.docx">
                    </div>
                    <p class="form-hint">Briefings, research notes, industry background.</p>
                </div>

                <div class="form-group">
                    <label for="research_urls">Web Links</label>
                    <textarea id="research_urls" name="research_urls" rows="3" placeholder="https://example.com/industry-report&#10;https://example.com/topic-background&#10;(one URL per line)"></textarea>
                    <p class="form-hint">URLs to scrape for research context.</p>
                </div>
            </div>

            <button type="submit" class="btn submit-btn">Create Project</button>
        </form>
    </div>
</div>
{% endblock %}
```

**Step 2: Update project_new_submit route**

Modify `src/boswell/server/routes/admin.py` to handle new form (no guest info):

```python
@router.post("/projects/new")
async def project_new_submit(
    request: Request,
    user: User = Depends(require_auth),
    name: str = Form(...),
    topic: str = Form(...),
    template_id: Optional[str] = Form(None),
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

    # Parse template_id if provided
    parsed_template_id: Optional[UUID] = None
    if template_id and template_id.strip():
        try:
            parsed_template_id = UUID(template_id)
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
    research_links = []
    questions = None

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
                        research_parts.append(f"=== Document: {upload_file.filename} ===\n{doc_content}")

                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to process file {upload_file.filename}: {e}")

    # Process URLs
    if research_urls and INGESTION_AVAILABLE:
        urls = [u.strip() for u in research_urls.split("\n") if u.strip()]
        for url in urls:
            if url.startswith("http://") or url.startswith("https://"):
                research_links.append(url)
                try:
                    url_content = await asyncio.to_thread(fetch_url, url)
                    if url_content:
                        research_parts.append(f"=== URL: {url} ===\n{url_content}")
                except Exception as e:
                    logger.warning(f"Failed to fetch URL {url}: {e}")

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

    # Create the project (no interview)
    project = Project(
        team_id=user.team_id,
        template_id=parsed_template_id,
        name=name,
        topic=topic,
        target_minutes=target_minutes,
        created_by=user.id,
        research_summary=research_summary,
        research_links=research_links if research_links else None,
        questions=questions,
    )
    db.add(project)
    await db.flush()

    # Redirect to project detail page
    return RedirectResponse(
        url=f"/admin/projects/{project.id}",
        status_code=303,
    )
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: redesign project creation form

- Remove interviewee fields from project creation
- Add project name field
- Project creation now creates just the project container
- Interviews are added separately via Add Interview button

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Update Project Detail Page

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html:363-368`

**Step 1: Show project name as title, topic as subtitle**

Update the header section:

```html
<h1 class="page-title">{{ project.name or project.topic }}</h1>
<p class="page-subtitle">
    {% if project.name %}
    {{ project.topic[:100] }}{% if project.topic|length > 100 %}...{% endif %} &middot;
    {% endif %}
    {{ project.target_minutes }} min target
    {% if project.template %} &middot; {{ project.template.name }}{% endif %}
    &middot; Created {{ project.created_at.strftime('%b %d, %Y') }}
</p>
```

**Step 2: Update page title in head**

```html
{% block title %}{{ project.name or project.topic }} - Boswell{% endblock %}
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: show project name in detail page header

- Name as main title, topic shown as subtitle
- Falls back to topic if name not set

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Update Project Edit Form

**Files:**
- Modify: `src/boswell/server/templates/admin/project_edit.html`
- Modify: `src/boswell/server/routes/admin.py:1180-1257`

**Step 1: Add name field to edit form**

Update `project_edit.html`:

```html
{% extends "base.html" %}

{% block title %}Edit {{ project.name or project.topic }} - Boswell{% endblock %}

{% block head %}
<style>
    .page-header {
        padding-top: 2rem;
        margin-bottom: 2rem;
    }

    .page-title {
        font-family: var(--font-display);
        font-size: 2rem;
        font-weight: 400;
        color: var(--fg);
        margin-bottom: 0.25rem;
    }

    .form-section {
        margin-bottom: 2rem;
    }

    .form-section h3 {
        font-size: 0.875rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--fg-dim);
        margin-bottom: 0.75rem;
    }

    .form-section p.help-text {
        font-size: 0.8125rem;
        color: var(--fg-dim);
        margin-top: 0.5rem;
    }

    textarea {
        min-height: 150px;
        font-family: inherit;
        line-height: 1.6;
    }

    textarea.questions-input {
        min-height: 250px;
        font-family: 'SF Mono', 'Fira Code', 'Monaco', monospace;
        font-size: 0.875rem;
    }

    .btn-group {
        display: flex;
        gap: 1rem;
        margin-top: 2rem;
    }
</style>
{% endblock %}

{% block body %}
<nav class="nav">
    <div class="nav-content">
        <a href="/admin/" class="nav-brand">Boswell x EMIR</a>
        <div class="nav-links">
            <a href="/admin/">Projects</a>
            <a href="/admin/templates">Interview Types</a>
            <span class="text-muted">{{ user.name }}</span>
            <form method="post" action="/admin/logout" style="display: inline;">
                <button type="submit">Logout</button>
            </form>
        </div>
    </div>
</nav>

<div class="container">
    <div class="page-header">
        <a href="/admin/projects/{{ project.id }}" class="back-link">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8z"/>
            </svg>
            Back to Project
        </a>
        <h1 class="page-title">Edit Project</h1>
    </div>

    <div class="card">
        <form method="post" action="/admin/projects/{{ project.id }}/edit">
            <div class="form-section">
                <h3>Project Name</h3>
                <input type="text" name="name" value="{{ project.name or '' }}" required
                       placeholder="e.g., Q1 Customer Research">
                <p class="help-text">A short, memorable name for this project.</p>
            </div>

            <div class="form-section">
                <h3>Research Topic / Intent</h3>
                <textarea name="topic" required placeholder="Describe the purpose and intent of this research...">{{ project.topic }}</textarea>
                <p class="help-text">The research goals and what you want to learn.</p>
            </div>

            <div class="form-section">
                <h3>Research Summary</h3>
                <textarea name="research_summary" placeholder="Paste or type background research, context, or materials for the AI interviewer to reference...">{{ project.research_summary or '' }}</textarea>
                <p class="help-text">This summary helps Boswell understand the context and ask more informed questions.</p>
            </div>

            <div class="form-section">
                <h3>Interview Questions</h3>
                <textarea name="questions_text" class="questions-input" placeholder="Enter one question per line...">{{ questions_text }}</textarea>
                <p class="help-text">Enter one question per line. These serve as a guide for Boswell - the AI will follow interesting threads naturally.</p>
            </div>

            <div class="btn-group">
                <button type="submit" class="btn">Save Changes</button>
                <a href="/admin/projects/{{ project.id }}" class="btn btn-outline">Cancel</a>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

**Step 2: Update edit route to handle name field**

```python
@router.post("/projects/{project_id}/edit")
async def edit_project(
    request: Request,
    project_id: UUID,
    name: str = Form(...),
    topic: str = Form(...),
    research_summary: str = Form(""),
    questions_text: str = Form(""),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Save project edits."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update fields
    project.name = name.strip()
    project.topic = topic.strip()
    project.research_summary = research_summary.strip() if research_summary.strip() else None

    # Parse questions (one per line)
    if questions_text.strip():
        questions_lines = [q.strip() for q in questions_text.strip().split("\n") if q.strip()]
        project.questions = {"questions": [{"text": q} for q in questions_lines]}
    else:
        project.questions = None

    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add name field to project edit form

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Create Interview Creation Form

**Files:**
- Create: `src/boswell/server/templates/admin/interview_new.html`
- Modify: `src/boswell/server/routes/admin.py` (add new routes)

**Step 1: Create interview_new.html template**

```html
{% extends "base.html" %}

{% block title %}Add Interview - {{ project.name or project.topic }} - Boswell{% endblock %}

{% block head %}
<style>
    .page-header {
        padding-top: 2rem;
        margin-bottom: 2rem;
    }

    .page-title {
        font-family: var(--font-display);
        font-size: 2rem;
        font-weight: 400;
        color: var(--fg);
        margin-bottom: 0.25rem;
    }

    .page-subtitle {
        color: var(--fg-dim);
        font-size: 0.875rem;
    }

    .form-card {
        max-width: 680px;
    }

    .form-section {
        margin-bottom: 2rem;
    }

    .form-section-title {
        font-family: var(--font-display);
        font-size: 1.25rem;
        font-weight: 500;
        color: var(--fg);
        margin-bottom: 0.5rem;
    }

    .form-section-desc {
        color: var(--fg-dim);
        font-size: 0.875rem;
        margin-bottom: 1.5rem;
    }

    .form-group {
        margin-bottom: 1.5rem;
    }

    .form-group label {
        display: block;
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--fg);
        margin-bottom: 0.5rem;
    }

    .form-group .required {
        color: var(--accent);
    }

    .form-hint {
        font-size: 0.8125rem;
        color: var(--fg-dim);
        margin-top: 0.5rem;
    }

    .form-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 2rem 0;
    }

    .file-upload {
        border: 2px dashed var(--border);
        border-radius: var(--radius-md);
        padding: 1.5rem;
        text-align: center;
        cursor: pointer;
        transition: all var(--transition-fast);
    }

    .file-upload:hover {
        border-color: var(--accent);
        background-color: var(--accent-subtle);
    }

    .file-upload input[type="file"] {
        border: none;
        padding: 0;
        background: transparent;
        text-align: center;
    }

    .file-upload-label {
        display: block;
        color: var(--fg-muted);
        font-size: 0.875rem;
        margin-bottom: 0.5rem;
    }

    .btn-group {
        display: flex;
        gap: 1rem;
        margin-top: 2rem;
    }

    .submit-btn {
        padding: 1rem 1.5rem;
        font-size: 1rem;
    }
</style>
{% endblock %}

{% block body %}
<nav class="nav">
    <div class="nav-content">
        <a href="/admin/" class="nav-brand">Boswell x EMIR</a>
        <div class="nav-links">
            <a href="/admin/">Projects</a>
            <a href="/admin/templates">Interview Types</a>
            <span class="text-muted">{{ user.name }}</span>
            <form method="post" action="/admin/logout" style="display: inline;">
                <button type="submit">Logout</button>
            </form>
        </div>
    </div>
</nav>

<div class="container">
    <div class="page-header">
        <a href="/admin/projects/{{ project.id }}" class="back-link">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8z"/>
            </svg>
            Back to Project
        </a>
        <h1 class="page-title">Add Interview</h1>
        <p class="page-subtitle">{{ project.name or project.topic }}</p>
    </div>

    <div class="card form-card">
        <form method="post" action="/admin/projects/{{ project.id }}/interviews/new" enctype="multipart/form-data">
            <div class="form-section">
                <h3 class="form-section-title">Interviewee</h3>
                <p class="form-section-desc">Who will be interviewed?</p>

                <div class="form-group">
                    <label for="name">Name <span class="required">*</span></label>
                    <input type="text" id="name" name="name" required placeholder="Steve Johnson">
                </div>

                <div class="form-group">
                    <label for="email">Email</label>
                    <input type="email" id="email" name="email" placeholder="steve@example.com">
                    <p class="form-hint">Optional. Required if you want to send an invitation email.</p>
                </div>
            </div>

            <hr class="form-divider">

            <div class="form-section">
                <h3 class="form-section-title">Background on This Person</h3>
                <p class="form-section-desc">Optional: Give Boswell context about this specific interviewee to personalize the conversation.</p>

                <div class="form-group">
                    <label for="context_notes">Notes</label>
                    <textarea id="context_notes" name="context_notes" rows="4" placeholder="VP of Operations at WidgetCorp, manufacturing industry. Been a customer for 2 years. Previously mentioned challenges with integration complexity."></textarea>
                    <p class="form-hint">Background, role, company, previous interactions, areas of interest.</p>
                </div>

                <div class="form-group">
                    <label for="context_urls">Links</label>
                    <textarea id="context_urls" name="context_urls" rows="3" placeholder="https://linkedin.com/in/stevejohnson&#10;https://widgetcorp.com/about&#10;(one URL per line)"></textarea>
                    <p class="form-hint">LinkedIn, company page, articles they've written.</p>
                </div>

                <div class="form-group">
                    <label for="context_files">Documents</label>
                    <div class="file-upload">
                        <span class="file-upload-label">PDFs, text files, notes</span>
                        <input type="file" id="context_files" name="context_files" multiple accept=".pdf,.txt,.md,.doc,.docx">
                    </div>
                    <p class="form-hint">Bio, previous meeting notes, relevant documents.</p>
                </div>
            </div>

            <div class="btn-group">
                <button type="submit" name="action" value="create" class="btn submit-btn">Create Interview</button>
                <button type="submit" name="action" value="create_and_invite" class="btn submit-btn btn-outline">Create & Send Invite</button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

**Step 2: Add routes for interview creation**

Add to `admin.py`:

```python
@router.get("/projects/{project_id}/interviews/new")
async def interview_new_form(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the new interview form for a project."""
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
        name="admin/interview_new.html",
        context={
            "user": user,
            "project": project,
        },
    )


@router.post("/projects/{project_id}/interviews/new")
async def interview_new_submit(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    name: str = Form(...),
    email: Optional[str] = Form(None),
    context_notes: Optional[str] = Form(None),
    context_urls: Optional[str] = Form(None),
    context_files: list[UploadFile] = File(default=[]),
    action: str = Form("create"),
    db: AsyncSession = Depends(get_session),
):
    """Create a new interview for a project."""
    # Fetch project
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate name
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Clean email
    email = email.strip().lower() if email else None

    # Process context materials
    context_parts = []
    context_links = []

    # Process context notes
    if context_notes and context_notes.strip():
        context_parts.append(context_notes.strip())

    # Process context URLs
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

    # Process context files
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

    # Combine context
    combined_context = "\n\n".join(context_parts) if context_parts else None

    # Create interview
    interview = Interview(
        project_id=project_id,
        name=name,
        email=email,
        context_notes=combined_context,
        context_links=context_links if context_links else None,
    )
    db.add(interview)
    await db.flush()

    # Send invitation email if requested
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
```

**Step 3: Update project detail "Add Interview" link**

In `project_detail.html`, change the Add Interview link:

```html
<a href="/admin/projects/{{ project.id }}/interviews/new" class="btn">
```

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: add interview creation form with personalization

- New form for adding interviews to a project
- Supports name, email, context notes, links, and files
- Option to send invitation email on create
- Context materials are processed and stored

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Update Voice Pipeline to Use Interview Context

**Files:**
- Modify: `src/boswell/voice/prompts.py:4-93`
- Modify: `src/boswell/server/worker.py:55-129`

**Step 1: Update build_system_prompt to accept interview context**

```python
def build_system_prompt(
    topic: str,
    questions: list[str],
    research_summary: str | None = None,
    interview_context: str | None = None,
    interviewee_name: str | None = None,
    target_minutes: int = 30,
    max_minutes: int = 45,
) -> str:
    """Build the system prompt for Claude.

    Args:
        topic: Interview topic.
        questions: List of prepared interview questions.
        research_summary: Optional project-level research summary.
        interview_context: Optional interview-level context about this specific person.
        interviewee_name: Name of the person being interviewed.
        target_minutes: Target interview length in minutes.
        max_minutes: Maximum interview length in minutes.

    Returns:
        System prompt string for Claude.
    """
    questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

    research_section = ""
    if research_summary:
        research_section = f"""
PROJECT RESEARCH:
{research_summary}

"""

    interview_context_section = ""
    if interview_context:
        interview_context_section = f"""
ABOUT THIS INTERVIEWEE ({interviewee_name or 'Guest'}):
{interview_context}

PERSONALIZATION INSTRUCTIONS:
- Use the interviewee's background to make questions more relevant to their experience
- Reference their role, company, or industry when appropriate
- Build on any previous interactions or known interests
- Tailor your language and examples to their context

"""

    return f"""You are Boswell, a skilled AI research interviewer conducting an interview about: {topic}

INTERVIEW STYLE:
- Warm, curious, and intellectually engaged like an NPR interviewer
- Ask open-ended questions that invite detailed, thoughtful responses
- Listen actively and follow interesting threads that emerge
- Be conversational and natural, not robotic or scripted
- Use the guest's name ({interviewee_name or 'Guest'}) occasionally

IMPORTANT - QUESTION FORMAT:
- Ask ONE question at a time
- Never include sub-questions (no "and also..." or "what about...")
- Never provide examples in your questions (no "like X or Y")
- Wait for the guest to fully answer before asking the next question

IMMEDIATE ACKNOWLEDGMENTS:
- After the guest finishes speaking, immediately respond with a brief acknowledgment (1-3 words)
- Examples: "Mm-hmm.", "I see.", "Right.", "Interesting.", "Got it.", "Yes."
- This shows you're listening and gives you a moment to formulate your next question
- Then follow with your substantive response or next question

{research_section}{interview_context_section}PREPARED QUESTIONS (use as a guide, personalize based on interviewee context):
{questions_text}

GUIDELINES:
- Target interview length: {target_minutes} minutes
- Maximum time: {max_minutes} minutes
- Check in with the guest every 4-5 questions ("How are we doing on time?")
- If they go off-topic but it's interesting, follow that thread briefly
- If they seem uncomfortable with a question, gracefully move on

STRIKING FROM THE RECORD:
If the guest says "nevermind", "forget that", "strike that", "don't include that", or similar:
- Immediately acknowledge with something like "Of course, that's struck from the record."
- Include [STRIKE] in your response - this marks the previous exchange for removal
- Don't dwell on it or ask what specifically they want removed - just acknowledge and move on naturally
- Example: "Absolutely, that's removed. [STRIKE] So, where were we..."

SPEECH SPEED CONTROL:
If the guest asks you to speak slower or faster, acknowledge their request and include a speed tag in your response.
- For "slow down" / "speak slower": Include [SPEED:slower] or [SPEED:slow] in your response
- For "speed up" / "talk faster": Include [SPEED:fast] or [SPEED:faster] in your response
- For "normal speed": Include [SPEED:normal] in your response
- Place the tag anywhere in your response - it will be automatically removed before speaking
- Example: "Of course, I'll slow down. [SPEED:slower] Now, let me ask you about..."

WRAPPING UP:
- Thank the guest briefly for their time
- Ask ONE time if there's anything else they'd like to add
- After they respond, immediately say goodbye and tell them they can close the window
- Do not drag out the ending with multiple thanks or extended pleasantries

RESPONSE FORMAT:
- Keep responses concise and natural for spoken conversation
- Avoid long monologues - this is a dialogue
- Don't use bullet points or numbered lists when speaking
- Don't use markdown formatting
- Speak as you would in a real conversation

Remember: The prepared questions are a guide, not a script. Personalize them based on what you know about this specific interviewee. Your goal is to have a genuine, insightful conversation."""
```

**Step 2: Update worker to pass interview context**

In `worker.py`, update `start_voice_interview`:

```python
async def start_voice_interview(
    interview: Interview,
    project: Project,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """Start a voice interview.

    Args:
        interview: The Interview model instance with room_name and room_token.
        project: The Project model instance with topic and questions.

    Returns:
        Tuple of (transcript entries, conversation history).

    Raises:
        ValueError: If interview is missing room credentials.
        RuntimeError: If the pipeline fails to start.
    """
    if not interview.room_name:
        raise ValueError(f"Interview {interview.id} has no room_name")

    room_url = f"https://emirbot.daily.co/{interview.room_name}"
    room_token = interview.room_token or ""

    # Extract questions from project
    questions = _extract_questions_list(project)
    if not questions:
        logger.warning(
            f"Project {project.id} has no questions, using default greeting"
        )
        questions = [
            "Can you tell me a bit about yourself and your background?",
            "What brings you to this interview today?",
            "Is there anything specific you'd like to discuss?",
        ]

    # Get guest name and context
    guest_name = getattr(interview, 'name', None) or "Guest"
    interview_context = getattr(interview, 'context_notes', None)

    # Build the system prompt with interview context
    system_prompt = build_system_prompt(
        topic=project.topic,
        questions=questions,
        research_summary=project.research_summary,
        interview_context=interview_context,
        interviewee_name=guest_name,
        target_minutes=project.target_minutes,
        max_minutes=project.target_minutes + 15,
    )

    logger.info(
        f"Starting voice interview {interview.id} "
        f"(room={interview.room_name}, topic='{project.topic}', guest='{guest_name}')"
    )

    # Run the Pipecat pipeline
    transcript_entries, conversation_history = await run_interview(
        room_url=room_url,
        room_token=room_token,
        system_prompt=system_prompt,
        bot_name="Boswell",
        guest_name=guest_name,
    )

    logger.info(
        f"Interview completed for {interview.id}: "
        f"{len(transcript_entries)} transcript entries"
    )

    return transcript_entries, conversation_history
```

**Step 3: Update InterviewData class to include context_notes**

In `run_interview_task`:

```python
class InterviewData:
    def __init__(self, id, room_name, room_token, name, context_notes):
        self.id = id
        self.room_name = room_name
        self.room_token = room_token
        self.name = name
        self.context_notes = context_notes

interview_data = InterviewData(
    interview_id,
    room_name,
    room_token,
    guest_name,
    getattr(interview, 'context_notes', None)
)
```

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: use interview context for personalized questions

- build_system_prompt now accepts interview_context parameter
- Worker passes interview.context_notes to prompt builder
- Boswell personalizes questions based on interviewee background

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Update Invite Flow to Use New Interview Form

**Files:**
- Modify: `src/boswell/server/templates/admin/invite.html`
- Modify: `src/boswell/server/routes/admin.py:606-734`

**Step 1: Redirect invite route to new interview form**

The current `/projects/{id}/invite` page allows adding interviews. We should redirect it to the new interview form or update it to support context fields.

Option: Keep invite.html for bulk CSV import only, single invites go through interview_new.html.

Update `invite_form` route in admin.py:

```python
@router.get("/projects/{project_id}/invite")
async def invite_form(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Show the bulk invite form for a project."""
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
```

**Step 2: Update invite.html for bulk import only**

Remove single-invite fields, keep CSV upload:

```html
{% extends "base.html" %}

{% block title %}Bulk Import - {{ project.name or project.topic }} - Boswell{% endblock %}

{% block head %}
<style>
    .page-header { padding-top: 2rem; margin-bottom: 2rem; }
    .page-title { font-family: var(--font-display); font-size: 2rem; font-weight: 400; color: var(--fg); margin-bottom: 0.25rem; }
    .page-subtitle { color: var(--fg-dim); font-size: 0.875rem; }
    .form-card { max-width: 600px; }
    .form-section { margin-bottom: 2rem; }
    .form-hint { font-size: 0.8125rem; color: var(--fg-dim); margin-top: 0.5rem; }
    .file-upload { border: 2px dashed var(--border); border-radius: var(--radius-md); padding: 2rem; text-align: center; cursor: pointer; transition: all var(--transition-fast); }
    .file-upload:hover { border-color: var(--accent); background-color: var(--accent-subtle); }
</style>
{% endblock %}

{% block body %}
<nav class="nav">
    <div class="nav-content">
        <a href="/admin/" class="nav-brand">Boswell x EMIR</a>
        <div class="nav-links">
            <a href="/admin/">Projects</a>
            <a href="/admin/templates">Interview Types</a>
            <span class="text-muted">{{ user.name }}</span>
            <form method="post" action="/admin/logout" style="display: inline;">
                <button type="submit">Logout</button>
            </form>
        </div>
    </div>
</nav>

<div class="container">
    <div class="page-header">
        <a href="/admin/projects/{{ project.id }}" class="back-link">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                <path fill-rule="evenodd" d="M15 8a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 0 0 .708-.708L2.707 8.5H14.5A.5.5 0 0 0 15 8z"/>
            </svg>
            Back to Project
        </a>
        <h1 class="page-title">Bulk Import Interviews</h1>
        <p class="page-subtitle">{{ project.name or project.topic }}</p>
    </div>

    <div class="card form-card">
        <div class="form-section">
            <p style="margin-bottom: 1rem;">Upload a CSV file to import multiple interviews at once. The CSV should have columns:</p>
            <ul style="margin-left: 1.5rem; margin-bottom: 1rem; color: var(--fg-muted);">
                <li><strong>email</strong> (required) - Interviewee email address</li>
                <li><strong>name</strong> (optional) - Interviewee name</li>
            </ul>
            <p class="form-hint">For single interviews with personalization, use <a href="/admin/projects/{{ project.id }}/interviews/new">Add Interview</a> instead.</p>
        </div>

        <form method="post" action="/admin/projects/{{ project.id }}/invite" enctype="multipart/form-data">
            <div class="form-section">
                <div class="file-upload">
                    <span style="display: block; color: var(--fg-muted); margin-bottom: 0.5rem;">Upload CSV File</span>
                    <input type="file" name="csv_file" accept=".csv" required>
                </div>
            </div>

            <button type="submit" class="btn" style="width: 100%;">Import & Send Invitations</button>
        </form>
    </div>
</div>
{% endblock %}
```

**Step 3: Update invite_submit to only handle CSV**

```python
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
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

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

    # Send invitation emails
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
```

**Step 4: Add "Bulk Import" link to project detail page**

Update project_detail.html, add a link next to "Add Interview":

```html
<div style="display: flex; align-items: center; gap: 1rem;">
    <a href="/admin/projects/{{ project.id }}/interviews/new" class="btn">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
            <path d="M8 4a.5.5 0 0 1 .5.5v3h3a.5.5 0 0 1 0 1h-3v3a.5.5 0 0 1-1 0v-3h-3a.5.5 0 0 1 0-1h3v-3A.5.5 0 0 1 8 4z"/>
        </svg>
        Add Interview
    </a>
    <a href="/admin/projects/{{ project.id }}/invite" class="btn btn-outline">Bulk Import</a>
</div>
```

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: separate single interview creation from bulk import

- invite.html now only handles CSV bulk import
- Single interviews use new interview_new.html form
- Add Bulk Import link to project detail page

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Deploy and Test

**Step 1: Push changes**

```bash
git push origin master
```

**Step 2: Deploy to Railway**

```bash
railway up --detach
```

**Step 3: Test the flow**

Manual testing checklist:
1. Create new project (without interviewee info)
2. Verify dashboard shows project name
3. Add interview with personalization context
4. Verify interview context appears in voice session
5. Test public link flow still works
6. Test bulk CSV import still works

**Step 4: Commit any fixes**

If issues found, fix and commit.

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Database migration - add name, research_links, context_notes, context_links |
| 2 | Dashboard shows project name instead of topic |
| 3 | Redesign project creation form (no person info) |
| 4 | Project detail shows name as title |
| 5 | Project edit form includes name field |
| 6 | New interview creation form with personalization |
| 7 | Voice pipeline uses interview context |
| 8 | Separate bulk import from single interview creation |
| 9 | Deploy and test |
