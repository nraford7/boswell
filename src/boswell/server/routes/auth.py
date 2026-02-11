# src/boswell/server/routes/auth.py
"""Authentication routes with magic link login."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boswell.server.config import get_settings
from boswell.server.database import get_session
from boswell.server.email import send_admin_login_email
from boswell.server.main import templates
from boswell.server.models import User, AccountInvite, ProjectShare, ProjectRole, _hash_token
from boswell.server.auth_utils import hash_password, verify_password

router = APIRouter()


# -----------------------------------------------------------------------------
# Token Functions
# -----------------------------------------------------------------------------


def get_serializer() -> URLSafeTimedSerializer:
    """Get a URL-safe timed serializer using the secret key."""
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key)


def create_login_token(email: str) -> str:
    """Create a login token for the given email address."""
    serializer = get_serializer()
    return serializer.dumps(email, salt="login")


def verify_login_token(token: str, max_age: int = 3600) -> Optional[str]:
    """Verify a login token and return the email if valid.

    Args:
        token: The token to verify.
        max_age: Maximum age in seconds (default: 1 hour).

    Returns:
        The email address if valid, None otherwise.
    """
    serializer = get_serializer()
    try:
        return serializer.loads(token, salt="login", max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def create_session_token(user_id: UUID) -> str:
    """Create a session token for the given user ID."""
    serializer = get_serializer()
    return serializer.dumps(str(user_id), salt="session")


def verify_session_token(token: str, max_age: int = 604800) -> Optional[str]:
    """Verify a session token and return the user ID if valid.

    Args:
        token: The token to verify.
        max_age: Maximum age in seconds (default: 7 days).

    Returns:
        The user ID as a string if valid, None otherwise.
    """
    serializer = get_serializer()
    try:
        return serializer.loads(token, salt="session", max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_session)
) -> Optional[User]:
    """Get the current user from the session cookie.

    Args:
        request: The incoming request.
        db: Database session.

    Returns:
        The User object if authenticated, None otherwise.
    """
    session_token = request.cookies.get("session")
    if not session_token:
        return None

    user_id_str = verify_session_token(session_token)
    if not user_id_str:
        return None

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and user.deactivated_at is not None:
        return None
    return user


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@router.get("/login")
async def login_page(request: Request):
    """Show the login page."""
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"message": None},
    )


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
        if user.deactivated_at is not None:
            return templates.TemplateResponse(
                request=request,
                name="admin/login.html",
                context={"message": "This account has been deactivated."},
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

    # Magic link fallback (for existing passwordless users only)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Account not found. You need an invite link to create an account."},
        )

    settings = get_settings()
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


@router.get("/verify")
async def verify_token(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Verify the login token and create a session."""
    email = verify_login_token(token)
    if not email:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Invalid or expired token. Please try again."},
        )

    # Get the user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "User not found. Please try again."},
        )

    if user.deactivated_at is not None:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "This account has been deactivated."},
        )

    # Create session token and redirect
    session_token = create_session_token(user.id)
    response = RedirectResponse(url="/admin/", status_code=303)
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=604800,  # 7 days
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie and redirect to login."""
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key="session")
    return response


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
    if user.password_hash:
        return RedirectResponse(url="/admin/", status_code=303)

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

    if len(password.encode("utf-8")) > 72:
        return templates.TemplateResponse(
            request=request,
            name="admin/set_password.html",
            context={"user": user, "message": "Password must be 72 bytes or fewer."},
        )

    user.password_hash = hash_password(password)
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


@router.get("/invite/{token}")
async def invite_page(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
):
    """Show the invite claim page."""
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
            "message": None,
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
        if len(password.encode("utf-8")) > 72:
            return templates.TemplateResponse(
                request=request,
                name="admin/invite_claim.html",
                context={
                    "invite": invite,
                    "existing_user": False,
                    "email": invite.email,
                    "token": token,
                    "message": "Password must be 72 bytes or fewer.",
                },
            )
        user = User(
            email=invite.email,
            name=name.strip(),
            password_hash=hash_password(password),
            email_verified_at=now,
        )
        db.add(user)
        await db.flush()

    # Grant project share if invite has one (atomic with claim)
    if invite.project_id and invite.role:
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

    # Commit the database changes
    await db.commit()

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
