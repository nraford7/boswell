# Bulk Interview Actions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add edit mode to project detail view with multi-select and bulk operations (delete, download, remind, follow-up).

**Architecture:** Toggle-based edit mode adds checkboxes to interview table. Sticky action bar at bottom shows selected count and action buttons. Four new backend endpoints handle bulk operations. Vanilla JS manages state.

**Tech Stack:** FastAPI, SQLAlchemy async, Jinja2 templates, vanilla JavaScript, HTMX

---

## Task 1: Add Bulk Delete Endpoint

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (after line 1410)

**Step 1: Add the bulk delete route**

Add after the existing `delete_interview` function (around line 1410):

```python
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

    # Fetch project to verify ownership
    project_result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

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
```

**Step 2: Verify it compiles**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from boswell.server.routes.admin import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add bulk delete endpoint for interviews"
```

---

## Task 2: Add Bulk Remind Endpoint

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (after bulk-delete)

**Step 1: Add the bulk remind route**

Add after the bulk delete function:

```python
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
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch eligible interviews (invited or started, with email)
    result = await db.execute(
        select(Interview)
        .where(Interview.id.in_(uuids))
        .where(Interview.project_id == project_id)
        .where(Interview.status.in_([InterviewStatus.invited, InterviewStatus.started]))
        .where(Interview.email.isnot(None))
    )
    interviews = result.scalars().all()

    settings = get_settings()
    sent_count = 0
    for interview in interviews:
        if interview.email:
            magic_link = f"{settings.base_url}/i/{interview.magic_token}"
            await send_invitation_email(
                to=interview.email,
                guest_name=interview.name,
                interview_topic=project.topic,
                magic_link=magic_link,
            )
            sent_count += 1

    logger.info(f"Sent {sent_count} reminder emails for project {project_id}")

    return JSONResponse({"sent": sent_count, "total": len(interview_ids)})
```

**Step 2: Verify it compiles**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from boswell.server.routes.admin import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add bulk remind endpoint for interviews"
```

---

## Task 3: Add Bulk Follow-up Endpoint

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (after bulk-remind)

**Step 1: Add the bulk follow-up route**

Add after the bulk remind function:

```python
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
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

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
```

**Step 2: Verify it compiles**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from boswell.server.routes.admin import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add bulk follow-up endpoint for interviews"
```

---

## Task 4: Add Bulk Download Transcripts Endpoint

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (after bulk-followup)

**Step 1: Add the bulk download route**

Add after the bulk follow-up function:

```python
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
        select(Project)
        .where(Project.id == project_id)
        .where(Project.team_id == user.team_id)
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

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
```

**Step 2: Verify it compiles**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from boswell.server.routes.admin import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add bulk download transcripts endpoint"
```

---

## Task 5: Add Edit Mode Toggle Button to Template

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Add Edit button to toolbar**

Find the section header with "Add Interview" button (around line 536-544) and add Edit button:

Replace:
```html
        <div class="section-header" style="margin-bottom: 1.5rem;">
            <h2>Interviews</h2>
            <div style="display: flex; align-items: center; gap: 1rem;">
                <a href="/admin/projects/{{ project.id }}/interviews/new" class="btn">
```

With:
```html
        <div class="section-header" style="margin-bottom: 1.5rem;">
            <h2>Interviews</h2>
            <div style="display: flex; align-items: center; gap: 1rem;">
                <button type="button" id="editModeBtn" class="btn btn-outline" onclick="toggleEditMode()">Edit</button>
                <a href="/admin/projects/{{ project.id }}/interviews/new" class="btn">
```

**Step 2: Verify syntax**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/boswell/server/templates')); env.get_template('admin/project_detail.html'); print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add edit mode toggle button to project detail"
```

---

## Task 6: Add Checkbox Column to Table

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Add CSS for checkbox column**

Add to the `<style>` block (around line 335, before `{% endblock %}`):

```css
    /* Edit mode styles */
    .checkbox-col {
        width: 40px;
        display: none;
    }

    .edit-mode .checkbox-col {
        display: table-cell;
    }

    .edit-mode .actions-cell {
        display: none;
    }

    .row-checkbox {
        width: 18px;
        height: 18px;
        cursor: pointer;
        accent-color: var(--accent);
    }

    .interviews-table tr.selected {
        background: var(--accent-subtle);
    }
```

**Step 2: Add checkbox header column**

Find the `<thead>` section (around line 564-571) and add checkbox column:

Replace:
```html
            <thead>
                <tr>
                    <th>Interviewee</th>
```

With:
```html
            <thead>
                <tr>
                    <th class="checkbox-col">
                        <input type="checkbox" class="row-checkbox" id="selectAllCheckbox" onchange="toggleSelectAll()">
                    </th>
                    <th>Interviewee</th>
```

**Step 3: Add checkbox to each row**

Find the `<tbody>` row template (around line 574-575) and add checkbox cell:

Replace:
```html
                {% for interview in interviews %}
                <tr data-status="{{ interview.status.value }}" data-name="{{ interview.name|lower }}">
                    <td>
```

With:
```html
                {% for interview in interviews %}
                <tr data-status="{{ interview.status.value }}" data-name="{{ interview.name|lower }}" data-id="{{ interview.id }}" data-has-transcript="{{ 'true' if interview.transcript else 'false' }}">
                    <td class="checkbox-col">
                        <input type="checkbox" class="row-checkbox" onchange="toggleSelection('{{ interview.id }}')">
                    </td>
                    <td>
```

**Step 4: Verify syntax**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/boswell/server/templates')); env.get_template('admin/project_detail.html'); print('OK')"`

Expected: `OK`

**Step 5: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add checkbox column to interviews table"
```

---

## Task 7: Add Sticky Action Bar HTML

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Add action bar CSS**

Add to the `<style>` block (after the edit mode styles):

```css
    /* Sticky action bar */
    .bulk-action-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: var(--bg-elevated);
        border-top: 1px solid var(--border);
        padding: 1rem 2rem;
        display: none;
        align-items: center;
        justify-content: space-between;
        z-index: 100;
        box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
    }

    .bulk-action-bar.visible {
        display: flex;
    }

    .bulk-action-bar .selection-info {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        color: var(--fg);
        font-weight: 500;
    }

    .bulk-action-bar .actions {
        display: flex;
        gap: 0.75rem;
    }

    .bulk-action-bar .btn-danger {
        color: #994444;
        border-color: #994444;
    }

    .bulk-action-bar .btn-danger:hover {
        background: rgba(153, 68, 68, 0.1);
    }

    /* Toast notification */
    .toast {
        position: fixed;
        bottom: 80px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--bg-elevated);
        border: 1px solid var(--border);
        padding: 0.75rem 1.5rem;
        border-radius: var(--radius-md);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 101;
        opacity: 0;
        transition: opacity 0.3s;
    }

    .toast.visible {
        opacity: 1;
    }

    /* Confirmation modal */
    .modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: none;
        align-items: center;
        justify-content: center;
        z-index: 200;
    }

    .modal-overlay.visible {
        display: flex;
    }

    .modal {
        background: var(--bg-elevated);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: 1.5rem;
        max-width: 400px;
        width: 90%;
    }

    .modal h3 {
        margin: 0 0 1rem;
        font-size: 1.125rem;
    }

    .modal p {
        margin: 0 0 1.5rem;
        color: var(--fg-muted);
    }

    .modal .actions {
        display: flex;
        gap: 0.75rem;
        justify-content: flex-end;
    }
```

**Step 2: Add action bar HTML**

Add just before the closing `</div>` of the container (before the final `<script>` block, around line 645):

```html
<!-- Bulk Action Bar -->
<div class="bulk-action-bar" id="bulkActionBar">
    <div class="selection-info">
        <input type="checkbox" class="row-checkbox" checked onchange="clearSelection()">
        <span id="selectionCount">0 selected</span>
    </div>
    <div class="actions">
        <button type="button" class="btn btn-outline" onclick="bulkDownload()">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16" style="margin-right: 0.375rem;">
                <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5z"/>
                <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708l3 3z"/>
            </svg>
            Download
        </button>
        <button type="button" class="btn btn-outline" onclick="bulkRemind()">Remind</button>
        <button type="button" class="btn btn-outline" onclick="bulkFollowup()">Follow-up</button>
        <button type="button" class="btn btn-outline btn-danger" onclick="bulkDelete()">Delete</button>
    </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<!-- Confirmation Modal -->
<div class="modal-overlay" id="modalOverlay">
    <div class="modal">
        <h3 id="modalTitle">Confirm</h3>
        <p id="modalMessage">Are you sure?</p>
        <div class="actions">
            <button type="button" class="btn btn-outline" onclick="hideModal()">Cancel</button>
            <button type="button" class="btn" id="modalConfirmBtn" onclick="modalConfirm()">Confirm</button>
        </div>
    </div>
</div>
```

**Step 3: Verify syntax**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/boswell/server/templates')); env.get_template('admin/project_detail.html'); print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add sticky bulk action bar and modal"
```

---

## Task 8: Add JavaScript for Edit Mode State Management

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Step 1: Add JavaScript**

Replace the existing `<script>` block at the end (starting around line 647) with the complete script that includes both existing filter functionality and new edit mode:

```javascript
<script>
let currentFilter = 'all';
let editMode = false;
let selectedIds = new Set();
let pendingAction = null;

// Existing filter functions
function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.filter === filter) {
            btn.classList.add('active');
        }
    });
    filterTable();
}

function filterTable() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#interviewsTable tbody tr');

    rows.forEach(row => {
        const status = row.dataset.status;
        const name = row.dataset.name;

        let passesFilter = currentFilter === 'all' || status === currentFilter;
        let passesSearch = !searchTerm || name.includes(searchTerm);

        if (passesFilter && passesSearch) {
            row.classList.remove('hidden');
        } else {
            row.classList.add('hidden');
        }
    });

    updateActionBar();
}

function copyLink(link, btn) {
    navigator.clipboard.writeText(link).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M12.736 3.97a.733.733 0 0 1 1.047 0c.286.289.29.756.01 1.05L7.88 12.01a.733.733 0 0 1-1.065.02L3.217 8.384a.757.757 0 0 1 0-1.06.733.733 0 0 1 1.047 0l3.052 3.093 5.4-6.425a.247.247 0 0 1 .02-.022Z"/></svg>';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
        }, 2000);
    });
}

// Edit mode functions
function toggleEditMode() {
    editMode = !editMode;
    const table = document.getElementById('interviewsTable');
    const btn = document.getElementById('editModeBtn');

    if (editMode) {
        table.classList.add('edit-mode');
        btn.textContent = 'Done';
        btn.classList.remove('btn-outline');
    } else {
        table.classList.remove('edit-mode');
        btn.textContent = 'Edit';
        btn.classList.add('btn-outline');
        clearSelection();
    }
}

function toggleSelection(id) {
    if (selectedIds.has(id)) {
        selectedIds.delete(id);
    } else {
        selectedIds.add(id);
    }
    updateRowSelection(id);
    updateActionBar();
}

function updateRowSelection(id) {
    const row = document.querySelector(`tr[data-id="${id}"]`);
    if (row) {
        const checkbox = row.querySelector('.row-checkbox');
        if (selectedIds.has(id)) {
            row.classList.add('selected');
            checkbox.checked = true;
        } else {
            row.classList.remove('selected');
            checkbox.checked = false;
        }
    }
}

function toggleSelectAll() {
    const checkbox = document.getElementById('selectAllCheckbox');
    const visibleRows = document.querySelectorAll('#interviewsTable tbody tr:not(.hidden)');

    if (checkbox.checked) {
        visibleRows.forEach(row => {
            const id = row.dataset.id;
            selectedIds.add(id);
            updateRowSelection(id);
        });
    } else {
        visibleRows.forEach(row => {
            const id = row.dataset.id;
            selectedIds.delete(id);
            updateRowSelection(id);
        });
    }
    updateActionBar();
}

function clearSelection() {
    selectedIds.forEach(id => {
        const row = document.querySelector(`tr[data-id="${id}"]`);
        if (row) {
            row.classList.remove('selected');
            row.querySelector('.row-checkbox').checked = false;
        }
    });
    selectedIds.clear();
    document.getElementById('selectAllCheckbox').checked = false;
    updateActionBar();
}

function updateActionBar() {
    const bar = document.getElementById('bulkActionBar');
    const countEl = document.getElementById('selectionCount');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');

    if (editMode && selectedIds.size > 0) {
        bar.classList.add('visible');
        countEl.textContent = `${selectedIds.size} selected`;
    } else {
        bar.classList.remove('visible');
    }

    // Update select all checkbox state
    const visibleRows = document.querySelectorAll('#interviewsTable tbody tr:not(.hidden)');
    const visibleIds = Array.from(visibleRows).map(r => r.dataset.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.has(id));
    const someSelected = visibleIds.some(id => selectedIds.has(id));

    selectAllCheckbox.checked = allSelected;
    selectAllCheckbox.indeterminate = someSelected && !allSelected;
}

// Toast
function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('visible');
    setTimeout(() => toast.classList.remove('visible'), duration);
}

// Modal
function showModal(title, message, onConfirm) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalMessage').textContent = message;
    pendingAction = onConfirm;
    document.getElementById('modalOverlay').classList.add('visible');
}

function hideModal() {
    document.getElementById('modalOverlay').classList.remove('visible');
    pendingAction = null;
}

function modalConfirm() {
    if (pendingAction) {
        pendingAction();
    }
    hideModal();
}

// Bulk actions
const projectId = '{{ project.id }}';

async function bulkDelete() {
    const count = selectedIds.size;
    showModal(
        'Delete Interviews',
        `Delete ${count} interview${count > 1 ? 's' : ''}? This cannot be undone.`,
        async () => {
            try {
                const response = await fetch(`/admin/projects/${projectId}/interviews/bulk-delete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ interview_ids: Array.from(selectedIds) })
                });
                const data = await response.json();
                showToast(`Deleted ${data.deleted} interview${data.deleted > 1 ? 's' : ''}`);
                setTimeout(() => location.reload(), 1000);
            } catch (e) {
                showToast('Error deleting interviews');
            }
        }
    );
}

async function bulkRemind() {
    try {
        const response = await fetch(`/admin/projects/${projectId}/interviews/bulk-remind`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interview_ids: Array.from(selectedIds) })
        });
        const data = await response.json();
        if (data.sent > 0) {
            showToast(`Sent reminders to ${data.sent} of ${data.total} selected`);
        } else {
            showToast('No interviews eligible for reminders');
        }
    } catch (e) {
        showToast('Error sending reminders');
    }
}

async function bulkFollowup() {
    try {
        const response = await fetch(`/admin/projects/${projectId}/interviews/bulk-followup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interview_ids: Array.from(selectedIds) })
        });
        const data = await response.json();
        if (data.created > 0) {
            showToast(`Created ${data.created} follow-up interview${data.created > 1 ? 's' : ''}`);
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('No completed interviews selected');
        }
    } catch (e) {
        showToast('Error creating follow-ups');
    }
}

function bulkDownload() {
    // Check how many have transcripts
    const rows = Array.from(selectedIds).map(id => document.querySelector(`tr[data-id="${id}"]`));
    const withTranscripts = rows.filter(r => r && r.dataset.hasTranscript === 'true').length;
    const total = selectedIds.size;

    if (withTranscripts === 0) {
        showToast('None of the selected interviews have transcripts');
        return;
    }

    if (withTranscripts < total) {
        showModal(
            'Download Transcripts',
            `Only ${withTranscripts} of ${total} selected interviews have transcripts. Download anyway?`,
            () => {
                window.location.href = `/admin/projects/${projectId}/transcripts/bulk-download?ids=${Array.from(selectedIds).join(',')}`;
            }
        );
    } else {
        window.location.href = `/admin/projects/${projectId}/transcripts/bulk-download?ids=${Array.from(selectedIds).join(',')}`;
    }
}
</script>
```

**Step 2: Verify syntax**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/boswell/server/templates')); env.get_template('admin/project_detail.html'); print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add JavaScript for edit mode and bulk actions"
```

---

## Task 9: Final Integration Test

**Step 1: Run the server locally**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run python -m boswell.server.main`

**Step 2: Manual testing checklist**

1. Navigate to a project with interviews
2. Click "Edit" button - verify checkboxes appear
3. Select some interviews - verify sticky bar appears
4. Test "Select All" - verify only visible rows selected
5. Apply a filter, then "Select All" - verify filtered selection
6. Click "Done" - verify edit mode exits and selections clear
7. Test each bulk action (if possible with test data)

**Step 3: Run existing tests**

Run: `cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions && uv run pytest tests/ -q`

Expected: Same 4 pre-existing failures, no new failures

**Step 4: Final commit if any cleanup needed**

```bash
cd /Users/noahraford/Projects/boswell/.worktrees/bulk-actions
git status
# If clean, no action needed
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Bulk delete endpoint | admin.py |
| 2 | Bulk remind endpoint | admin.py |
| 3 | Bulk follow-up endpoint | admin.py |
| 4 | Bulk download endpoint | admin.py |
| 5 | Edit mode toggle button | project_detail.html |
| 6 | Checkbox column | project_detail.html |
| 7 | Sticky action bar HTML/CSS | project_detail.html |
| 8 | JavaScript state management | project_detail.html |
| 9 | Integration testing | - |

Total: 8 implementation tasks + 1 testing task
