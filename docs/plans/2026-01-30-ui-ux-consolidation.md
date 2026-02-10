# UI/UX Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Simplify Boswell's admin interface by eliminating redundant configuration paths, clarifying the Template/Project/Interview hierarchy, and standardizing UI patterns.

**Architecture:** Remove duplicate template/style selectors from interview creation (inherit from project). Move project template selector from detail page to edit page only. Consolidate bulk import naming. Add missing navigation active states. Standardize form patterns across all forms.

**Tech Stack:** Jinja2 templates, CSS, minimal JavaScript changes

---

## Task 1: Simplify Interview Creation Form

**Files:**
- Modify: `src/boswell/server/templates/admin/interview_new.html`

**Context:** Currently, when adding an interview to a project, users can select a template, add custom questions, choose interview style, and save as template. This duplicates project-level settings. Interviews should inherit from the project - the only inputs needed are interviewee details and optional personal context.

**Step 1: Read current interview_new.html**

Familiarize with the current structure before modifying.

**Step 2: Remove template selection section**

Replace lines 79-96 (Interview Type section with template dropdown) - remove entirely. The interview inherits the project's template.

**Step 3: Remove custom style section**

Remove lines 111-151 (the `custom-style` div containing angle selection, secondary blend, and save-as-template checkbox). This configuration belongs at project/template level.

**Step 4: Remove the JavaScript for template/style toggling**

Remove the `<script>` block at the bottom (lines 186-211) containing `handleTemplateChange()`, `toggleCustomAngle()`, and `toggleTemplateName()` functions - no longer needed.

**Step 5: Clean up form structure**

The remaining form should have:
1. Interviewee section (name, email) - keep as-is
2. Interview Topic section with Questions textarea - keep but simplify description
3. Background on Interviewee section (notes, links, files) - keep as-is
4. Submit buttons - keep as-is

Update the "Interview Topic" section description from "What should Boswell explore?" to "Optional: Add questions specific to this interviewee. Project questions are used by default."

**Step 6: Test manually**

Run the server and verify:
- Navigate to a project → Add Interview
- Form shows only: name, email, questions (optional), context fields
- No template dropdown, no style selectors
- Creating an interview works

**Step 7: Commit**

```bash
git add src/boswell/server/templates/admin/interview_new.html
git commit -m "refactor(ui): simplify interview creation - inherit from project"
```

---

## Task 2: Move Template Selector from Project Detail to Edit Only

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`
- Modify: `src/boswell/server/templates/admin/project_edit.html`

**Context:** The template selector currently appears on both project_detail.html (as a standalone form) and project_edit.html. Having it in two places creates confusion. Project detail should be read-only display; all editing goes through the Edit page.

**Step 1: Remove template selector card from project_detail.html**

Remove lines 547-576 (the entire "Default Interview Type" card containing the template selection form).

**Step 2: Add template display to project header**

In the project header area (around line 494-500, after the page-subtitle), add a simple display showing the current template name:

```html
{% if project.template %}
<span style="color: var(--fg-dim); font-size: 0.875rem;">
    &middot; {{ project.template.name }} style
</span>
{% endif %}
```

Add this inside the page-subtitle paragraph, after the target_minutes display.

**Step 3: Verify project_edit.html has template selector**

Confirm `project_edit.html` already has the template selector (lines 112-123). It does - no changes needed there.

**Step 4: Remove the /set-template route usage note**

The route `/admin/projects/{{ project.id }}/set-template` is no longer used from the UI. The backend route can remain (won't break anything) but is now only accessible via the edit form.

**Step 5: Test manually**

- View project detail → No template selector card visible
- Template name shows in header if one is set
- Click "Edit Project" → Template selector is available there
- Saving from edit page updates the template

**Step 6: Commit**

```bash
git add src/boswell/server/templates/admin/project_detail.html src/boswell/server/templates/admin/project_edit.html
git commit -m "refactor(ui): move template selector to project edit only"
```

---

## Task 3: Add Navigation Active States

**Files:**
- Modify: `src/boswell/server/templates/base.html`
- Modify: `src/boswell/server/templates/admin/dashboard.html`
- Modify: `src/boswell/server/templates/admin/templates_list.html`
- Modify: `src/boswell/server/templates/admin/project_detail.html`
- Modify: `src/boswell/server/templates/admin/project_new.html`
- Modify: `src/boswell/server/templates/admin/project_edit.html`
- Modify: `src/boswell/server/templates/admin/interview_new.html`
- Modify: `src/boswell/server/templates/admin/template_form.html`
- Modify: `src/boswell/server/templates/admin/invite.html`
- Modify: `src/boswell/server/templates/admin/bulk_import.html`
- Modify: `src/boswell/server/templates/admin/transcript.html`

**Context:** Navigation links have no visual distinction for the active page. Adding this improves wayfinding.

**Step 1: Add active state CSS to base.html**

In the `<style>` section of base.html, after the `.nav-links a:hover` rule (around line 437), add:

```css
.nav-links a.active {
    color: var(--accent);
    background-color: var(--accent-subtle);
}
```

**Step 2: Update dashboard.html nav**

The nav already has `class="active"` on Projects link (line 165). Verify it's correct.

**Step 3: Update templates_list.html nav**

Change line 82 from:
```html
<a href="/admin/templates">Interview Types</a>
```
to:
```html
<a href="/admin/templates" class="active">Interview Types</a>
```

**Step 4: Update all project-related pages**

For these files, ensure the Projects link has `class="active"`:
- project_detail.html (line 473)
- project_new.html (line 107)
- project_edit.html (line 63)
- interview_new.html (line 37)
- invite.html (line 24)
- transcript.html (line 116)

Pattern: `<a href="/admin/" class="active">Projects</a>`

**Step 5: Update template_form.html nav**

Change the Interview Types link to have `class="active"`:
```html
<a href="/admin/templates" class="active">Interview Types</a>
```

**Step 6: Update bulk_import.html nav**

This is a cross-cutting page - keep Projects as active since it deals with creating projects:
```html
<a href="/admin/" class="active">Projects</a>
```

**Step 7: Test manually**

Navigate through the app:
- Dashboard → Projects link highlighted
- Interview Types → Interview Types link highlighted
- Any project page → Projects link highlighted

**Step 8: Commit**

```bash
git add src/boswell/server/templates/
git commit -m "feat(ui): add navigation active states"
```

---

## Task 4: Rename and Clarify Bulk Import Pages

**Files:**
- Rename: `src/boswell/server/templates/admin/invite.html` → `src/boswell/server/templates/admin/project_bulk_import.html`
- Modify: `src/boswell/server/templates/admin/bulk_import.html` (update title/description)
- Modify: `src/boswell/server/routes/admin.py` (update template reference)
- Modify: `src/boswell/server/templates/admin/project_detail.html` (update link text)

**Context:** Two bulk import pages exist with confusing names. `invite.html` imports guests to a specific project. `bulk_import.html` creates projects + guests from CSV. Rename for clarity.

**Step 1: Find the route that renders invite.html**

Search for the template reference in routes:
```bash
grep -r "invite.html" src/boswell/server/
```

**Step 2: Rename invite.html to project_bulk_import.html**

```bash
mv src/boswell/server/templates/admin/invite.html src/boswell/server/templates/admin/project_bulk_import.html
```

**Step 3: Update the route in admin.py**

Find the route rendering this template and change `"admin/invite.html"` to `"admin/project_bulk_import.html"`.

**Step 4: Update project_detail.html link text**

Change the "Bulk Import" button (around line 674) from:
```html
<a href="/admin/projects/{{ project.id }}/invite" class="btn btn-outline">Bulk Import</a>
```
to:
```html
<a href="/admin/projects/{{ project.id }}/invite" class="btn btn-outline">Import from CSV</a>
```

**Step 5: Update bulk_import.html title and description**

Change the page title from "Bulk Upload" to "Bulk Create Projects & Interviews" for clarity about its cross-project nature.

Update the h1 on line 209 from:
```html
<h1 ...>Bulk Upload</h1>
```
to:
```html
<h1 ...>Bulk Create Projects & Interviews</h1>
```

**Step 6: Test manually**

- Project detail → "Import from CSV" button works
- Cross-project bulk import page has clearer title

**Step 7: Commit**

```bash
git add -A
git commit -m "refactor(ui): clarify bulk import page naming"
```

---

## Task 5: Standardize Form Patterns

**Files:**
- Modify: `src/boswell/server/templates/admin/project_edit.html`

**Context:** Forms use inconsistent patterns. `project_new.html` uses `h3.form-section-title` + `p.form-section-desc`. `project_edit.html` uses uppercase h3 headers. Standardize on the project_new pattern.

**Step 1: Update project_edit.html form section styles**

Replace the form-section styles (lines 20-36) with the standard pattern from project_new.html:

```css
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
```

**Step 2: Update form section markup**

Change each form section from:
```html
<div class="form-section">
    <h3>Project Name</h3>
    ...
    <p class="help-text">...</p>
</div>
```

to:
```html
<div class="form-section">
    <h3 class="form-section-title">Project Name</h3>
    <p class="form-section-desc">A short, memorable name for this project.</p>
    <input ...>
</div>
```

Apply to all sections:
- Project Name
- Research Topic / Intent
- Public Description
- Introduction Message
- Default Interview Type
- Research Summary
- Interview Questions

**Step 3: Remove old help-text styling**

The old `.help-text` class in project_edit.html (lines 32-36) can be removed since we're using form-section-desc.

**Step 4: Test manually**

- Edit any project → Form has consistent styling with new project form
- All labels are display font, all descriptions are dim text below

**Step 5: Commit**

```bash
git add src/boswell/server/templates/admin/project_edit.html
git commit -m "refactor(ui): standardize form patterns in project edit"
```

---

## Task 6: Improve Public Link Visibility on Project Detail

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Context:** The Public Interview Link is buried mid-page. For projects using public links, this should be more prominent. Move it into the project header area.

**Step 1: Move public link to header**

In the project header area (around line 501-518, after the Edit Project / Download buttons), add a condensed public link display:

```html
{% if project.public_link_token %}
<div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem;">
    <span style="font-size: 0.8125rem; color: var(--fg-dim);">Public link:</span>
    <code style="font-size: 0.75rem; color: var(--fg-muted);">{{ base_url }}/join/{{ project.public_link_token }}</code>
    <button type="button" class="copy-btn" onclick="copyPublicLink()" title="Copy link" style="width: 24px; height: 24px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="currentColor" viewBox="0 0 16 16">
            <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/>
            <path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/>
        </svg>
    </button>
</div>
{% endif %}
```

**Step 2: Simplify the full Public Link card**

The existing Public Link card (lines 579-615) is now redundant for display but still needed for management actions (regenerate, disable, generate). Convert it to a management-focused card:

Change the card header to "Manage Public Link" and only show the action buttons (regenerate/disable or generate).

**Step 3: Test manually**

- Project with public link → Link visible in header with copy button
- Management card still allows regenerate/disable
- Project without link → Only "Generate" button in management card

**Step 4: Commit**

```bash
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add public link to project header for visibility"
```

---

## Task 7: Add Edit Mode Explanation

**Files:**
- Modify: `src/boswell/server/templates/admin/project_detail.html`

**Context:** The Edit button reveals checkboxes for bulk operations, but there's no indication of what it does before clicking.

**Step 1: Add title attribute to Edit button**

Change the Edit button (around line 667) from:
```html
<button type="button" id="editModeBtn" class="btn btn-outline" onclick="toggleEditMode()">Edit</button>
```
to:
```html
<button type="button" id="editModeBtn" class="btn btn-outline" onclick="toggleEditMode()" title="Select multiple interviews for bulk actions">Edit</button>
```

**Step 2: Commit**

```bash
git add src/boswell/server/templates/admin/project_detail.html
git commit -m "feat(ui): add tooltip explaining Edit mode purpose"
```

---

## Summary of Changes

| Task | Files Modified | Purpose |
|------|---------------|---------|
| 1 | interview_new.html | Remove duplicate template/style config |
| 2 | project_detail.html, project_edit.html | Consolidate template selector location |
| 3 | base.html + 10 templates | Add navigation active states |
| 4 | invite.html → project_bulk_import.html, admin.py | Clarify bulk import naming |
| 5 | project_edit.html | Standardize form patterns |
| 6 | project_detail.html | Improve public link visibility |
| 7 | project_detail.html | Add Edit mode tooltip |

---

## Final Verification

After all tasks:
1. Navigate through entire admin flow
2. Create project → Add interviews → View transcripts
3. Verify no template selection during interview creation
4. Verify navigation highlighting works on all pages
5. Verify form styling is consistent
6. Verify public link is visible in project header
