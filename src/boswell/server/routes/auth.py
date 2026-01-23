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
from boswell.server.main import templates
from boswell.server.models import Team, User

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
    db: AsyncSession = Depends(get_session),
):
    """Handle login form submission.

    Creates a magic link and displays it. In production, this would send an email.
    """
    settings = get_settings()
    normalized_email = email.lower()

    # Check if email is in admin_emails list (case-insensitive)
    admin_emails_lower = [e.lower() for e in settings.admin_emails] if settings.admin_emails else []
    if admin_emails_lower and normalized_email not in admin_emails_lower:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"message": "Email not authorized."},
        )

    # Check if user exists, create if not
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    if not user:
        # Create a new team for this user
        team = Team(name=f"{normalized_email}'s Team")
        db.add(team)
        await db.flush()  # Get the team ID

        # Create the user with name from email username
        name = normalized_email.split("@")[0]
        user = User(team_id=team.id, email=normalized_email, name=name)
        db.add(user)
        await db.flush()

    # Generate login token and link
    token = create_login_token(normalized_email)
    login_link = f"{settings.base_url}/admin/verify?token={token}"

    # For now, display the link (in production, send via email)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"message": f"Login link: {login_link}"},
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
