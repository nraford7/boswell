# src/boswell/server/routes/auth.py
"""Authentication routes with magic link login."""

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
from boswell.server.models import Team, User
from passlib.context import CryptContext

router = APIRouter()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return _pwd_context.verify(password, password_hash)


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
    return result.scalar_one_or_none()


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
