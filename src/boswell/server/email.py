"""Email sending module using Resend API.

This module provides a unified interface for sending emails using the
Resend API for transactional email delivery.
"""

import asyncio
import logging
from typing import Any

import resend

from boswell.server.config import get_settings

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    html: str | None = None,
    template: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Send an email via Resend.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
        html: Optional HTML email body.
        template: Optional template name (for logging/tracking).
        context: Optional template context variables (for logging/tracking).

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
    settings = get_settings()

    if not settings.resend_api_key:
        logger.error("RESEND_API_KEY not configured")
        return False

    resend.api_key = settings.resend_api_key

    try:
        params: resend.Emails.SendParams = {
            "from": settings.sender_email,
            "to": [to],
            "subject": subject,
            "text": body,
        }

        if html:
            params["html"] = html

        logger.info(f"Sending email to {to} from {settings.sender_email}")
        response = await asyncio.to_thread(resend.Emails.send, params)

        email_id = response.get('id') if isinstance(response, dict) else getattr(response, 'id', 'unknown')
        logger.info(
            f"Email sent successfully to {to}, subject: {subject}, "
            f"template: {template}, id: {email_id}"
        )
        return True

    except Exception as e:
        logger.error(
            f"Failed to send email to {to}, subject: {subject}, "
            f"template: {template}, error: {type(e).__name__}: {e}"
        )
        return False


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
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">You're Invited</h1>
    </div>
    <div style="background: #f9fafb; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
        <p style="margin-top: 0;">Hello {guest_name},</p>
        <p>You have been invited to participate in an interview about:</p>
        <p style="font-size: 18px; font-weight: 600; color: #4f46e5; margin: 20px 0;">{interview_topic}</p>
        <p style="margin-bottom: 25px;">Click the button below to start your interview when you're ready:</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{magic_link}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 30px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Start Interview</a>
        </div>
        <p style="font-size: 14px; color: #6b7280; margin-top: 25px;">This link is unique to you and should not be shared.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0;">
        <p style="font-size: 14px; color: #6b7280; margin-bottom: 0;">Best regards,<br>The Boswell Team</p>
    </div>
</body>
</html>"""
    return await send_email(
        to=to,
        subject=subject,
        body=body,
        html=html,
        template="invitation",
        context={
            "guest_name": guest_name,
            "interview_topic": interview_topic,
            "magic_link": magic_link,
        },
    )


async def send_admin_login_email(
    to: str,
    login_link: str,
) -> bool:
    """Send admin magic link login email.

    Args:
        to: Admin email address.
        login_link: Magic link URL for login.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    subject = "Your Boswell Login Link"
    body = f"""Hello,

Click the link below to log in to Boswell:
{login_link}

This link will expire in 1 hour.

Best regards,
The Boswell Team
"""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">Login to Boswell</h1>
    </div>
    <div style="background: #f9fafb; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
        <p style="margin-top: 0;">Hello,</p>
        <p>Click the button below to log in to your Boswell admin dashboard:</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{login_link}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 30px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Log In</a>
        </div>
        <p style="font-size: 14px; color: #6b7280; margin-top: 25px;">This link will expire in 1 hour.</p>
        <p style="font-size: 14px; color: #6b7280;">If you didn't request this login link, you can safely ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 25px 0;">
        <p style="font-size: 14px; color: #6b7280; margin-bottom: 0;">Best regards,<br>The Boswell Team</p>
    </div>
</body>
</html>"""
    return await send_email(
        to=to,
        subject=subject,
        body=body,
        html=html,
        template="admin_login",
        context={"login_link": login_link},
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
