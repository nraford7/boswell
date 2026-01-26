# Project Template-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make template selection happen at project creation, so templates drive content (questions, research) and style (angle) for ALL interviews in that project.

**Architecture:** Add `template_id` to Project (rename `public_template_id`). When creating a project, user selects a template first. The template's questions and angle are used as the project's default. The worker then uses template content instead of only project-generated questions.

**Tech Stack:** SQLAlchemy, Alembic migrations, FastAPI, Jinja2 templates

---

## Problem Analysis

### Current Flow (Broken)
1. User creates project → questions auto-generated from topic description
2. User can set `public_template_id` for public links
3. Worker always uses `project.questions` (the auto-generated ones)
4. Template's questions are resolved in `config["questions"]` but **never used**

### Desired Flow
1. User creates project → selects Interview Type (template) first
2. Template's questions, research, and angle become the project defaults
3. **All interviews** (public and named) use the template's content
4. Worker uses template questions when available, falls back to project questions

---

## Data Model Changes

### Rename Field
- Rename `Project.public_template_id` → `Project.template_id` (simpler, clearer intent)
- This is the project's default template for all interviews

### No Schema Migration Needed
- We already have `public_template_id` in the database
- We'll rename the model field but keep the column name for now (avoid migration)
- Later cleanup can rename the column if desired

---

## Task 1: Rename public_template_id to template_id in Model

**Files:**
- Modify: `src/boswell/server/models.py:170-181`

**Step 1: Update field name in Project model**

Change the field from `public_template_id` to `template_id` while keeping the same column:

```python
# Before (lines 170-172):
public_template_id: Mapped[Optional[UUID]] = mapped_column(
    ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
)

# After:
template_id: Mapped[Optional[UUID]] = mapped_column(
    "public_template_id",  # Keep existing column name to avoid migration
    ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True
)
```

**Step 2: Update relationship name**

```python
# Before (lines 179-181):
public_template: Mapped[Optional["InterviewTemplate"]] = relationship(
    "InterviewTemplate", foreign_keys=[public_template_id]
)

# After:
template: Mapped[Optional["InterviewTemplate"]] = relationship(
    "InterviewTemplate", foreign_keys=[template_id]
)
```

**Step 3: Commit**

```bash
git add src/boswell/server/models.py
git commit -m "refactor: rename public_template_id to template_id in Project model"
```

---

## Task 2: Update All References to public_template_id

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (multiple locations)
- Modify: `src/boswell/server/routes/guest.py`
- Modify: `src/boswell/server/templates/admin/project_detail.html`
- Modify: `src/boswell/server/templates/admin/project_edit.html`
- Modify: `src/boswell/server/templates/guest/public_welcome.html`

**Step 1: Update admin.py**

Search and replace all occurrences:
- `public_template_id` → `template_id`
- `public_template` → `template` (in relationship access)
- Route name `set-public-template` → `set-template` (cleaner)

**Step 2: Update guest.py**

- `Project.public_template` → `Project.template`
- `project.public_template_id` → `project.template_id`

**Step 3: Update project_detail.html**

- `public_template_id` → `template_id`
- Update section title from "Public Interview Link" template dropdown to something like "Default Interview Type"

**Step 4: Update project_edit.html**

- `public_template_id` → `template_id`
- Update label from "Public Link Interview Type" to "Default Interview Type"

**Step 5: Update public_welcome.html**

- `project.public_template` → `project.template`

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename public_template references to template"
```

---

## Task 3: Add Template Selection to Project Creation Form

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (project_new_form and project_new_submit)
- Modify: `src/boswell/server/templates/admin/project_new.html`

**Step 1: Update project_new_form GET route**

Find `@router.get("/projects/new")` and add template fetching:

```python
# Fetch templates for selection
templates_result = await db.execute(
    select(InterviewTemplate)
    .where(InterviewTemplate.team_id == user.team_id)
    .order_by(InterviewTemplate.name)
)
templates = templates_result.scalars().all()
```

Pass `templates=templates` to the template context.

**Step 2: Update project_new_submit POST route**

Add parameter:
```python
template_id: Optional[str] = Form(None),
```

Before creating the project, parse and set template_id:
```python
# Handle template_id
parsed_template_id = None
if template_id and template_id.strip():
    try:
        template_uuid = UUID(template_id)
        # Verify template belongs to team
        template_result = await db.execute(
            select(InterviewTemplate)
            .where(InterviewTemplate.id == template_uuid)
            .where(InterviewTemplate.team_id == user.team_id)
        )
        if template_result.scalar_one_or_none() is not None:
            parsed_template_id = template_uuid
    except ValueError:
        pass  # Invalid UUID, ignore
```

Add `template_id=parsed_template_id` to Project creation.

**Step 3: Update project_new.html**

Add Interview Type selection as the FIRST section (before Project Details):

```html
<div class="form-section">
    <h3 class="form-section-title">Interview Type</h3>
    <p class="form-section-desc">Choose the interview style and questions to use.</p>

    <div class="form-group">
        <label for="template_id">Template</label>
        <select name="template_id" id="template_id">
            <option value="">Custom (generate questions from topic)</option>
            {% for t in templates %}
            <option value="{{ t.id }}">
                {{ t.name }} ({{ t.angle.value|title if t.angle else 'Exploratory' }}{% if t.angle_secondary %} + {{ t.angle_secondary.value|title }}{% endif %})
            </option>
            {% endfor %}
        </select>
        <p class="form-hint">Select a template to use its questions and interview style. Or choose "Custom" to generate questions from your topic description.</p>
    </div>
</div>

<hr class="form-divider">
```

**Step 4: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/templates/admin/project_new.html
git commit -m "feat: add template selection to project creation form"
```

---

## Task 4: Update Worker to Use Template Questions

**Files:**
- Modify: `src/boswell/server/worker.py:115-150`

**Step 1: Modify question extraction logic**

The current code extracts questions only from project. We need to prefer template questions when available.

After `config = get_effective_interview_config(interview, template)` (around line 362), the `config["questions"]` has the resolved questions. But the actual voice interview function (line 120) uses `_extract_questions_list(project)`.

**Change the worker to pass effective questions to start_voice_interview:**

In the `run_interview_worker` function, after getting the config (around line 362-367), extract questions from config:

```python
# Get effective questions (prefer template, then project)
effective_questions = None
if config["questions"]:
    # Template/interview questions are in JSONB format
    effective_questions = config["questions"]
```

Then pass `effective_questions` to `start_voice_interview` as a new parameter.

**Step 2: Update start_voice_interview signature**

Add parameter: `effective_questions: dict | None = None`

**Step 3: Update question extraction in start_voice_interview**

Replace the question extraction logic (lines 119-129):

```python
# Extract questions - prefer effective_questions from template, then project
if effective_questions:
    # Template questions come as JSONB: {"questions": [{"text": "...", ...}, ...]}
    questions_data = effective_questions.get("questions", [])
    questions = [q.get("text", "") for q in questions_data if q.get("text")]
else:
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
```

**Step 4: Update all calls to start_voice_interview**

Add `effective_questions=effective_questions` to the call around line 388.

**Step 5: Commit**

```bash
git add src/boswell/server/worker.py
git commit -m "feat: worker now uses template questions when available"
```

---

## Task 5: Update Interview Creation to Inherit Project Template

**Files:**
- Modify: `src/boswell/server/routes/guest.py:557-565`
- Modify: `src/boswell/server/routes/admin.py` (interview creation)

**Step 1: Update public join to use project.template_id**

In `start_public_interview` (guest.py), the Interview is created with `template_id=project.template_id`. This is already done from our previous work, but verify it uses the new field name.

**Step 2: Update named interview creation**

In admin.py, when creating a named interview, if no template is explicitly selected, default to the project's template:

Find the Interview creation in `interview_new_submit` (around line 539). Change:

```python
# If no template selected for this interview, inherit from project
final_template_id = parsed_template_id or project.template_id
```

Then use `template_id=final_template_id` in Interview creation.

**Step 3: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/routes/guest.py
git commit -m "feat: interviews inherit template from project by default"
```

---

## Task 6: Update Project Detail UI

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Move template selection out of Public Link section**

The template selection should be a project-level setting, not buried in the Public Link section.

Create a new section after the stats grid, before the Public Link section:

```html
<!-- Default Interview Type -->
<div class="card" style="margin-bottom: 2rem;">
    <div class="section-header">
        <h2>Default Interview Type</h2>
    </div>
    <p style="color: var(--fg-muted); margin-bottom: 1rem; font-size: 0.9375rem;">
        All interviews in this project use this template's questions and style by default.
    </p>

    <form method="post" action="/admin/projects/{{ project.id }}/set-template" style="display: flex; align-items: center; gap: 0.75rem;">
        <select name="template_id" id="template_id" style="flex: 1; max-width: 400px;">
            <option value="">Custom (project-generated questions)</option>
            {% for t in templates %}
            <option value="{{ t.id }}" {% if project.template_id == t.id %}selected{% endif %}>
                {{ t.name }} ({{ t.angle.value|title if t.angle else 'Exploratory' }}{% if t.angle_secondary %} + {{ t.angle_secondary.value|title }}{% endif %})
            </option>
            {% endfor %}
        </select>
        <button type="submit" class="btn btn-outline btn-sm">Save</button>
    </form>

    {% if project.template %}
    <div style="margin-top: 1rem; padding: 1rem; background: var(--bg-surface); border-radius: var(--radius-md);">
        <strong style="font-size: 0.875rem;">{{ project.template.name }}</strong>
        <span style="color: var(--fg-dim); font-size: 0.8125rem;"> · {{ project.template.angle.value|title if project.template.angle else 'Exploratory' }} style</span>
        {% if project.template.description %}
        <p style="color: var(--fg-muted); font-size: 0.8125rem; margin-top: 0.5rem;">{{ project.template.description }}</p>
        {% endif %}
    </div>
    {% endif %}
</div>
```

**Step 2: Simplify Public Link section**

Remove the template dropdown from the Public Link section since it's now at project level. The Public Link section should just show the link and generate/disable buttons.

**Step 3: Commit**

```bash
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat: move template selection to project level in UI"
```

---

## Task 7: Update Route Names for Clarity

**Files:**
- Modify: `src/boswell/server/routes/admin.py`

**Step 1: Rename route**

Change `/projects/{project_id}/set-public-template` to `/projects/{project_id}/set-template`.

**Step 2: Update function name**

Rename `set_public_template` to `set_template`.

**Step 3: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "refactor: rename set-public-template route to set-template"
```

---

## Task 8: Test End-to-End Flow

**Step 1: Start local server**

```bash
cd /Users/noahraford/Projects/boswell
docker-compose up -d
```

**Step 2: Manual testing checklist**

1. **Create new project with template:**
   - Go to `/admin/projects/new`
   - Verify Interview Type dropdown appears first
   - Select "ESA Interview" template
   - Fill in project details
   - Create project
   - Verify project detail page shows the template

2. **Test public link:**
   - Generate public link
   - Open link in incognito
   - Verify style badge shows the template's angle
   - Start interview
   - Verify Boswell uses the template's questions and style

3. **Test named interview:**
   - Add a named interview to the project
   - Don't select a template (should inherit from project)
   - Start the interview
   - Verify it uses the project's template

4. **Test custom project:**
   - Create a new project with "Custom" selected
   - Verify questions are generated from topic
   - Interviews should use generated questions

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found in testing"
```

---

## Task 9: Deploy to Production

**Step 1: Push all changes**

```bash
git push origin master
```

**Step 2: Verify Railway deployment**

No migration needed since we're reusing the existing column.

**Step 3: Test on production**

Run through the same testing checklist on production.

---

## Summary

| Task | Description | Key Changes |
|------|-------------|-------------|
| 1 | Rename field in model | `public_template_id` → `template_id` (keep column) |
| 2 | Update all references | Search/replace across codebase |
| 3 | Add to project creation | Template dropdown as first field |
| 4 | Update worker | Use template questions when available |
| 5 | Interview inheritance | Interviews default to project template |
| 6 | Update project detail UI | Template selection at project level |
| 7 | Rename route | `set-public-template` → `set-template` |
| 8 | Test | End-to-end verification |
| 9 | Deploy | Push and verify |

**Result:** Templates are selected at project creation time and drive content (questions, research) and style (angle) for all interviews. The template becomes the single source of truth for how interviews in that project are conducted.
