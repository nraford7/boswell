# Account Management & Project Sharing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace team-based access with user accounts + per-project sharing (view/operate/collaborate/owner roles), password auth, and invite-only registration.

**Architecture:** `project_shares` table becomes the sole authorization source of truth. A central `authorization.py` module provides `get_project_role()` and `require_project_role()` used by all admin routes. Teams are removed entirely. Auth switches from magic links to email+password with invite-only registration.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Alembic, bcrypt (via passlib), itsdangerous (sessions)

**Design doc:** `docs/plans/2026-02-10-account-sharing-design.md`

---

### Task 1: Add bcrypt dependency

**Files:**
- Modify: `pyproject.toml:39-49`

**Step 1: Add passlib[bcrypt] to server dependencies**

In `pyproject.toml`, add `"passlib[bcrypt]>=1.7.4"` to the `[project.optional-dependencies] server` list after `"itsdangerous>=2.1.2"`:

```toml
server = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.25",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "jinja2>=3.1.3",
    "python-multipart>=0.0.6",
    "resend>=0.8.0",
    "itsdangerous>=2.1.2",
    "passlib[bcrypt]>=1.7.4",
]
```

**Step 2: Install**

Run: `uv sync --extra server`
Expected: Resolves and installs passlib + bcrypt

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add passlib[bcrypt] for password authentication"
```

---

### Task 2: Add ProjectRole enum and new models to models.py

**Files:**
- Modify: `src/boswell/server/models.py:1-11` (imports)
- Modify: `src/boswell/server/models.py:46-61` (add enums after existing enums)
- Modify: `src/boswell/server/models.py:86-103` (User model changes)
- Create new models after existing models

**Step 1: Write failing test for ProjectRole enum**

Create `tests/test_models_sharing.py`:

```python
"""Tests for sharing-related models and enums."""

import pytest
from boswell.server.models import ProjectRole


def test_project_role_hierarchy():
    """Roles should have a defined ordering: view < operate < collaborate < owner."""
    assert ProjectRole.view.value == "view"
    assert ProjectRole.operate.value == "operate"
    assert ProjectRole.collaborate.value == "collaborate"
    assert ProjectRole.owner.value == "owner"


def test_project_role_gte():
    """ProjectRole should support >= comparison via .level property or similar."""
    roles = [ProjectRole.view, ProjectRole.operate, ProjectRole.collaborate, ProjectRole.owner]
    for i, role in enumerate(roles):
        for j, other in enumerate(roles):
            if i >= j:
                assert role >= other
            else:
                assert not (role >= other)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_sharing.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectRole'`

**Step 3: Add ProjectRole enum to models.py**

After `JobStatus` enum (after line 56), add:

```python
class ProjectRole(str, enum.Enum):
    """Role for project sharing access control.

    Ordered from least to most privilege.
    """

    view = "view"
    operate = "operate"
    collaborate = "collaborate"
    owner = "owner"

    @property
    def level(self) -> int:
        return _ROLE_LEVELS[self]

    def __ge__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level >= other.level

    def __gt__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level > other.level

    def __le__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level <= other.level

    def __lt__(self, other):
        if not isinstance(other, ProjectRole):
            return NotImplemented
        return self.level < other.level


_ROLE_LEVELS = {
    ProjectRole.view: 0,
    ProjectRole.operate: 1,
    ProjectRole.collaborate: 2,
    ProjectRole.owner: 3,
}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models_sharing.py -v`
Expected: PASS

**Step 5: Add ProjectShare model**

Add after the `generate_magic_token` function, before the `Team` class:

```python
import hashlib  # add to imports at top


class ProjectShare(Base):
    """Per-project access grant. Authorization source of truth."""

    __tablename__ = "project_shares"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="projectrole"), nullable=False
    )
    granted_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="shares")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    granter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[granted_by])

    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_user"),
        sa.Index("ix_project_shares_user_project", "user_id", "project_id"),
        sa.Index("ix_project_shares_project_role", "project_id", "role"),
    )
```

Note: add `import sqlalchemy as sa` to imports at top.

**Step 6: Add AccountInvite model**

```python
def _hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class AccountInvite(Base):
    """Invite link for sharing a project and optionally creating an account."""

    __tablename__ = "account_invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[Optional[ProjectRole]] = mapped_column(
        Enum(ProjectRole, name="projectrole", create_constraint=False), nullable=True
    )
    claimed_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    inviter: Mapped["User"] = relationship("User", foreign_keys=[invited_by])
    project: Mapped[Optional["Project"]] = relationship("Project")
    claimed_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[claimed_by_user_id])

    __table_args__ = (
        sa.CheckConstraint(
            "(project_id IS NULL AND role IS NULL) OR (project_id IS NOT NULL AND role IS NOT NULL)",
            name="ck_invite_project_role_together",
        ),
        sa.Index("ix_invite_email_status", "email", "claimed_at", "revoked_at", "expires_at"),
        sa.Index("ix_invite_project_status", "project_id", "claimed_at", "revoked_at"),
    )
```

**Step 7: Add password_hash and email_verified_at to User model**

Modify the User class (currently lines 86-103) to add two fields after `name`:

```python
class User(Base):
    """A user who can manage interviews."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    team: Mapped[Optional["Team"]] = relationship("Team", back_populates="users")
```

Note: `team_id` becomes nullable with `SET NULL` instead of `CASCADE`. The `Team` relationship becomes `Optional`.

**Step 8: Add `shares` relationship to Project model**

Add after the existing relationships in the Project class (after line 186):

```python
    shares: Mapped[list["ProjectShare"]] = relationship(
        "ProjectShare", back_populates="project", cascade="all, delete-orphan"
    )
```

**Step 9: Run tests**

Run: `uv run pytest tests/test_models_sharing.py -v`
Expected: PASS

**Step 10: Commit**

```bash
git add src/boswell/server/models.py tests/test_models_sharing.py
git commit -m "feat: add ProjectShare, AccountInvite models and ProjectRole enum"
```

---

### Task 3: Alembic migration — Phase A additive schema

**Files:**
- Create: `src/boswell/server/migrations/versions/g1_add_sharing_tables.py`

**Step 1: Generate migration**

Run: `cd /Users/noahraford/Projects/boswell && uv run alembic revision --autogenerate -m "add sharing tables and user auth fields"`

If autogenerate doesn't capture everything, manually create the migration.

**Step 2: Verify migration content**

The migration should:
1. Create `projectrole` enum type
2. Add `password_hash` (TEXT, nullable) to `users`
3. Add `email_verified_at` (TIMESTAMPTZ, nullable) to `users`
4. Make `users.team_id` nullable (ALTER COLUMN DROP NOT NULL)
5. Change `users.team_id` FK ondelete to SET NULL
6. Create `project_shares` table with all columns, constraints, indexes
7. Create `account_invites` table with all columns, constraints, indexes

If autogenerate misses any changes, edit the generated migration to include them. The critical changes are:

```python
def upgrade() -> None:
    # Create enum type
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE projectrole AS ENUM ('view', 'operate', 'collaborate', 'owner');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    project_role = postgresql.ENUM(
        "view", "operate", "collaborate", "owner",
        name="projectrole", create_type=False,
    )

    # Add user auth columns
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))

    # Make team_id nullable on users
    op.alter_column("users", "team_id", existing_type=postgresql.UUID(), nullable=True)

    # Create project_shares
    op.create_table(
        "project_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", project_role, nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_project_shares_project_user", "project_shares", ["project_id", "user_id"])
    op.create_index("ix_project_shares_user_project", "project_shares", ["user_id", "project_id"])
    op.create_index("ix_project_shares_project_role", "project_shares", ["project_id", "role"])

    # Create account_invites
    op.create_table(
        "account_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", project_role, nullable=True),
        sa.Column("claimed_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_invite_project_role_together", "account_invites",
        "(project_id IS NULL AND role IS NULL) OR (project_id IS NOT NULL AND role IS NOT NULL)",
    )
    op.create_index("ix_invite_email_status", "account_invites",
                    ["email", "claimed_at", "revoked_at", "expires_at"])
    op.create_index("ix_invite_project_status", "account_invites",
                    ["project_id", "claimed_at", "revoked_at"])
```

**Step 3: Run migration**

Run: `uv run alembic upgrade head`
Expected: Migration applies successfully

**Step 4: Commit**

```bash
git add src/boswell/server/migrations/
git commit -m "migration: add project_shares, account_invites tables and user auth columns"
```

---

### Task 4: Authorization module

**Files:**
- Create: `src/boswell/server/authorization.py`
- Create: `tests/test_authorization.py`

**Step 1: Write failing tests**

Create `tests/test_authorization.py`:

```python
"""Tests for the authorization module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from boswell.server.authorization import (
    get_project_role,
    check_project_access,
    assert_not_last_owner,
)
from boswell.server.models import ProjectRole


@pytest.mark.asyncio
async def test_get_project_role_returns_role_for_shared_user():
    """get_project_role returns the role when user has a share."""
    user_id = uuid4()
    project_id = uuid4()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.collaborate
    mock_db.execute.return_value = mock_result

    role = await get_project_role(user_id, project_id, mock_db)
    assert role == ProjectRole.collaborate


@pytest.mark.asyncio
async def test_get_project_role_returns_none_for_no_access():
    """get_project_role returns None when user has no share."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    role = await get_project_role(uuid4(), uuid4(), mock_db)
    assert role is None


@pytest.mark.asyncio
async def test_check_project_access_passes_when_role_sufficient():
    """check_project_access should not raise when role >= min_role."""
    user_id = uuid4()
    project_id = uuid4()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.owner
    mock_db.execute.return_value = mock_result

    # Should not raise
    await check_project_access(user_id, project_id, ProjectRole.view, mock_db)


@pytest.mark.asyncio
async def test_check_project_access_raises_404_when_no_access():
    """check_project_access should raise 404 when user has no share."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(uuid4(), uuid4(), ProjectRole.view, mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_check_project_access_raises_403_when_role_insufficient():
    """check_project_access should raise 403 when role < min_role."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.view
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(uuid4(), uuid4(), ProjectRole.owner, mock_db)
    assert exc_info.value.status_code == 403
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_authorization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'boswell.server.authorization'`

**Step 3: Implement authorization.py**

Create `src/boswell/server/authorization.py`:

```python
"""Central authorization module.

project_shares is the single source of truth for project access.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boswell.server.models import ProjectRole, ProjectShare


async def get_project_role(
    user_id: UUID, project_id: UUID, db: AsyncSession
) -> Optional[ProjectRole]:
    """Look up the user's role on a project.

    Returns None if the user has no access.
    """
    result = await db.execute(
        select(ProjectShare.role)
        .where(ProjectShare.project_id == project_id)
        .where(ProjectShare.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def check_project_access(
    user_id: UUID,
    project_id: UUID,
    min_role: ProjectRole,
    db: AsyncSession,
) -> ProjectRole:
    """Verify user has at least min_role on the project.

    Returns the actual role if access is granted.
    Raises 404 if no access at all (don't leak existence).
    Raises 403 if access exists but insufficient.
    """
    role = await get_project_role(user_id, project_id, db)
    if role is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not (role >= min_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return role


async def assert_not_last_owner(
    project_id: UUID, user_id: UUID, db: AsyncSession
) -> None:
    """Raise if user_id is the only owner of the project.

    Call before downgrading or removing an owner.
    """
    from sqlalchemy import func as sa_func

    result = await db.execute(
        select(sa_func.count())
        .select_from(ProjectShare)
        .where(ProjectShare.project_id == project_id)
        .where(ProjectShare.role == ProjectRole.owner)
        .where(ProjectShare.user_id != user_id)
    )
    other_owners = result.scalar_one()
    if other_owners == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove or downgrade the last owner",
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_authorization.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/boswell/server/authorization.py tests/test_authorization.py
git commit -m "feat: add central authorization module with role-based project access"
```

---

### Task 5: Password auth helpers

**Files:**
- Modify: `src/boswell/server/routes/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write failing tests**

Create `tests/test_auth.py`:

```python
"""Tests for password authentication helpers."""

import pytest
from boswell.server.routes.auth import hash_password, verify_password


def test_hash_and_verify_password():
    """Hashing a password then verifying it should succeed."""
    pw = "secureP@ssword123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)


def test_wrong_password_fails():
    """Verifying with wrong password should fail."""
    hashed = hash_password("correct-password")
    assert not verify_password("wrong-password", hashed)


def test_password_hashes_are_unique():
    """Two hashes of the same password should differ (random salt)."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'hash_password'`

**Step 3: Add password helpers to auth.py**

Add after the imports (around line 12), add:

```python
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return _pwd_context.verify(password, password_hash)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/boswell/server/routes/auth.py tests/test_auth.py
git commit -m "feat: add bcrypt password hashing helpers"
```

---

### Task 6: Password login route

**Files:**
- Modify: `src/boswell/server/routes/auth.py`
- Modify: `tests/test_auth.py`

**Step 1: Write failing test**

Add to `tests/test_auth.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from boswell.server.routes.auth import hash_password


@pytest.mark.asyncio
async def test_login_post_with_valid_password():
    """POST /admin/login with correct email+password sets session cookie."""
    from fastapi.testclient import TestClient
    # This test will be an integration test once the route exists
    # For now, test the route function directly
    pass  # Placeholder for integration test
```

**Step 2: Modify POST /admin/login to support password auth**

Replace the `login_submit` route in `auth.py` (lines 128-185) with a version that checks for a `password` form field. If password is provided, authenticate directly. If not, fall back to magic link flow:

```python
@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Handle login — password auth or magic link fallback."""
    normalized_email = email.strip().lower()

    # Look up user
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    # Password login path
    if password:
        if not user or not user.password_hash:
            return templates.TemplateResponse(
                request=request,
                name="admin/login.html",
                context={"message": "Invalid email or password."},
            )
        if not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request=request,
                name="admin/login.html",
                context={"message": "Invalid email or password."},
            )
        # Success — create session
        session_token = create_session_token(user.id)
        response = RedirectResponse(url="/admin/", status_code=303)
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=604800,
        )
        return response

    # Magic link fallback (existing behavior for users without passwords)
    settings = get_settings()
    admin_emails_lower = [e.lower() for e in settings.admin_emails] if settings.admin_emails else []
    if admin_emails_lower and normalized_email not in admin_emails_lower:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Email not authorized."},
        )

    if not user:
        team = Team(name=f"{normalized_email}'s Team")
        db.add(team)
        await db.flush()
        name = normalized_email.split("@")[0]
        user = User(team_id=team.id, email=normalized_email, name=name)
        db.add(user)
        await db.flush()

    token = create_login_token(normalized_email)
    login_link = f"{settings.base_url}/admin/verify?token={token}"
    email_sent = await send_admin_login_email(to=normalized_email, login_link=login_link)

    if email_sent:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Check your email for a login link."},
        )
    else:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": f"Email failed. Login link: {login_link}"},
        )
```

Note: add `from typing import Optional` if not already imported.

**Step 3: Run existing tests to check no regressions**

Run: `uv run pytest tests/ -v`
Expected: All existing tests still pass

**Step 4: Commit**

```bash
git add src/boswell/server/routes/auth.py tests/test_auth.py
git commit -m "feat: add password login alongside magic link fallback"
```

---

### Task 7: Invite claim route (account creation + project share)

**Files:**
- Modify: `src/boswell/server/routes/auth.py`
- Create: `tests/test_invite_claim.py`

**Step 1: Write failing tests**

Create `tests/test_invite_claim.py`:

```python
"""Tests for invite claim logic."""

import pytest
import hashlib
import hmac
from boswell.server.models import _hash_token


def test_hash_token_is_sha256():
    """_hash_token should return hex SHA-256 of input."""
    raw = "test-token-abc"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert _hash_token(raw) == expected
    assert len(_hash_token(raw)) == 64


def test_hash_token_deterministic():
    """Same input should always produce same hash."""
    assert _hash_token("foo") == _hash_token("foo")


def test_hash_token_different_inputs():
    """Different inputs should produce different hashes."""
    assert _hash_token("a") != _hash_token("b")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_invite_claim.py -v`
Expected: FAIL — `ImportError: cannot import name '_hash_token'`

**Step 3: Implement invite claim route**

Add to `auth.py` after the logout route:

```python
@router.get("/invite/{token}")
async def invite_page(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Show the invite claim page."""
    from boswell.server.models import AccountInvite, _hash_token

    token_hash = _hash_token(token)
    result = await db.execute(
        select(AccountInvite).where(AccountInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Invalid invite link."},
        )

    now = datetime.now(timezone.utc)
    if invite.claimed_at or invite.revoked_at or invite.expires_at < now:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "This invite has expired or already been used."},
        )

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == invite.email))
    existing_user = existing.scalar_one_or_none()

    return templates.TemplateResponse(
        request=request,
        name="admin/invite_claim.html",
        context={
            "invite": invite,
            "existing_user": existing_user is not None,
            "email": invite.email,
            "token": token,
        },
    )


@router.post("/invite/{token}")
async def claim_invite(
    request: Request,
    token: str,
    name: str = Form(""),
    password: str = Form(""),
    existing_password: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Claim an invite — create account or link existing."""
    from boswell.server.models import AccountInvite, ProjectShare, ProjectRole, _hash_token

    token_hash = _hash_token(token)
    result = await db.execute(
        select(AccountInvite).where(AccountInvite.token_hash == token_hash)
    )
    invite = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if not invite or invite.claimed_at or invite.revoked_at or invite.expires_at < now:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Invalid or expired invite."},
        )

    # Check for existing user
    existing = await db.execute(select(User).where(User.email == invite.email))
    user = existing.scalar_one_or_none()

    if user:
        # Existing user — verify password
        if not user.password_hash or not existing_password:
            return templates.TemplateResponse(
                request=request,
                name="admin/invite_claim.html",
                context={
                    "invite": invite,
                    "existing_user": True,
                    "email": invite.email,
                    "token": token,
                    "message": "Please enter your password to claim this invite.",
                },
            )
        if not verify_password(existing_password, user.password_hash):
            return templates.TemplateResponse(
                request=request,
                name="admin/invite_claim.html",
                context={
                    "invite": invite,
                    "existing_user": True,
                    "email": invite.email,
                    "token": token,
                    "message": "Incorrect password.",
                },
            )
    else:
        # New user — create account
        if not name.strip() or not password:
            return templates.TemplateResponse(
                request=request,
                name="admin/invite_claim.html",
                context={
                    "invite": invite,
                    "existing_user": False,
                    "email": invite.email,
                    "token": token,
                    "message": "Name and password are required.",
                },
            )
        user = User(
            email=invite.email,
            name=name.strip(),
            password_hash=hash_password(password),
            email_verified_at=now,  # Verified via invite
        )
        db.add(user)
        await db.flush()

    # Grant project share if invite has one (atomic with claim)
    if invite.project_id and invite.role:
        # Upsert: if share exists, update role; otherwise insert
        existing_share = await db.execute(
            select(ProjectShare)
            .where(ProjectShare.project_id == invite.project_id)
            .where(ProjectShare.user_id == user.id)
        )
        share = existing_share.scalar_one_or_none()
        if share:
            share.role = invite.role
            share.updated_at = now
        else:
            db.add(ProjectShare(
                project_id=invite.project_id,
                user_id=user.id,
                role=invite.role,
                granted_by=invite.invited_by,
            ))

    # Mark invite claimed
    invite.claimed_at = now
    invite.claimed_by_user_id = user.id

    # Create session
    session_token = create_session_token(user.id)
    response = RedirectResponse(url="/admin/", status_code=303)
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=604800,
    )
    return response
```

Add import at top of auth.py:

```python
from datetime import datetime, timezone
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_invite_claim.py tests/test_auth.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/boswell/server/routes/auth.py src/boswell/server/models.py tests/test_invite_claim.py
git commit -m "feat: add invite claim route for account creation and project sharing"
```

---

### Task 8: Password setup gate for existing users

**Files:**
- Modify: `src/boswell/server/routes/auth.py`
- Modify: `src/boswell/server/routes/admin.py:52-76` (require_auth)

**Step 1: Add password setup route to auth.py**

```python
@router.get("/set-password")
async def set_password_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
):
    """Show password setup page for users who don't have one yet."""
    if not user:
        return RedirectResponse(url="/admin/login", status_code=303)
    if user.password_hash:
        return RedirectResponse(url="/admin/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/set_password.html",
        context={"user": user, "message": None},
    )


@router.post("/set-password")
async def set_password_submit(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Set password for existing user migrating from magic link."""
    if not user:
        return RedirectResponse(url="/admin/login", status_code=303)

    if password != password_confirm:
        return templates.TemplateResponse(
            request=request,
            name="admin/set_password.html",
            context={"user": user, "message": "Passwords do not match."},
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="admin/set_password.html",
            context={"user": user, "message": "Password must be at least 8 characters."},
        )

    user.password_hash = hash_password(password)
    return RedirectResponse(url="/admin/", status_code=303)
```

**Step 2: Update require_auth to gate on password**

In `admin.py` (lines 52-76), modify `require_auth` to redirect passwordless users:

```python
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
    if not user.password_hash:
        path = request.url.path
        if path != "/admin/set-password":
            raise HTTPException(
                status_code=307,
                headers={"Location": "/admin/set-password"},
            )
    return user
```

**Step 3: Run existing tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/boswell/server/routes/auth.py src/boswell/server/routes/admin.py
git commit -m "feat: add password setup gate for migrating users"
```

---

### Task 9: Backfill migration — populate project_shares from legacy data

**Files:**
- Create: `src/boswell/server/migrations/versions/g2_backfill_project_shares.py`

**Step 1: Create data migration**

```python
"""Backfill project_shares from legacy team ownership.

For each project:
1. created_by user gets 'owner' role
2. Other users in same team get 'view' role
3. If created_by is NULL, earliest team user becomes owner

Revision ID: g2
Revises: g1 (previous migration)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "g2_backfill"
down_revision = "<previous_revision_id>"  # Set to actual g1 revision ID


def upgrade() -> None:
    conn = op.get_bind()

    # Get all projects with their team_id and created_by
    projects = conn.execute(sa.text("""
        SELECT id, team_id, created_by FROM interviews WHERE team_id IS NOT NULL
    """)).fetchall()

    for project in projects:
        project_id, team_id, created_by = project

        # Get all users in this team
        team_users = conn.execute(sa.text("""
            SELECT id, created_at FROM users WHERE team_id = :team_id ORDER BY created_at, id
        """), {"team_id": team_id}).fetchall()

        if not team_users:
            continue

        # Determine owner
        owner_id = created_by
        if not owner_id:
            owner_id = team_users[0][0]  # Earliest user by created_at, then UUID

        # Insert owner share
        conn.execute(sa.text("""
            INSERT INTO project_shares (id, project_id, user_id, role, created_at, updated_at)
            VALUES (gen_random_uuid(), :project_id, :user_id, 'owner', NOW(), NOW())
            ON CONFLICT (project_id, user_id) DO NOTHING
        """), {"project_id": project_id, "user_id": owner_id})

        # Insert view shares for other team members
        for user_row in team_users:
            user_id = user_row[0]
            if user_id != owner_id:
                conn.execute(sa.text("""
                    INSERT INTO project_shares (id, project_id, user_id, role, created_at, updated_at)
                    VALUES (gen_random_uuid(), :project_id, :user_id, 'view', NOW(), NOW())
                    ON CONFLICT (project_id, user_id) DO NOTHING
                """), {"project_id": project_id, "user_id": user_id})

    # Also backfill template created_by from team ownership
    # Templates don't have created_by yet, so we need to add that column first
    op.add_column("interview_templates",
                  sa.Column("created_by", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))

    # Set created_by to earliest user in same team
    conn.execute(sa.text("""
        UPDATE interview_templates t
        SET created_by = (
            SELECT u.id FROM users u
            WHERE u.team_id = t.team_id
            ORDER BY u.created_at, u.id
            LIMIT 1
        )
        WHERE t.created_by IS NULL
    """))

    # Verify invariant: every project has at least one owner
    orphans = conn.execute(sa.text("""
        SELECT i.id FROM interviews i
        WHERE i.team_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM project_shares ps
            WHERE ps.project_id = i.id AND ps.role = 'owner'
        )
    """)).fetchall()

    if orphans:
        raise Exception(
            f"MIGRATION FAILED: {len(orphans)} projects have no owner after backfill. "
            f"IDs: {[str(o[0]) for o in orphans[:10]]}"
        )


def downgrade() -> None:
    op.drop_column("interview_templates", "created_by")
    op.execute("DELETE FROM project_shares")
```

**Step 2: Run migration**

Run: `uv run alembic upgrade head`
Expected: Backfill completes, all projects have owners

**Step 3: Commit**

```bash
git add src/boswell/server/migrations/
git commit -m "migration: backfill project_shares from legacy team data"
```

---

### Task 10: Replace team_id checks in admin.py — dashboard and project list

**Files:**
- Modify: `src/boswell/server/routes/admin.py:84-100` (dashboard)
- Modify: `src/boswell/server/routes/admin.py` imports

**Step 1: Update imports**

Add to admin.py imports:

```python
from boswell.server.authorization import get_project_role, check_project_access
from boswell.server.models import ProjectRole, ProjectShare
```

**Step 2: Replace dashboard query**

Replace the dashboard route (lines 84-100 and the query at line 92-96):

Old:
```python
    result = await db.execute(
        select(Project)
        .where(Project.team_id == user.team_id)
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
```

New:
```python
    # My Projects (where user is owner)
    owned_result = await db.execute(
        select(Project)
        .join(ProjectShare, ProjectShare.project_id == Project.id)
        .where(ProjectShare.user_id == user.id)
        .where(ProjectShare.role == ProjectRole.owner)
        .order_by(Project.created_at.desc())
    )
    owned_projects = owned_result.scalars().all()

    # Shared with me (non-owner roles)
    shared_result = await db.execute(
        select(Project)
        .join(ProjectShare, ProjectShare.project_id == Project.id)
        .where(ProjectShare.user_id == user.id)
        .where(ProjectShare.role != ProjectRole.owner)
        .order_by(Project.created_at.desc())
    )
    shared_projects = shared_result.scalars().all()

    projects = owned_projects + shared_projects
```

Update the template context to pass `owned_projects` and `shared_projects` separately for the dashboard sections.

**Step 3: Run existing tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "refactor: replace team_id dashboard query with project_shares"
```

---

### Task 11: Replace all remaining team_id checks in admin.py

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (30 locations identified by grep)

This is the largest task. The pattern is consistent across all 30 locations:

**For project access checks** (lines 291, 327, 355, 383, 433, 488, 1032, 1062, 1267, 1438, 1487, 1552, 1607, 1674, 1892, 1947, 2010, 2099):

Replace:
```python
.where(Project.team_id == user.team_id)
```
or
```python
if project is None or project.team_id != user.team_id:
```

With a call to `check_project_access()`:
```python
await check_project_access(user.id, project_id, ProjectRole.view, db)
# or ProjectRole.operate / ProjectRole.collaborate / ProjectRole.owner depending on the action
```

Use these role mappings per design doc:
- View project, transcripts, analyses → `ProjectRole.view`
- Start/manage interviews → `ProjectRole.operate`
- Edit project config, questions, add/remove guests → `ProjectRole.collaborate`
- Manage sharing, delete project → `ProjectRole.owner`

**For template ownership checks** (lines 139, 226, 297, 398, 443, 651, 806, 844, 959, 1203, 1902, 1976):

Replace:
```python
.where(InterviewTemplate.team_id == user.team_id)
```

With:
```python
.where(InterviewTemplate.created_by == user.id)
```

**For project creation** (line 235, 582, 1282):

Replace:
```python
team_id=user.team_id,
```

Remove team_id assignment. After creating the project, insert an owner share:

```python
project = Project(topic=topic, created_by=user.id, ...)
db.add(project)
await db.flush()
db.add(ProjectShare(project_id=project.id, user_id=user.id, role=ProjectRole.owner, granted_by=user.id))
```

**For template creation** (line 778):

Replace `team_id=user.team_id` with `created_by=user.id`.

**For interview access via project** (lines 1346, 1399, 1723, 1775):

Replace:
```python
if interview.project.team_id != user.team_id:
```

With:
```python
await check_project_access(user.id, interview.project_id, ProjectRole.view, db)
```

**Step 1: Work through each location systematically**

Process route by route, testing after each batch of related changes. Group by functionality:

1. Project detail/view routes (view role)
2. Project edit routes (collaborate role)
3. Interview management routes (operate role)
4. Project creation routes (owner share insertion)
5. Template routes (created_by ownership)
6. Delete routes (owner role)
7. Transcript routes (view role)

**Step 2: Run tests after each batch**

Run: `uv run pytest tests/ -v`
Expected: All pass after each batch

**Step 3: Verify no remaining team_id references in admin.py**

Run: `grep -n "team_id" src/boswell/server/routes/admin.py`
Expected: Zero matches (or only in comments being removed)

**Step 4: Commit**

```bash
git add src/boswell/server/routes/admin.py
git commit -m "refactor: replace all team_id authorization with project_shares role checks"
```

---

### Task 12: Sharing UI — project sharing routes

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (add new routes)
- Create: `src/boswell/server/templates/admin/project_share.html`

**Step 1: Add sharing routes to admin.py**

Add these routes:

```python
# GET /admin/projects/{id}/sharing — view sharing settings (owner only)
# POST /admin/projects/{id}/sharing — share with email (owner only)
# POST /admin/projects/{id}/sharing/{share_id}/update — change role (owner only)
# POST /admin/projects/{id}/sharing/{share_id}/revoke — revoke access (owner only)
# POST /admin/projects/{id}/sharing/invites/{invite_id}/revoke — revoke pending invite (owner only)
```

Implementation for the share route:

```python
@router.get("/projects/{project_id}/sharing")
async def project_sharing(
    request: Request,
    project_id: UUID,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    """View project sharing settings."""
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

    return templates.TemplateResponse(
        request=request,
        name="admin/project_share.html",
        context={
            "user": user,
            "project": project,
            "shares": shares,
            "pending_invites": pending_invites,
            "roles": [r.value for r in ProjectRole],
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
        from boswell.server.models import AccountInvite, _hash_token
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

    return RedirectResponse(
        url=f"/admin/projects/{project_id}/sharing" + (f"?invite_link={invite_link}" if invite_link else ""),
        status_code=303,
    )
```

**Step 2: Create the sharing template**

Create `src/boswell/server/templates/admin/project_share.html` with:
- List of current collaborators with role badges and change/revoke buttons
- Pending invites with copyable link and revoke button
- "Add collaborator" form with email input and role dropdown
- If `invite_link` query param present, show copyable link prominently

**Step 3: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/templates/admin/project_share.html
git commit -m "feat: add project sharing UI routes and template"
```

---

### Task 13: Dashboard template — "My Projects" and "Shared with me" sections

**Files:**
- Modify: `src/boswell/server/templates/admin/dashboard.html`

**Step 1: Update dashboard template**

Split the project list into two sections:

```html
<!-- My Projects -->
<h2>My Projects</h2>
{% for project in owned_projects %}
  <!-- existing project card markup -->
{% endfor %}

<!-- Shared with me -->
{% if shared_projects %}
<h2>Shared with me</h2>
{% for project in shared_projects %}
  <!-- project card with role badge and "shared by" attribution -->
{% endfor %}
{% endif %}
```

For each shared project, show:
- Role badge (view/operate/collaborate)
- "Shared by [name]" text
- Actions gated by role (e.g., no edit button for view-only)

**Step 2: Verify in browser**

Run dev server, check dashboard renders both sections correctly.

**Step 3: Commit**

```bash
git add src/boswell/server/templates/admin/dashboard.html
git commit -m "feat: split dashboard into My Projects and Shared with me sections"
```

---

### Task 14: Auth templates — login, set-password, invite-claim

**Files:**
- Modify: `src/boswell/server/templates/admin/login.html` (add password field)
- Create: `src/boswell/server/templates/admin/set_password.html`
- Create: `src/boswell/server/templates/admin/invite_claim.html`

**Step 1: Update login.html**

Add password field to the login form. The form should have email + password fields, with a submit button. Keep the magic link option as a secondary fallback link.

**Step 2: Create set_password.html**

Simple form with: password, confirm password, submit button. Message display area.

**Step 3: Create invite_claim.html**

Two modes:
- **New user**: Shows email (locked), name field, password field, submit
- **Existing user**: Shows email (locked), password field for verification, submit

**Step 4: Commit**

```bash
git add src/boswell/server/templates/admin/
git commit -m "feat: add login, set-password, and invite-claim templates"
```

---

### Task 15: Account settings page

**Files:**
- Modify: `src/boswell/server/routes/admin.py` (add settings routes)
- Create: `src/boswell/server/templates/admin/account_settings.html`

**Step 1: Add routes**

```python
@router.get("/settings")
async def account_settings(
    request: Request,
    user: User = Depends(require_auth),
):
    """Account settings page."""
    return templates.TemplateResponse(
        request=request,
        name="admin/account_settings.html",
        context={"user": user, "message": None},
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
    from boswell.server.routes.auth import hash_password, verify_password

    user.name = name.strip()

    if new_password:
        if not current_password or not verify_password(current_password, user.password_hash):
            return templates.TemplateResponse(
                request=request,
                name="admin/account_settings.html",
                context={"user": user, "message": "Current password is incorrect."},
            )
        if len(new_password) < 8:
            return templates.TemplateResponse(
                request=request,
                name="admin/account_settings.html",
                context={"user": user, "message": "New password must be at least 8 characters."},
            )
        user.password_hash = hash_password(new_password)

    return templates.TemplateResponse(
        request=request,
        name="admin/account_settings.html",
        context={"user": user, "message": "Settings updated."},
    )
```

**Step 2: Create template with name, current password, new password fields**

**Step 3: Commit**

```bash
git add src/boswell/server/routes/admin.py src/boswell/server/templates/admin/account_settings.html
git commit -m "feat: add account settings page for name and password changes"
```

---

### Task 16: Remove ADMIN_EMAILS config requirement

**Files:**
- Modify: `src/boswell/server/config.py:42` (remove admin_emails)
- Modify: `src/boswell/server/routes/auth.py` (remove allowlist check)

**Step 1: Remove admin_emails from Settings**

In `config.py`, remove the `admin_emails` field and its parsing.

**Step 2: Remove allowlist check from login route**

In `auth.py`, remove the block at lines 141-148 that checks `settings.admin_emails`.

**Step 3: Remove auto-provisioning of teams**

In `auth.py`, remove the block at lines 154-164 that creates a Team + User on first login. The magic link path should only work for existing users (who haven't set passwords yet).

**Step 4: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/boswell/server/config.py src/boswell/server/routes/auth.py
git commit -m "refactor: remove ADMIN_EMAILS allowlist and auto-provisioning"
```

---

### Task 17: Cleanup migration — drop teams

**Files:**
- Create: `src/boswell/server/migrations/versions/g3_drop_teams.py`
- Modify: `src/boswell/server/models.py` (remove Team model and all team_id columns)

**Step 1: Create migration**

```python
"""Drop teams table and all team_id columns.

Phase F of migration strategy.
"""

def upgrade() -> None:
    # Drop team_id foreign keys and columns
    op.drop_constraint("users_team_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "team_id")

    op.drop_constraint("interviews_team_id_fkey", "interviews", type_="foreignkey")
    op.drop_column("interviews", "team_id")

    op.drop_constraint("interview_templates_team_id_fkey", "interview_templates", type_="foreignkey")
    op.drop_column("interview_templates", "team_id")

    # Drop teams table
    op.drop_table("teams")
```

**Step 2: Remove Team model from models.py**

Delete the entire `Team` class (lines 63-83) and remove all `team_id` fields and `team` relationships from User, Project, and InterviewTemplate models.

**Step 3: Remove Team import from auth.py**

Line 17 of auth.py: remove `Team` from the import.

**Step 4: Run migration**

Run: `uv run alembic upgrade head`
Expected: Clean migration

**Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/boswell/server/models.py src/boswell/server/routes/auth.py src/boswell/server/migrations/
git commit -m "cleanup: drop teams table and all team_id references"
```

---

### Task 18: Integration tests for full sharing workflow

**Files:**
- Create: `tests/test_sharing_integration.py`

**Step 1: Write integration tests**

```python
"""Integration tests for the full sharing workflow.

Requires DATABASE_URL to be set.
"""

import os
import pytest
from uuid import uuid4

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


@pytest.mark.asyncio
async def test_owner_share_creates_project_share_row():
    """Sharing a project creates a project_shares row for the target user."""
    pass  # Implement with test DB setup


@pytest.mark.asyncio
async def test_invite_claim_grants_share_atomically():
    """Claiming an invite creates user + share in one transaction."""
    pass


@pytest.mark.asyncio
async def test_last_owner_cannot_be_downgraded():
    """Downgrading the only owner should fail with 400."""
    pass


@pytest.mark.asyncio
async def test_view_role_cannot_edit_project():
    """A user with view role should get 403 on edit routes."""
    pass


@pytest.mark.asyncio
async def test_collaborate_role_can_edit_project():
    """A user with collaborate role can edit project config."""
    pass


@pytest.mark.asyncio
async def test_operate_role_can_start_interview():
    """A user with operate role can start/manage interviews."""
    pass


@pytest.mark.asyncio
async def test_no_share_returns_404():
    """A user with no share should get 404 for the project."""
    pass


@pytest.mark.asyncio
async def test_every_project_has_owner_after_migration():
    """After backfill, every project should have >= 1 owner."""
    pass
```

**Step 2: Commit**

```bash
git add tests/test_sharing_integration.py
git commit -m "test: add integration test scaffolding for sharing workflow"
```

---

### Task 19: Final verification and cleanup

**Files:**
- All modified files

**Step 1: Verify no remaining team_id references in source code**

Run: `grep -rn "team_id" src/boswell/server/ --include="*.py" | grep -v migrations | grep -v "\.pyc"`
Expected: Zero matches

**Step 2: Verify all routes have authorization checks**

Run: `grep -n "def " src/boswell/server/routes/admin.py | head -50`
Cross-reference every route function with a `check_project_access` or `require_auth` call.

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup and verification for account sharing feature"
```

---

## Summary of all tasks

| # | Task | Key files | Est. complexity |
|---|------|-----------|-----------------|
| 1 | Add bcrypt dependency | `pyproject.toml` | Trivial |
| 2 | ProjectRole enum + new models | `models.py` | Medium |
| 3 | Alembic migration — additive schema | migration file | Medium |
| 4 | Authorization module | `authorization.py` | Medium |
| 5 | Password auth helpers | `auth.py` | Small |
| 6 | Password login route | `auth.py` | Medium |
| 7 | Invite claim route | `auth.py` | Large |
| 8 | Password setup gate | `auth.py`, `admin.py` | Small |
| 9 | Backfill migration | migration file | Medium |
| 10 | Dashboard → project_shares | `admin.py` | Medium |
| 11 | Replace ALL team_id checks | `admin.py` (30 locations) | **Large** |
| 12 | Sharing UI routes | `admin.py`, template | Large |
| 13 | Dashboard template split | `dashboard.html` | Small |
| 14 | Auth templates | 3 templates | Medium |
| 15 | Account settings page | `admin.py`, template | Small |
| 16 | Remove ADMIN_EMAILS | `config.py`, `auth.py` | Small |
| 17 | Drop teams cleanup | migration, `models.py` | Medium |
| 18 | Integration tests | `test_sharing_integration.py` | Medium |
| 19 | Final verification | All files | Small |
