# Unified Interview Creation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the public interview link flow with named interview creation so both use the same template/angle resolution logic.

**Architecture:** Add `public_template_id` field to Project. When guests join via public link, create an Interview record with that template_id. This makes public interviews use the same content+style resolution as named interviews (via `get_effective_interview_config` in worker.py).

**Tech Stack:** SQLAlchemy, Alembic migrations, FastAPI, Jinja2 templates

---

## Current State Analysis

### Named Interviews (Admin Panel)
- Created at `/admin/projects/{id}/interviews/new`
- User selects a template OR defines custom content+style
- `Interview.template_id` is set (or inline angle/questions are stored)
- Worker calls `get_effective_interview_config(interview, template)` to resolve content+style

### Public Interviews (Generic Links)
- Created at `/join/{token}/start` when guest enters name
- **Gap:** No template_id is set - interview created with no content/style configuration
- Worker falls back to project-level questions only, no angle

### The Fix
1. Add `public_template_id` to Project model
2. Update public join flow to set `Interview.template_id = project.public_template_id`
3. Add UI to configure which template public links use
4. Public interviews now get the same content+style as named interviews

---

## Task 1: Add public_template_id to Project Model

**Files:**
- Modify: `src/boswell/server/models.py:139-174`
- Create: `src/boswell/server/migrations/versions/XXXX_add_public_template_id.py`

**Step 1: Add the field to Project model**

In `src/boswell/server/models.py`, add after `intro_prompt` field (around line 168):

```python
    # Template to use for public link interviews (content + style)
    public_template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
    )
```

**Step 2: Add relationship**

Add to Project's relationships section (around line 172):

```python
    public_template: Mapped[Optional["InterviewTemplate"]] = relationship(
        "InterviewTemplate", foreign_keys=[public_template_id]
    )
```

**Step 3: Create migration**

```bash
cd /Users/noahraford/Projects/boswell
alembic revision --autogenerate -m "Add public_template_id to projects"
```

**Step 4: Apply migration**

```bash
alembic upgrade head
```

**Step 5: Commit**

```bash
git add src/boswell/server/models.py src/boswell/server/migrations/versions/
git commit -m "feat: add public_template_id field to Project model"
```

---

## Task 2: Update Public Join Flow to Use Template

**Files:**
- Modify: `src/boswell/server/routes/guest.py:529-580`

**Step 1: Update imports**

Add `InterviewTemplate` to imports at line 18:

```python
from boswell.server.models import Interview, InterviewStatus, InterviewTemplate, Project
```

**Step 2: Update start_public_interview to set template_id**

Replace the Interview creation block (lines 557-564) with:

```python
    # Create new Interview record with public template
    interview = Interview(
        project_id=project.id,
        name=guest_name,
        email=None,  # No email for public interviews
        status=InterviewStatus.started,
        started_at=datetime.now(timezone.utc),
        template_id=project.public_template_id,  # Use project's public template
    )
```

**Step 3: Commit**

```bash
git add src/boswell/server/routes/guest.py
git commit -m "feat: public interviews now use project's public_template_id"
```

---

## Task 3: Add Public Template Selection to Project Detail UI

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html:416-452`
- Modify: `src/boswell/server/routes/admin.py`

**Step 1: Update project_detail route to pass templates**

In `src/boswell/server/routes/admin.py`, find the `project_detail` route (search for `@router.get("/projects/{project_id}")`). Add template fetch:

```python
    # Fetch templates for public link configuration
    templates_result = await db.execute(
        select(InterviewTemplate)
        .where(InterviewTemplate.team_id == user.team_id)
        .order_by(InterviewTemplate.name)
    )
    templates = templates_result.scalars().all()
```

Add `templates=templates` to the context dict passed to TemplateResponse.

**Step 2: Update the Public Link Section in project_detail.html**

Replace lines 416-452 (the public link section) with:

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
        <div style="display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem;">
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

        <!-- Interview Type for Public Link -->
        <form method="post" action="/admin/projects/{{ project.id }}/set-public-template" style="display: flex; align-items: center; gap: 0.75rem;">
            <label for="public_template_id" style="font-size: 0.875rem; color: var(--fg-muted); white-space: nowrap;">Interview Type:</label>
            <select name="public_template_id" id="public_template_id" style="flex: 1; max-width: 300px;">
                <option value="">Default (Project questions, Exploratory)</option>
                {% for t in templates %}
                <option value="{{ t.id }}" {% if project.public_template_id == t.id %}selected{% endif %}>
                    {{ t.name }} ({{ t.angle.value|title if t.angle else 'Exploratory' }}{% if t.angle_secondary %} + {{ t.angle_secondary.value|title }}{% endif %})
                </option>
                {% endfor %}
            </select>
            <button type="submit" class="btn btn-outline btn-sm">Save</button>
        </form>

        {% else %}
        <form method="post" action="/admin/projects/{{ project.id }}/generate-public-link">
            <button type="submit" class="btn">Generate Public Link</button>
        </form>
        {% endif %}
    </div>
```

**Step 3: Commit**

```bash
git add src/boswell/server/templates/admin/project_detail.html src/boswell/server/routes/admin.py
git commit -m "feat: add template selection UI for public interview links"
```

---

## Task 4: Add Route to Set Public Template

**Files:**
- Modify: `src/boswell/server/routes/admin.py`

**Step 1: Add the route**

Add after the `disable_public_link` route:

```python
@router.post("/projects/{project_id}/set-public-template")
async def set_public_template(
    request: Request,
    project_id: UUID,
    public_template_id: Optional[str] = Form(None),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """Set the interview template for public links."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Parse and validate template_id
    if public_template_id and public_template_id.strip():
        try:
            template_uuid = UUID(public_template_id)
            # Verify template belongs to team
            template_result = await db.execute(
                select(InterviewTemplate)
                .where(InterviewTemplate.id == template_uuid)
                .where(InterviewTemplate.team_id == user.team_id)
            )
            template = template_result.scalar_one_or_none()
            if template is None:
                raise HTTPException(status_code=404, detail="Template not found")
            project.public_template_id = template_uuid
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid template ID")
    else:
        project.public_template_id = None

    await db.commit()

    return RedirectResponse(
        url=f"/admin/projects/{project_id}",
        status_code=303,
    )
```

**Step 2: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "feat: add route to set public template for projects"
```

---

## Task 5: Add public_template to Project Edit Form

**Files:**
- Modify: `src/boswell/server/templates/admin/project_edit.html`
- Modify: `src/boswell/server/routes/admin.py` (edit project routes)

**Step 1: Find project edit template**

Check if the project edit form exists and update it to include public_template_id selection.

**Step 2: Update route to pass templates**

In the GET route for project edit, add template fetch similar to Task 3.

**Step 3: Add field to edit form**

Add a dropdown for public_template_id selection in the edit form, similar to the interview creation form.

**Step 4: Update POST route to save public_template_id**

Add `public_template_id: Optional[str] = Form(None)` to the edit route signature and save it.

**Step 5: Commit**

```bash
git add src/boswell/server/templates/admin/project_edit.html src/boswell/server/routes/admin.py
git commit -m "feat: add public template selection to project edit form"
```

---

## Task 6: Update Public Welcome Template to Show Interview Type

**Files:**
- Modify: `src/boswell/server/templates/guest/public_welcome.html`
- Modify: `src/boswell/server/routes/guest.py:500-526`

**Step 1: Update public_join_landing to load template**

In `guest.py`, update the `public_join_landing` function to eager-load the public_template:

```python
@router.get("/join/{token}")
async def public_join_landing(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Landing page for public/generic interview links."""
    # Find project by public_link_token, with public_template
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.public_template))
        .where(Project.public_link_token == token)
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

**Step 2: Add relationship import**

Add `selectinload` to imports if not present:

```python
from sqlalchemy.orm import selectinload
```

**Step 3: Update public_welcome.html to show interview style**

Add below the duration badge:

```html
        {% if project.public_template %}
        <div class="duration-badge" style="margin-left: 0.5rem;">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            {{ project.public_template.angle.value|title if project.public_template.angle else 'Exploratory' }} style
        </div>
        {% endif %}
```

**Step 4: Commit**

```bash
git add src/boswell/server/routes/guest.py src/boswell/server/templates/guest/public_welcome.html
git commit -m "feat: show interview style on public welcome page"
```

---

## Task 7: Test End-to-End Flow

**Step 1: Start local server**

```bash
cd /Users/noahraford/Projects/boswell
docker-compose up -d
```

**Step 2: Manual testing checklist**

1. **Create Interview Template:**
   - Go to `/admin/templates/new`
   - Create "Customer Discovery" template with Exploratory angle
   - Create "Expert Challenge" template with Interrogative angle

2. **Configure Public Link:**
   - Go to a project detail page
   - Generate public link (if not exists)
   - Set "Interview Type" to "Expert Challenge"
   - Click Save

3. **Test Public Flow:**
   - Open public link in incognito browser
   - Verify the style badge shows "Interrogative style"
   - Enter name and start interview
   - Verify Boswell uses interrogative approach (challenges claims)

4. **Verify Named Interview Still Works:**
   - Create a named interview with "Customer Discovery" template
   - Start the interview via magic link
   - Verify Boswell uses exploratory approach

5. **Test No Template Case:**
   - Set public template to "Default"
   - Start a public interview
   - Verify Boswell uses project questions with default exploratory style

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found in testing"
```

---

## Task 8: Deploy to Production

**Step 1: Push all changes**

```bash
git push origin master
```

**Step 2: Verify Railway auto-deploys**

Railway should auto-deploy. Watch logs for migration success.

**Step 3: Run production smoke test**

1. Go to production admin
2. Configure a public link template
3. Test the public flow end-to-end

---

## Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Add public_template_id to Project | models.py, migration |
| 2 | Update public join to use template | guest.py |
| 3 | Add template selection UI | project_detail.html, admin.py |
| 4 | Add set-public-template route | admin.py |
| 5 | Add to project edit form | project_edit.html, admin.py |
| 6 | Show style on welcome page | public_welcome.html, guest.py |
| 7 | Test end-to-end | - |
| 8 | Deploy | - |

**Result:** Public interview links and named interviews both use the same template/angle resolution system. Admins can configure which interview type (content + style) is used for public links on a per-project basis.
