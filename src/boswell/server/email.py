"""Email sending module using Resend API.

This module provides a unified interface for sending emails. Currently
implements a stub that logs email attempts. Will be replaced with actual
Resend integration later.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    template: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Send an email via Resend (stub for now).

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text or HTML email body.
        template: Optional template name (for future use).
        context: Optional template context variables (for future use).

    Returns:
        True if email was sent successfully, False otherwise.

    Example:
        >>> await send_email(
        ...     to="guest@example.com",
        ...     subject="Your Interview Invitation",
        ...     body="Click here to join your interview...",
        ... )
        True
    """
    # TODO: Implement with Resend API
    # from boswell.server.config import get_settings
    # settings = get_settings()
    # resend.api_key = settings.resend_api_key
    # resend.Emails.send(...)

    logger.info(
        f"[EMAIL STUB] To: {to}, Subject: {subject}, "
        f"Template: {template}, Body length: {len(body)} chars"
    )

    if context:
        logger.debug(f"[EMAIL STUB] Context keys: {list(context.keys())}")

    return True


async def send_invitation_email(
    to: str,
    guest_name: str,
    interview_topic: str,
    magic_link: str,
) -> bool:
    """Send an interview invitation email to a guest.

    Args:
        to: Guest email address.
        guest_name: Name of the guest.
        interview_topic: Topic of the interview.
        magic_link: Magic link URL for the guest to join.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    subject = f"Interview Invitation: {interview_topic}"
    body = f"""Hello {guest_name},

You have been invited to participate in an interview about "{interview_topic}".

Click the link below to join your interview:
{magic_link}

This link is unique to you and should not be shared.

Best regards,
The Boswell Team
"""
    return await send_email(
        to=to,
        subject=subject,
        body=body,
        template="invitation",
        context={
            "guest_name": guest_name,
            "interview_topic": interview_topic,
            "magic_link": magic_link,
        },
    )


async def send_analysis_ready_email(
    to: str,
    guest_name: str,
    interview_topic: str,
    analysis_link: str,
) -> bool:
    """Send notification that interview analysis is ready.

    Args:
        to: Recipient email address.
        guest_name: Name of the guest who was interviewed.
        interview_topic: Topic of the interview.
        analysis_link: Link to view the analysis.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    subject = f"Interview Analysis Ready: {interview_topic}"
    body = f"""Hello,

The analysis for the interview with {guest_name} about "{interview_topic}" is now ready.

View the analysis here:
{analysis_link}

Best regards,
The Boswell Team
"""
    return await send_email(
        to=to,
        subject=subject,
        body=body,
        template="analysis_ready",
        context={
            "guest_name": guest_name,
            "interview_topic": interview_topic,
            "analysis_link": analysis_link,
        },
    )
