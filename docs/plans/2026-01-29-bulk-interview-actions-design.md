# Bulk Interview Actions Design

Add edit mode to project detail view enabling multi-select and bulk operations on interviews.

## Overview

Users can enter "edit mode" to select multiple interviews and perform bulk actions: delete, download transcripts, send reminders, or create follow-ups.

## User Flow

1. User clicks "Edit" button in toolbar
2. Table shows checkboxes; individual row actions hide
3. User selects interviews (individually or "select all")
4. Sticky action bar appears at bottom with bulk actions
5. User performs action; sees confirmation/toast feedback
6. User clicks "Done" to exit edit mode

## Edit Mode Activation

**Entering edit mode:**
- "Edit" button added to toolbar (alongside "Add Interview" and "Bulk Import")
- On click:
  - Checkbox column appears as first column in table
  - Header row gets "Select all" checkbox
  - Individual row action buttons (Transcript, Remind, Delete, etc.) hide
  - "Edit" button changes to "Done"

**Checkbox behavior:**
- Row checkbox toggles selection
- "Select all" has three states: unchecked, checked, indeterminate
- Selection updates sticky bar count in real-time
- "Select all" only affects visible (filtered) rows

**Exiting edit mode:**
- Click "Done" button
- All selections cleared
- Table returns to normal view

## Sticky Action Bar

**Position:** Fixed to bottom of viewport, full width

**Visibility:** Only when edit mode active AND 1+ interviews selected

**Styling:**
- Background: `var(--bg-elevated)` with subtle top border
- Height: ~60px

**Layout:**
```
[X] 3 selected                    [Download] [Remind] [Follow-up] [Delete]
```

- Left: Checkbox (deselect all) + count
- Right: Action buttons ordered by safety (least destructive first)

**Button styling:**
- Download, Remind, Follow-up: `btn-outline`
- Delete: red outline (`color: #994444; border-color: #994444`)

## Action Behaviors

### Delete
- Confirmation modal: "Delete X interviews? This cannot be undone."
- POST `/admin/projects/{project_id}/interviews/bulk-delete`
- Body: `{ "interview_ids": [...] }`
- Response: Page reload, exit edit mode
- Toast: "Deleted X interviews"

### Download Transcripts
- Pre-check: Count selected with transcripts (completed + transcript exists)
- If none have transcripts: Toast "None of the selected interviews have transcripts"
- If some have transcripts: Modal "Only X of Y selected interviews have transcripts. Download anyway?"
- If all have transcripts: Proceed directly
- GET `/admin/projects/{project_id}/transcripts/bulk-download?ids=id1,id2,...`
- Returns: JSON file with array of transcripts

### Send Reminder
- POST `/admin/projects/{project_id}/interviews/bulk-remind`
- Body: `{ "interview_ids": [...] }`
- Backend filters to: invited/started status + valid email
- Toast: "Sent reminders to X of Y selected" or "No interviews eligible for reminders"

### Create Follow-up
- POST `/admin/projects/{project_id}/interviews/bulk-followup`
- Body: `{ "interview_ids": [...] }`
- Backend filters to: completed status only
- Creates new interviews with fresh magic tokens
- Response: Page reload showing new interviews
- Toast: "Created X follow-up interviews"

## Frontend Implementation

**State (vanilla JS):**
```javascript
let editMode = false;
let selectedIds = new Set();
```

**Key functions:**
- `toggleEditMode()` - enter/exit edit mode, show/hide checkboxes and action bar
- `toggleSelection(id)` - add/remove from selectedIds, update UI
- `toggleSelectAll()` - select/deselect all visible rows
- `updateActionBar()` - update count, show/hide bar
- `getSelectedIds()` - return array for form submission

**Filter integration:**
- Existing `filterTable()` uses `.hidden` class
- "Select all" iterates only rows without `.hidden`

**Form submission:**
- Standard form POST with hidden inputs, or HTMX with `hx-vals`
- Delete/Follow-up reload page
- Remind uses HTMX swap none + toast

## Backend Endpoints (New)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/projects/{id}/interviews/bulk-delete` | Delete multiple interviews |
| POST | `/admin/projects/{id}/interviews/bulk-remind` | Send reminder emails |
| POST | `/admin/projects/{id}/interviews/bulk-followup` | Create follow-up interviews |
| GET | `/admin/projects/{id}/transcripts/bulk-download` | Download selected transcripts |

## Files to Modify

1. `src/boswell/server/templates/admin/project_detail.html`
   - Add Edit/Done toggle button
   - Add checkbox column (hidden by default)
   - Add sticky action bar HTML
   - Add JavaScript for edit mode state management

2. `src/boswell/server/routes/admin.py`
   - Add 4 new bulk action endpoints
   - Reuse existing single-item logic where possible

## Out of Scope

- Keyboard shortcuts for selection
- Drag-to-select
- Persisting selection across page loads
- Bulk edit of interview metadata
