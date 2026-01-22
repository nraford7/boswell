"""MeetingBaaS integration for Boswell.

Handles creating speaking AI bots that join video calls to conduct interviews.
Uses the MeetingBaaS Speaking Bots API.
"""

import re
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from boswell.config import load_config
from boswell.interview import Interview


class MeetingBaaSError(Exception):
    """Exception raised for MeetingBaaS API errors."""

    pass


class BotResponse(BaseModel):
    """Response from MeetingBaaS bot creation."""

    bot_id: str = Field(..., description="Unique bot identifier")
    status: str = Field(default="created", description="Bot status")


class BotStatusResponse(BaseModel):
    """Response from MeetingBaaS bot status check."""

    bot_id: str = Field(..., description="Unique bot identifier")
    status: str = Field(..., description="Current bot status")
    meeting_url: str | None = Field(default=None, description="Meeting URL")


class MeetingBaaSClient:
    """Client for interacting with MeetingBaaS Speaking Bots API.

    The Speaking Bots API allows creating AI bots that can join video calls
    and conduct conversations using configured personas.
    """

    BASE_URL = "https://speaking.meetingbaas.com"

    def __init__(self, api_key: str) -> None:
        """Initialize the MeetingBaaS client.

        Args:
            api_key: MeetingBaaS API key for authentication.
        """
        self.api_key = api_key
        self._client = httpx.Client(timeout=60.0)

    def create_bot(
        self,
        meeting_url: str,
        persona: str = "boswell_interviewer",
        entry_message: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        """Create a speaking bot and dispatch it to a meeting.

        Args:
            meeting_url: The Zoom/Google Meet/Teams meeting URL.
            persona: Name of the persona to use (default: boswell_interviewer).
            entry_message: Optional message the bot says when joining.
            extra: Optional additional context for the bot.

        Returns:
            Dictionary with bot_id and status.

        Raises:
            MeetingBaaSError: If the API request fails.
            ValueError: If the meeting URL is invalid.
        """
        # Validate meeting URL format
        if not self._is_valid_meeting_url(meeting_url):
            raise ValueError(
                f"Invalid meeting URL: {meeting_url}. "
                "Must be a Zoom, Google Meet, or Teams URL."
            )

        payload = {
            "meeting_url": meeting_url,
            "meeting_baas_api_key": self.api_key,
            "personas": [persona],
        }

        # Add optional parameters
        if entry_message:
            payload["entry_message"] = entry_message

        if extra:
            payload["extra"] = extra

        try:
            response = self._client.post(
                f"{self.BASE_URL}/bots",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            data = response.json()
            return {
                "bot_id": data.get("bot_id", data.get("id", "")),
                "status": data.get("status", "created"),
            }

        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = str(e)
            raise MeetingBaaSError(f"Failed to create bot: {error_detail}") from e
        except httpx.RequestError as e:
            raise MeetingBaaSError(f"Request failed: {e}") from e

    def get_bot_status(self, bot_id: str) -> dict:
        """Get the current status of a bot.

        Args:
            bot_id: The bot ID to check.

        Returns:
            Dictionary with bot_id, status, and meeting_url.

        Raises:
            MeetingBaaSError: If the API request fails.
        """
        try:
            response = self._client.get(
                f"{self.BASE_URL}/bots/{bot_id}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()

            data = response.json()
            return {
                "bot_id": data.get("bot_id", data.get("id", bot_id)),
                "status": data.get("status", "unknown"),
                "meeting_url": data.get("meeting_url"),
            }

        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = str(e)
            raise MeetingBaaSError(f"Failed to get bot status: {error_detail}") from e
        except httpx.RequestError as e:
            raise MeetingBaaSError(f"Request failed: {e}") from e

    def _is_valid_meeting_url(self, url: str) -> bool:
        """Check if URL is a valid video meeting URL.

        Supports:
        - Google Meet: meet.google.com/xxx-xxxx-xxx
        - Zoom: zoom.us/j/... or *.zoom.us/j/...
        - Teams: teams.microsoft.com/...

        Args:
            url: URL to validate.

        Returns:
            True if URL appears to be a valid meeting URL.
        """
        patterns = [
            # Google Meet
            r"https?://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}",
            # Zoom (various formats)
            r"https?://[\w.-]*zoom\.us/j/\d+",
            r"https?://[\w.-]*zoom\.us/my/[\w.-]+",
            # Microsoft Teams
            r"https?://teams\.microsoft\.com/",
            r"https?://teams\.live\.com/",
        ]

        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True

        return False

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "MeetingBaaSClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


def get_persona_path(persona_name: str) -> Path:
    """Get the path to a persona file.

    Looks in the personas/ directory relative to the project root.

    Args:
        persona_name: Name of the persona (without .md extension).

    Returns:
        Path to the persona markdown file.
    """
    # Look for personas in multiple locations
    possible_paths = [
        Path(__file__).parent.parent.parent / "personas" / f"{persona_name}.md",
        Path.home() / ".boswell" / "personas" / f"{persona_name}.md",
    ]

    for path in possible_paths:
        if path.exists():
            return path

    # Return default path even if it doesn't exist
    return possible_paths[0]


def load_persona(persona_name: str) -> str | None:
    """Load a persona configuration from file.

    Args:
        persona_name: Name of the persona to load.

    Returns:
        Persona content as string, or None if not found.
    """
    path = get_persona_path(persona_name)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def create_interview_bot(interview: Interview) -> str:
    """Create a MeetingBaaS bot for an interview.

    Dispatches a speaking bot to the interview's meeting URL with the
    Boswell interviewer persona.

    Args:
        interview: The Interview object with meeting_link set.

    Returns:
        The bot_id for tracking.

    Raises:
        RuntimeError: If config is not set or API key is missing.
        MeetingBaaSError: If bot creation fails.
        ValueError: If interview has no meeting_link.
    """
    if not interview.meeting_link:
        raise ValueError("Interview has no meeting link set")

    config = load_config()
    if config is None or not config.meetingbaas_api_key:
        raise RuntimeError(
            "MeetingBaaS API key not configured. Run 'boswell init' to set up."
        )

    # Build the extra context for the bot
    extra_context = {
        "interview_id": interview.id,
        "topic": interview.topic,
        "questions": interview.generated_questions,
        "target_time_minutes": interview.target_time_minutes,
        "max_time_minutes": interview.max_time_minutes,
    }

    # Load persona content if available
    persona_content = load_persona("boswell_interviewer")
    if persona_content:
        extra_context["persona_instructions"] = persona_content

    # Create entry message
    entry_message = (
        "Hello! I'm Boswell, your AI interviewer. "
        "Thank you for joining. When you're ready, we can begin the interview."
    )

    with MeetingBaaSClient(config.meetingbaas_api_key) as client:
        result = client.create_bot(
            meeting_url=interview.meeting_link,
            persona="boswell_interviewer",
            entry_message=entry_message,
            extra=extra_context,
        )

    return result["bot_id"]


def generate_meeting_url() -> str:
    """Generate a placeholder meeting URL.

    Note: Actual meeting creation requires the user to create a Google Meet
    or Zoom meeting and provide the URL. This function returns a placeholder
    for development/testing purposes.

    Returns:
        A placeholder string indicating the user should provide a URL.
    """
    return "[User must provide Google Meet or Zoom URL]"


def validate_meeting_url(url: str) -> bool:
    """Validate that a URL is a supported meeting platform URL.

    Args:
        url: The URL to validate.

    Returns:
        True if the URL is a valid Google Meet, Zoom, or Teams URL.
    """
    client = MeetingBaaSClient("")  # Empty key just for validation
    return client._is_valid_meeting_url(url)
