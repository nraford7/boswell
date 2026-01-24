# Generic Interview Links Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow projects to have a reusable link that anyone can use to start an interview by entering their name.

**Architecture:** Add `public_link_token` field to Project model. Create new `/join/{token}` routes that show a name-entry welcome screen, then create an Interview record and Daily.co room on-the-fly. The interview is saved with the guest's entered name.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2 templates, Daily.co API, PostgreSQL

---

### Task 1: Add public_link_token to Project Model

**Files:**
- Modify: `src/boswell/server/models.py:109-139`

**Step 1: Add the new field to Project model**

In `src/boswell/server/models.py`, add `public_link_token` field to the Project class:

```python
class Project(Base):
    """Interview project - a topic to interview people about."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        pg_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    team_id: Mapped[UUID] = mapped_column(
        pg_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    template_id: Mapped[Optional[UUID]] = mapped_column(
        pg_UUID(as_uuid=True), ForeignKey("interview_templates.id"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        pg_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # NEW: Public link token for generic interview links
    public_link_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )

    # Relationships
    team: Mapped["Team"] = relationship(back_populates="projects")
    template: Mapped[Optional["InterviewTemplate"]] = relationship()
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
```

**Step 2: Create database migration**

Run:
```bash
cd /Users/noahraford/Projects/boswell
alembic revision --autogenerate -m "Add public_link_token to projects"
```

**Step 3: Apply migration**

Run:
```bash
alembic upgrade head
```

**Step 4: Commit**

```bash
git add src/boswell/server/models.py alembic/versions/
git commit -m "feat: add public_link_token field to Project model"
```

---

### Task 2: Make Interview.email Optional

**Files:**
- Modify: `src/boswell/server/models.py:145-187`

**Step 1: Change email field to nullable**

The Interview model currently requires email. For generic links, guests won't provide email. Change:

```python
# Before:
email: Mapped[str] = mapped_column(String(255), nullable=False)

# After:
email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

**Step 2: Create migration**

Run:
```bash
alembic revision --autogenerate -m "Make interview email optional"
```

**Step 3: Apply migration**

Run:
```bash
alembic upgrade head
```

**Step 4: Commit**

```bash
git add src/boswell/server/models.py alembic/versions/
git commit -m "feat: make Interview.email optional for generic links"
```

---

### Task 3: Update create_daily_room to Accept Guest Name

**Files:**
- Modify: `src/boswell/server/routes/guest.py:25-100`

**Step 1: Add guest_name parameter**

Update the `create_daily_room` function signature and pass the name to Daily.co:

```python
async def create_daily_room(interview_id: str, guest_name: str = "Guest") -> dict:
    """Create a Daily.co room for the interview.

    Args:
        interview_id: The interview UUID (used for room name).
        guest_name: Display name for the guest in the room.

    Returns:
        Dict with room_name, room_url, and room_token.
    """
    settings = get_settings()

    room_name = f"boswell-{interview_id[:8]}"

    async with httpx.AsyncClient() as client:
        # Create room
        room_response = await client.post(
            "https://api.daily.co/v1/rooms",
            headers={"Authorization": f"Bearer {settings.daily_api_key}"},
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

        if room_response.status_code not in (200, 201):
            logger.error(f"Failed to create room: {room_response.text}")
            raise HTTPException(status_code=500, detail="Failed to create interview room")

        room_data = room_response.json()
        room_url = room_data.get("url", f"https://{settings.daily_domain}.daily.co/{room_name}")

        # Create meeting token with guest's name
        token_response = await client.post(
            "https://api.daily.co/v1/meeting-tokens",
            headers={"Authorization": f"Bearer {settings.daily_api_key}"},
            json={
                "properties": {
                    "room_name": room_name,
                    "is_owner": False,
                    "user_name": guest_name,  # Use actual guest name
                }
            },
        )

        if token_response.status_code not in (200, 201):
            logger.error(f"Failed to create token: {token_response.text}")
            raise HTTPException(status_code=500, detail="Failed to create room token")

        token_data = token_response.json()

        return {
            "room_name": room_name,
            "room_url": room_url,
            "room_token": token_data.get("token"),
        }
```

**Step 2: Update existing call site in start_interview**

Find the existing call to `create_daily_room` and pass the interview name:

```python
# In start_interview function, after fetching interview:
room_info = await create_daily_room(str(interview.id), interview.name)
```

**Step 3: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "feat: pass guest name to Daily.co room creation"
```

---

### Task 4: Create Public Join Routes

**Files:**
- Modify: `src/boswell/server/routes/guest.py`

**Step 1: Add imports if needed**

Ensure these imports are present:

```python
from boswell.server.models import Interview, InterviewStatus, Project
```

**Step 2: Add GET /join/{token} route**

Add after the existing guest routes:

```python
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
```

**Step 3: Add POST /join/{token}/start route**

```python
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
```

**Step 4: Add datetime import if needed**

```python
from datetime import datetime, timezone
```

**Step 5: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "feat: add public join routes for generic interview links"
```

---

### Task 5: Create Public Welcome Template

**Files:**
- Create: `src/boswell/server/templates/guest/public_welcome.html`

**Step 1: Create the template**

```html
{% extends "base.html" %}

{% block title %}Join Interview - {{ project.topic }}{% endblock %}

{% block head %}
<style>
    .welcome-container {
        max-width: 480px;
        margin: 0 auto;
        padding: 3rem 1.5rem;
    }

    .welcome-card {
        background: var(--bg-elevated);
        border: 1px solid var(--border);
        border-radius: var(--radius-lg);
        padding: 2.5rem;
        text-align: center;
    }

    .welcome-icon {
        width: 64px;
        height: 64px;
        margin: 0 auto 1.5rem;
        background: var(--accent-subtle);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .welcome-icon svg {
        width: 32px;
        height: 32px;
        color: var(--accent);
    }

    .welcome-title {
        font-family: var(--font-display);
        font-size: 1.75rem;
        font-weight: 400;
        color: var(--fg);
        margin-bottom: 0.5rem;
    }

    .welcome-topic {
        color: var(--accent);
        font-size: 1.125rem;
        margin-bottom: 1.5rem;
    }

    .welcome-description {
        color: var(--fg-muted);
        font-size: 0.9375rem;
        line-height: 1.6;
        margin-bottom: 2rem;
    }

    .name-form {
        text-align: left;
    }

    .name-form label {
        display: block;
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--fg-muted);
        margin-bottom: 0.5rem;
    }

    .name-form input[type="text"] {
        width: 100%;
        font-size: 1.125rem;
        padding: 0.875rem 1rem;
        text-align: center;
    }

    .name-form button {
        width: 100%;
        margin-top: 1.5rem;
        padding: 1rem;
        font-size: 1rem;
    }

    .duration-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.375rem;
        background: var(--bg-surface);
        padding: 0.375rem 0.75rem;
        border-radius: var(--radius-full);
        font-size: 0.8125rem;
        color: var(--fg-dim);
        margin-bottom: 1.5rem;
    }

    .duration-badge svg {
        width: 14px;
        height: 14px;
    }

    .terms-text {
        font-size: 0.75rem;
        color: var(--fg-dim);
        margin-top: 1.5rem;
        line-height: 1.5;
    }

    .terms-text a {
        color: var(--accent);
    }
</style>
{% endblock %}

{% block body %}
<div class="welcome-container">
    <div class="welcome-card">
        <div class="welcome-icon">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
        </div>

        <h1 class="welcome-title">Welcome to Boswell</h1>
        <p class="welcome-topic">{{ project.topic }}</p>

        <div class="duration-badge">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            ~{{ project.target_minutes }} minutes
        </div>

        <p class="welcome-description">
            You're about to have a voice conversation with Boswell, an AI research interviewer.
            Please enter your name to begin.
        </p>

        <form method="post" action="/join/{{ token }}/start" class="name-form">
            <label for="guest_name">Your Name</label>
            <input type="text" id="guest_name" name="guest_name"
                   placeholder="Enter your name"
                   required
                   minlength="2"
                   maxlength="100"
                   autofocus>
            <button type="submit" class="btn">Start Interview</button>
        </form>

        <p class="terms-text">
            By continuing, you agree to have your responses recorded and transcribed
            for research purposes.
        </p>
    </div>
</div>
{% endblock %}
```

**Step 2: Commit**

```bash
git add src/boswell/server/templates/guest/public_welcome.html
git commit -m "feat: add public welcome template for generic interview links"
```

---

### Task 6: Add Admin UI for Generating Public Links

**Files:**
- Modify: `src/boswell/server/routes/admin.py`
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Add route to generate public link token**

In `src/boswell/server/routes/admin.py`, add:

```python
import secrets

@router.post("/projects/{project_id}/generate-public-link")
async def generate_public_link(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Generate or regenerate a public interview link for a project."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

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
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project.public_link_token = None
    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )
```

**Step 2: Update project_detail.html to show public link**

Add after the stats-grid section, before the materials-section:

```html
<!-- Public Link Section -->
<div class="card" style="margin-bottom: 2rem;">
    <div class="section-header">
        <h2>Public Interview Link</h2>
    </div>
    <p style="color: var(--fg-muted); margin-bottom: 1rem; font-size: 0.9375rem;">
        Share this link with anyone to let them start an interview. They'll enter their name and begin immediately.
    </p>

    {% if project.public_link_token %}
    <div style="display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;">
        <div class="invite-link-wrapper" style="flex: 1; min-width: 200px;">
            <input type="text" readonly
                   value="{{ base_url }}/join/{{ project.public_link_token }}"
                   style="font-family: monospace; font-size: 0.8125rem; width: 100%;"
                   id="publicLinkInput">
            <button type="button" class="copy-btn" onclick="copyPublicLink()" title="Copy link">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16">
                    <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/>
                    <path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/>
                </svg>
            </button>
        </div>
        <form method="post" action="/admin/projects/{{ project.id }}/generate-public-link" style="display: inline;">
            <button type="submit" class="btn btn-outline btn-sm">Regenerate</button>
        </form>
        <form method="post" action="/admin/projects/{{ project.id }}/disable-public-link" style="display: inline;"
              onsubmit="return confirm('Disable the public link? Existing links will stop working.');">
            <button type="submit" class="btn btn-outline btn-sm" style="color: #994444; border-color: #994444;">Disable</button>
        </form>
    </div>
    {% else %}
    <form method="post" action="/admin/projects/{{ project.id }}/generate-public-link">
        <button type="submit" class="btn">Generate Public Link</button>
    </form>
    {% endif %}
</div>

<script>
function copyPublicLink() {
    const input = document.getElementById('publicLinkInput');
    input.select();
    navigator.clipboard.writeText(input.value);
    // Visual feedback could be added here
}
</script>
```

**Step 3: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/templates/admin/project_detail.html
git commit -m "feat: add admin UI for generating public interview links"
```

---

### Task 7: Test End-to-End Flow

**Step 1: Start local server**

```bash
cd /Users/noahraford/Projects/boswell
docker-compose up -d
```

**Step 2: Manual testing checklist**

1. Log into admin dashboard
2. Go to a project
3. Click "Generate Public Link"
4. Copy the link
5. Open in incognito/new browser
6. Enter a test name
7. Click "Start Interview"
8. Verify you're in the room with Boswell
9. Verify Boswell greets you by your entered name
10. Complete or exit the interview
11. Check admin dashboard - interview should appear with the guest name

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found in testing"
```

---

### Task 8: Deploy to Railway

**Step 1: Push all changes**

```bash
git push origin master
```

**Step 2: Verify Railway auto-deploys or trigger manually**

```bash
railway up --service web --detach
railway up --service worker --detach
```

**Step 3: Run migrations on production**

Railway should run migrations automatically via start_web.sh. Verify in logs.

**Step 4: Test on production**

1. Go to production admin URL
2. Generate a public link for a project
3. Test the full flow

---

## Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Add public_link_token to Project | models.py, migration |
| 2 | Make Interview.email optional | models.py, migration |
| 3 | Update create_daily_room with guest name | guest.py |
| 4 | Create public join routes | guest.py |
| 5 | Create public welcome template | public_welcome.html |
| 6 | Add admin UI for public links | admin.py, project_detail.html |
| 7 | Test end-to-end | - |
| 8 | Deploy to Railway | - |

**Total estimated tasks:** 8 main tasks with ~25 individual steps
