# Admin User Management Dashboard

## Overview

A centralized user management dashboard accessible from Settings, allowing site admins to view all users, see their project access, and perform account management actions (edit, reset password, deactivate, delete).

## Problem

Boswell has per-project sharing with role-based access control, but no way to see all users across the system or manage their accounts from one place. Admins must navigate to each project's sharing page individually and cannot reset passwords, deactivate accounts, or delete users.

## Design Decisions

- **Location**: New "Users" tab inside `/admin/settings`, visible only to admins
- **Admin gating**: `is_admin` boolean on User model. Seeded via Alembic migration for existing users (by email), and a `INITIAL_ADMIN_EMAIL` env var for first-run bootstrapping. (`ADMIN_EMAILS` was previously removed from the config; this does not re-introduce it as a runtime feature.)
- **Password reset**: Admin sets a temporary password directly (no email required). Same validation rules as normal password setting (8+ chars, 72 bytes max).
- **Deactivation**: Soft-delete via `deactivated_at` timestamp. Deactivated users cannot log in. Existing sessions are invalidated on next request via the `get_current_user` check.
- **Deletion**: Hard delete with cascade, but blocked if user is sole owner of any project.

## Data Model Changes

### User model additions

```python
# New columns on User
is_admin: bool = False           # Gates access to user management
deactivated_at: datetime | None  # Soft-deactivate (blocks login)
```

### Alembic migration

Single migration adding both columns with defaults:
- `is_admin` defaults to `False`
- `deactivated_at` defaults to `NULL`

The migration includes a data step: if the `INITIAL_ADMIN_EMAIL` environment variable is set, mark that user as `is_admin=True`. This is a one-time bootstrap for the first admin. Additional admins can be promoted from the Users dashboard afterward.

### Login guard

In `login_submit` (auth.py), after verifying credentials, check:
```python
if user.deactivated_at is not None:
    return error("This account has been deactivated.")
```

Same check in `verify_token` (magic link path) and `get_current_user` (session validation). The `get_current_user` check ensures that deactivation takes effect on the next request even for users with existing session cookies (no separate session revocation needed).

## Routes

All user management routes require the `require_admin` dependency.

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/settings` | GET | Account settings (existing, now tab 1) |
| `/admin/settings/users` | GET | Users list (admin only, tab 2) |
| `/admin/settings/users/{user_id}/edit` | POST | Update user name/email |
| `/admin/settings/users/{user_id}/reset-password` | POST | Set temporary password |
| `/admin/settings/users/{user_id}/deactivate` | POST | Soft-deactivate user |
| `/admin/settings/users/{user_id}/reactivate` | POST | Clear deactivation |
| `/admin/settings/users/{user_id}/delete` | POST | Hard delete + cascade |
| `/admin/settings/users/invite` | POST | Create standalone account invite |

### require_admin dependency

```python
async def require_admin(user: User = Depends(require_auth)) -> User:
    if not user.is_admin or user.deactivated_at is not None:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

Also checks `deactivated_at` as defense in depth, in case the `get_current_user` guard is bypassed.

## Safety Guards

### Self-protection
- **No self-deletion**: The delete route rejects `user_id == current_user.id` with a 400 error ("Cannot delete your own account").
- **No self-deactivation**: The deactivate route rejects `user_id == current_user.id` with a 400 error ("Cannot deactivate your own account").

### Last-admin protection
- **Cannot delete the last admin**: Before deleting an admin user, query `SELECT count(*) FROM users WHERE is_admin = true AND deactivated_at IS NULL`. If count would drop to 0, reject with error.
- **Cannot deactivate the last admin**: Same check before deactivation.

### Sole-owner protection
- **Cannot delete a sole project owner**: Before deleting a user, check if they are the sole owner of any project (same pattern as `assert_not_last_owner` in `authorization.py`). If so, reject with error listing the affected projects. Admin must transfer ownership first via the project's sharing page.
- **Cannot deactivate a sole project owner**: Same check. A deactivated sole owner would leave projects unmanageable.

### Email uniqueness
- **Edit route checks for duplicate emails**: Before updating a user's email, check that no other user has that email. Return a user-friendly error if duplicate, rather than letting it hit the database unique constraint.

## UI Design

### Settings page — tabbed layout

The existing account settings page gains a tab bar at the top:

```
[ Account ]  [ Users ]
```

- "Account" tab: existing name/password form (unchanged)
- "Users" tab: only rendered if `user.is_admin`
- Tab state is determined by the URL: `/admin/settings` = Account, `/admin/settings/users` = Users

The `is_admin` flag is available in templates via `user.is_admin` (already passed in context as `user`).

### Users tab layout

**Header row**: "Users" title + "Invite User" button (right-aligned)

**Users table**:

| Name | Email | Status | Projects | Joined | Actions |
|------|-------|--------|----------|--------|---------|
| Noah R. | noah@example.com | Active | 3 projects | Jan 12 | Edit / Reset PW / Deactivate / Delete |
| Jane D. | jane@example.com | Active | 1 project | Feb 1 | Edit / Reset PW / Deactivate / Delete |
| Bob S. | bob@example.com | Deactivated | 2 projects | Jan 20 | Reactivate / Delete |

**Data loading**: The users list is loaded with a single query that eagerly loads project shares and their associated projects, avoiding N+1 queries. The query joins `users` -> `project_shares` -> `interviews` (projects table).

**Search**: A search box filters the table by name or email (client-side filtering, same pattern as the interview search in `project_detail.html`).

**Projects column**: Shows count. Clicking expands an inline detail row showing project names and roles:
```
  Project Alpha — owner
  Project Beta — view
  Project Gamma — collaborate
```

**Actions**: Icon buttons per row:
- Pencil icon — edit name/email (opens modal)
- Key icon — reset password (opens modal with password input)
- Pause/play icon — deactivate/reactivate (confirmation)
- Trash icon — delete (confirmation modal warning about permanent removal)
- Actions on the current user's own row are disabled (no self-edit of admin status, no self-delete/deactivate)

**Invite modal**: Email input + optional name. Creates an `AccountInvite` with `project_id=NULL` and `role=NULL` (permitted by the existing check constraint). The admin copies and shares the invite link manually. When claimed, the user gets an account but no project access — they land on an empty dashboard until shared into projects.

### Action modals

All actions use confirmation modals (same pattern as bulk delete in project_detail.html):

**Edit user modal:**
- Name input (pre-filled)
- Email input (pre-filled)
- Save / Cancel buttons
- Error display for duplicate email

**Reset password modal:**
- New password input
- Confirm password input
- Save / Cancel buttons
- Enforces same rules as normal password setting: minimum 8 characters, maximum 72 bytes

**Delete user modal:**
- Warning text: "Permanently delete {name}? This removes their access to all projects."
- If user is sole owner of projects, shows error listing those projects instead
- Delete / Cancel buttons

**Deactivate modal:**
- Warning text: "Deactivate {name}? They will be unable to log in."
- If user is sole owner of projects, shows error listing those projects instead
- Deactivate / Cancel buttons

## Implementation Scope

### Files to create
- `src/boswell/server/templates/admin/settings_users.html` — Users tab template
- Alembic migration for `is_admin` and `deactivated_at` columns

### Files to modify
- `src/boswell/server/models.py` — Add `is_admin`, `deactivated_at` to User
- `src/boswell/server/routes/admin.py` — Add user management routes, `require_admin` dependency
- `src/boswell/server/routes/auth.py` — Add deactivation check to login/session flows
- `src/boswell/server/templates/admin/account_settings.html` — Add tab navigation, pass `active_tab` context
- Navigation templates — "Users" tab conditionally shown in settings

### Out of scope
- Global admin roles beyond `is_admin` boolean
- Audit/activity logs
- Email notifications for account changes
- Bulk user operations (import CSV of users)
- API keys / programmatic access
- Pagination (can be added later if user count grows)
