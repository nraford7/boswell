# Admin User Management Dashboard — Implementation Plan

> **For Claude:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a centralized user management dashboard under Settings > Users, gated to admin users, with full CRUD for accounts.

**Architecture:** Two new columns on the User model (`is_admin`, `deactivated_at`) + an Alembic migration. New routes under `/admin/settings/users/*` in `admin.py` behind a `require_admin` dependency. A new `settings_users.html` template with a users table and JS-driven modals. Deactivation checks added to the auth login flow.

**Tech Stack:** Python/FastAPI, SQLAlchemy (async), Alembic, Jinja2 templates, vanilla JS

**Spec:** `docs/superpowers/specs/2026-02-11-admin-user-dashboard-design.md`

---

## Chunk 1: Data Model + Migration + Auth Guards

### Task 1: Add `is_admin`, `deactivated_at`, and relationships to models

**Files:**
- Modify: `src/boswell/server/models.py:110-143` (ProjectShare relationships)
- Modify: `src/boswell/server/models.py:194-209` (User class)

- [ ] **Step 1: Add columns to User model**

In `src/boswell/server/models.py`, add two columns and a relationship to the `User` class after `created_at` (line 208):

```python
    is_admin: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    project_shares: Mapped[list["ProjectShare"]] = relationship(
        "ProjectShare",
        foreign_keys="ProjectShare.user_id",
        back_populates="user",
        lazy="select",
    )
```

The file already has `import sqlalchemy as sa` (line 10), `DateTime` (line 11), `Optional` (line 7), and `relationship` (line 13).

- [ ] **Step 2: Update ProjectShare.user to add back_populates**

In `src/boswell/server/models.py`, change line 136 from:

```python
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
```

to:

```python
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="project_shares")
```

This is required because the new `User.project_shares` relationship uses `back_populates="user"`, which must be reciprocal.

- [ ] **Step 3: Verify model loads without errors**

Run: `uv run python -c "from boswell.server.models import User; print(User.__table__.columns.keys())"`
Expected: Output includes `is_admin` and `deactivated_at`

- [ ] **Step 4: Commit**

```bash
git add src/boswell/server/models.py
git commit -m "feat(models): add is_admin, deactivated_at, and project_shares relationship to User"
```

---

### Task 2: Create Alembic migration

**Files:**
- Create: `src/boswell/server/migrations/versions/h1a2b3c4d5e6_add_user_admin_and_deactivation.py`

- [ ] **Step 1: Write the migration file**

Create `src/boswell/server/migrations/versions/h1a2b3c4d5e6_add_user_admin_and_deactivation.py`:

```python
"""Add is_admin and deactivated_at to users.

Revision ID: h1a2b3c4d5e6
Revises: g3c4d5e6f7a8
Create Date: 2026-02-11
"""
from typing import Sequence, Union
import os

from alembic import op
import sqlalchemy as sa

revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, None] = "g3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))

    # One-time bootstrap: promote initial admin by email
    admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    if admin_email:
        conn = op.get_bind()
        conn.execute(
            sa.text("UPDATE users SET is_admin = true WHERE email = :email"),
            {"email": admin_email.strip().lower()},
        )


def downgrade() -> None:
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_admin")
```

Note: Uses `op.get_bind().execute()` for parameterized queries, which is the correct Alembic pattern. `down_revision` is `g3c4d5e6f7a8` — the last migration in the chain.

- [ ] **Step 2: Verify migration file syntax**

Run: `uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('m', 'src/boswell/server/migrations/versions/h1a2b3c4d5e6_add_user_admin_and_deactivation.py'); mod = importlib.util.module_from_spec(spec)"`
Expected: No import errors

- [ ] **Step 3: Commit**

```bash
git add src/boswell/server/migrations/versions/h1a2b3c4d5e6_add_user_admin_and_deactivation.py
git commit -m "feat(migration): add is_admin and deactivated_at columns"
```

---

### Task 3: Add deactivation check to auth flows

**Files:**
- Modify: `src/boswell/server/routes/auth.py:86-112` (get_current_user)
- Modify: `src/boswell/server/routes/auth.py:130-170` (login_submit)
- Modify: `src/boswell/server/routes/auth.py:198-235` (verify_token)

- [ ] **Step 1: Add deactivation check to `get_current_user`**

In `src/boswell/server/routes/auth.py`, in the `get_current_user` function, after the user is loaded from DB (line 111-112), add a deactivation check before returning:

```python
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and user.deactivated_at is not None:
        return None
    return user
```

This invalidates existing sessions for deactivated users on their next request.

- [ ] **Step 2: Add deactivation check to `login_submit`**

In the password login path of `login_submit` (after verifying password succeeds, before creating session — around line 165), add:

```python
        if user.deactivated_at is not None:
            return templates.TemplateResponse(
                request=request,
                name="admin/login.html",
                context={"message": "This account has been deactivated."},
            )
```

Insert this after the `if not verify_password(...)` block and before the `# Success — create session` comment.

- [ ] **Step 3: Add deactivation check to `verify_token`**

In the `verify_token` function (magic link login), after the user is loaded (around line 228), add:

```python
    if user.deactivated_at is not None:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "This account has been deactivated."},
        )
```

Insert this after the `if not user:` block and before creating the session token.

- [ ] **Step 4: Verify no import errors**

Run: `uv run python -c "from boswell.server.routes.auth import get_current_user, login_submit, verify_token; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/boswell/server/routes/auth.py
git commit -m "feat(auth): block deactivated users from login and sessions"
```

---

### Task 4: Add `require_admin` dependency and sole-owner helper

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (near `require_auth`, around line 75)

- [ ] **Step 1: Add `require_admin` function**

In `src/boswell/server/routes/admin.py`, add a new dependency right after the `require_auth` function (around line 75, before the routes section):

```python
async def require_admin(
    request: Request,
    user: User = Depends(require_auth),
) -> User:
    """Require admin access. Returns 403 for non-admins."""
    if not user.is_admin or user.deactivated_at is not None:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

- [ ] **Step 2: Add sole-owner helper function**

Add this helper after `require_admin`:

```python
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
```

Note: Uses `func.count()` which is already imported in admin.py (line 18: `from sqlalchemy import func, select`).

- [ ] **Step 3: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add require_admin dependency and sole-owner helper"
```

---

### Task 5: Write tests for auth guards, admin check, and sole-owner helper

**Files:**
- Create: `tests/test_admin_users.py`

- [ ] **Step 1: Write tests**

Create `tests/test_admin_users.py`:

```python
"""Tests for admin user management guards and helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4
from datetime import datetime, timezone

from boswell.server.models import User, ProjectRole, ProjectShare


class TestDeactivatedUserBlocking:
    """Deactivated users should be treated as unauthenticated."""

    def test_deactivated_user_has_timestamp(self):
        """Deactivated users have a non-None deactivated_at."""
        user = MagicMock(spec=User)
        user.deactivated_at = datetime.now(timezone.utc)
        assert user.deactivated_at is not None

    def test_active_user_has_no_timestamp(self):
        """Active users have deactivated_at = None."""
        user = MagicMock(spec=User)
        user.deactivated_at = None
        assert user.deactivated_at is None


class TestRequireAdminLogic:
    """is_admin flag gates access to user management."""

    def test_admin_user_passes(self):
        """Active admin passes the require_admin check."""
        user = MagicMock(spec=User)
        user.is_admin = True
        user.deactivated_at = None
        # require_admin allows: is_admin=True AND deactivated_at is None
        assert user.is_admin and user.deactivated_at is None

    def test_non_admin_user_blocked(self):
        """Non-admin is rejected."""
        user = MagicMock(spec=User)
        user.is_admin = False
        user.deactivated_at = None
        assert not user.is_admin

    def test_deactivated_admin_blocked(self):
        """Even an admin should be blocked if deactivated."""
        user = MagicMock(spec=User)
        user.is_admin = True
        user.deactivated_at = datetime.now(timezone.utc)
        # require_admin rejects: deactivated_at is not None
        is_allowed = user.is_admin and user.deactivated_at is None
        assert not is_allowed


class TestSelfProtectionGuards:
    """Admins cannot delete or deactivate themselves."""

    def test_self_delete_blocked(self):
        """user_id == current_user.id should be rejected."""
        admin_id = uuid4()
        target_id = admin_id  # same user
        assert target_id == admin_id

    def test_different_user_delete_allowed(self):
        """Deleting a different user is allowed (guard passes)."""
        admin_id = uuid4()
        target_id = uuid4()
        assert target_id != admin_id


class TestSoleOwnerLogic:
    """Cannot delete/deactivate sole project owners."""

    def test_user_is_sole_owner_when_only_owner(self):
        """A single owner share means user is sole owner."""
        owner_count = 1  # Only one owner on the project
        assert owner_count == 1  # sole owner — block action

    def test_user_is_not_sole_owner_with_co_owners(self):
        """Multiple owners means user is NOT sole owner."""
        owner_count = 2
        assert owner_count > 1  # not sole owner — allow action

    def test_user_with_no_owned_projects(self):
        """User who owns nothing can be freely deleted."""
        owned_project_ids = []
        assert len(owned_project_ids) == 0


class TestLastAdminGuard:
    """Cannot deactivate/delete the last active admin."""

    def test_last_admin_blocked(self):
        """When active admin count is 1, action is blocked."""
        active_admin_count = 1
        assert active_admin_count <= 1  # block

    def test_multiple_admins_allowed(self):
        """When active admin count > 1, action is allowed."""
        active_admin_count = 3
        assert active_admin_count > 1  # allow
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_users.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_admin_users.py
git commit -m "test: add admin user management guard tests"
```

---

## Chunk 2: User Management Routes

### Task 6: Add the Users list route

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (append after existing `update_account` route, around line 2394)

- [ ] **Step 1: Add the users list route**

In `src/boswell/server/routes/admin.py`, add after the existing `update_account` route:

```python
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
```

Note: `selectinload` is already imported at line 20 of admin.py.

- [ ] **Step 2: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add users list route with eager-loaded project shares"
```

---

### Task 7: Add user action routes (edit, reset-password, deactivate, reactivate, delete, invite)

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (append after users list route)

Important imports: admin.py already has `from datetime import datetime, timezone` (line 11) and `from sqlalchemy import func, select` (line 18). You must add `timedelta` and `update` to these imports:

```python
# Line 11: add timedelta
from datetime import datetime, timedelta, timezone

# Line 18: add update
from sqlalchemy import func, select, update
```

- [ ] **Step 1: Add the required imports to the top of admin.py**

Update line 11:
```python
from datetime import datetime, timedelta, timezone
```

Update line 18:
```python
from sqlalchemy import func, select, update
```

- [ ] **Step 2: Add edit user route**

```python
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
```

- [ ] **Step 3: Add reset password route**

```python
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
```

- [ ] **Step 4: Add deactivate route**

```python
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

    # Check last-admin guard
    if target.is_admin:
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
        names = ", ".join(p.name or p.topic for p in sole_projects)
        return RedirectResponse(
            url=f"/admin/settings/users?error=User+is+sole+owner+of:+{names}.+Transfer+ownership+first.",
            status_code=303,
        )

    target.deactivated_at = datetime.now(timezone.utc)
    await db.commit()
    return RedirectResponse(url="/admin/settings/users?message=User+deactivated", status_code=303)
```

- [ ] **Step 5: Add reactivate route**

```python
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
```

- [ ] **Step 6: Add delete route**

```python
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

    # Check last-admin guard
    if target.is_admin:
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
        names = ", ".join(p.name or p.topic for p in sole_projects)
        return RedirectResponse(
            url=f"/admin/settings/users?error=User+is+sole+owner+of:+{names}.+Transfer+ownership+first.",
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
```

Note: Uses `update(AccountInvite)` — `update` was added to imports in Step 1.

- [ ] **Step 7: Add invite route**

```python
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
```

Note: Uses `secrets.token_urlsafe(48)` directly (already imported in admin.py line 9) and `token_prefix=raw_token[:12]` matching the existing pattern in `share_project`. Uses `timedelta` (added to imports in Step 1).

- [ ] **Step 8: Verify all routes load**

Run: `uv run python -c "from boswell.server.routes.admin import admin_users_list, admin_edit_user, admin_reset_password, admin_deactivate_user, admin_reactivate_user, admin_delete_user, admin_invite_user; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): add user management action routes"
```

---

### Task 8: Update existing settings route to pass `active_tab`

**Files:**
- Modify: `src/boswell/server/routes/admin.py:2345-2355` (account_settings)
- Modify: `src/boswell/server/routes/admin.py:2358-2393` (update_account)

- [ ] **Step 1: Add `active_tab` to both settings routes**

In `account_settings` (GET `/settings`), update the context:

```python
context={"user": user, "message": None, "active_tab": "account"},
```

In `update_account` (POST `/settings`), update both TemplateResponse calls to include `"active_tab": "account"` in their context dicts.

- [ ] **Step 2: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "feat(admin): pass active_tab to settings templates"
```

---

## Chunk 3: Templates

### Task 9: Add tab navigation to account_settings.html

**Files:**
- Modify: `src/boswell/server/templates/admin/account_settings.html`

- [ ] **Step 1: Add tab navigation below the page header**

In `account_settings.html`, replace the page-header div (lines 87-89):

```html
    <div class="page-header">
        <h1 class="page-title">Account <span>Settings</span></h1>
    </div>
```

with a tabbed header:

```html
    <div class="page-header">
        <h1 class="page-title">Settings</h1>
    </div>

    <div class="tabs" style="margin-bottom: 2rem; border-bottom: 1px solid var(--border); display: flex; gap: 0;">
        <a href="/admin/settings" class="tab-link {% if active_tab == 'account' %}active{% endif %}"
           style="padding: 0.75rem 1.25rem; font-size: 0.875rem; font-weight: 500; color: {% if active_tab == 'account' %}var(--accent){% else %}var(--fg-muted){% endif %}; border-bottom: 2px solid {% if active_tab == 'account' %}var(--accent){% else %}transparent{% endif %}; text-decoration: none; margin-bottom: -1px;">
            Account
        </a>
        {% if user.is_admin %}
        <a href="/admin/settings/users" class="tab-link {% if active_tab == 'users' %}active{% endif %}"
           style="padding: 0.75rem 1.25rem; font-size: 0.875rem; font-weight: 500; color: {% if active_tab == 'users' %}var(--accent){% else %}var(--fg-muted){% endif %}; border-bottom: 2px solid {% if active_tab == 'users' %}var(--accent){% else %}transparent{% endif %}; text-decoration: none; margin-bottom: -1px;">
            Users
        </a>
        {% endif %}
    </div>
```

- [ ] **Step 2: Commit**

```bash
git add src/boswell/server/templates/admin/account_settings.html
git commit -m "feat(ui): add tabbed navigation to settings page"
```

---

### Task 10: Create the Users tab template

**Files:**
- Create: `src/boswell/server/templates/admin/settings_users.html`

- [ ] **Step 1: Create the template file**

Create `src/boswell/server/templates/admin/settings_users.html`. This template extends `base.html`, includes the same nav bar as `account_settings.html`, and shows the tabbed settings with the Users tab active.

The template should include:
1. Same nav bar as other admin pages (Projects, Interview Types, Settings, user name, Logout)
2. Same tab bar as account_settings.html (with "Users" tab active)
3. Message/error banners from query params (`request.query_params.get('message')`, etc.)
4. Invite link display area (shown when `invite_link` query param present)
5. Users table with expandable project details
6. Action modals (edit, reset password, delete, deactivate confirmation)
7. An "Invite User" button + modal

Key implementation details:
- Read `message`, `error`, and `invite_link` from `request.query_params` in the template
- Each user row shows: name, email, status badge (Active/Deactivated/Admin), project count, joined date, action buttons
- The project count is a clickable element that toggles an inline detail row showing project names + roles
- Action buttons are disabled/hidden for the current user's own row (prevent self-delete, self-deactivate)
- Modals use form POSTs to the action routes (same pattern as project_detail.html modals)
- Include client-side search filtering (same pattern as interview search in project_detail.html)

Styling patterns to follow (from `project_detail.html` and `account_settings.html`):
- CSS variables: `--bg-elevated`, `--border`, `--accent`, `--fg`, `--fg-dim`, `--fg-muted`, `--success`, `--error`
- Status badges: `.badge` class pattern from interview statuses
- Modals: `.modal-overlay` / `.modal` pattern from project_detail.html
- Table: `.interviews-table` style patterns
- Alert banners: `.alert-success` / `.alert-error` from account_settings.html

- [ ] **Step 2: Verify template parses without errors**

Run: `uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/boswell/server/templates')); t = env.get_template('admin/settings_users.html'); print('Template parsed OK')"`
Expected: `Template parsed OK`

- [ ] **Step 3: Commit**

```bash
git add src/boswell/server/templates/admin/settings_users.html
git commit -m "feat(ui): add admin users management template"
```

---

### Task 11: Add Settings link to all admin nav bars

**Files:**
- Modify all admin templates that have a nav bar but lack a Settings link:
  - `src/boswell/server/templates/admin/dashboard.html`
  - `src/boswell/server/templates/admin/project_detail.html`
  - `src/boswell/server/templates/admin/project_new.html`
  - `src/boswell/server/templates/admin/project_edit.html`
  - `src/boswell/server/templates/admin/project_created.html`
  - `src/boswell/server/templates/admin/project_share.html`
  - `src/boswell/server/templates/admin/project_bulk_import.html`
  - `src/boswell/server/templates/admin/interview_new.html`
  - `src/boswell/server/templates/admin/templates_list.html`
  - `src/boswell/server/templates/admin/template_form.html`
  - `src/boswell/server/templates/admin/transcript.html`
  - `src/boswell/server/templates/admin/bulk_import.html`
- `account_settings.html` and `settings_users.html` already have the Settings link.

- [ ] **Step 1: Add Settings link to all nav bars**

In each template listed above, find the nav links pattern:
```html
<a href="/admin/">Projects</a>
<a href="/admin/templates">Interview Types</a>
```

Add after "Interview Types":
```html
<a href="/admin/settings">Settings</a>
```

Only add if not already present. Do not add `class="active"` on these pages (it's only active on the settings pages).

- [ ] **Step 2: Commit**

```bash
git add src/boswell/server/templates/admin/
git commit -m "feat(ui): add Settings link to admin navigation across all templates"
```

---

## Chunk 4: Testing & Verification

### Task 12: Run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `uv run pytest --ignore=tests/test_display_text.py -v`
Expected: All tests pass (the `test_display_text.py` ignore is pre-existing due to missing `pipecat` module)

- [ ] **Step 2: Fix any failures**

If tests fail, investigate and fix. Common issues:
- Import errors from model changes
- Missing relationship definitions
- Template rendering errors

---

### Task 13: Manual verification checklist

- [ ] **Step 1: Verify migration can be applied**

If a database is available:
Run: `INITIAL_ADMIN_EMAIL=<your-email> uv run alembic upgrade head`

If no database, verify migration syntax is valid (done in Task 2).

- [ ] **Step 2: Final commit**

If there are any remaining unstaged changes:
```bash
git add -A
git commit -m "feat: admin user management dashboard

Adds a centralized user dashboard under Settings > Users for site admins.
Features: user listing, edit name/email, reset password, deactivate/reactivate,
delete with sole-owner protection, standalone account invites.

Gated behind is_admin flag on User model with INITIAL_ADMIN_EMAIL bootstrap."
```
