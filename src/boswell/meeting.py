"""MeetingBaaS integration for Boswell.

Handles creating speaking AI bots that join video calls to conduct interviews.
Uses the MeetingBaaS Speaking Bots API.
"""

import asyncio
import re
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from boswell.config import load_config
from boswell.interview import Interview, InterviewStatus, load_interview, save_interview

# No-show handling constants
NO_SHOW_TIMEOUT_MINUTES = 10
POLL_INTERVAL_SECONDS = 30


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
        entry_message: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        """Create a speaking bot and dispatch it to a meeting.

        Args:
            meeting_url: The Zoom/Google Meet/Teams meeting URL.
            entry_message: Optional message the bot says when joining.
            extra: Optional additional context for the bot. If it contains
                'persona_instructions', that becomes the bot's prompt.

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
        }

        # Add optional parameters
        if entry_message:
            payload["entry_message"] = entry_message

        if extra:
            payload["extra"] = extra

            # If extra contains prompt/persona instructions, add as top-level prompt
            if "persona_instructions" in extra:
                payload["prompt"] = extra["persona_instructions"]

            # Add bot name based on topic if available
            if "topic" in extra:
                payload["bot_name"] = "Boswell"

        try:
            response = self._client.post(
                f"{self.BASE_URL}/bots",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-meeting-baas-api-key": self.api_key,
                },
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

    # Build the interview prompt for the bot
    questions_text = "\n".join(
        f"{i+1}. {q}" for i, q in enumerate(interview.generated_questions)
    )

    persona_prompt = f"""You are Boswell, a skilled AI research interviewer conducting an interview about: {interview.topic}

Your interview style:
- Warm, curious, and intellectually engaged like an NPR interviewer
- Ask open-ended questions that invite detailed responses
- Listen actively and follow interesting threads
- Acknowledge what the guest says before moving to new topics
- Be conversational, not robotic

Prepared questions (use as a guide, but follow the conversation naturally):
{questions_text}

Guidelines:
- Start by greeting the guest and asking if they're ready to begin
- Target interview length: {interview.target_time_minutes} minutes
- Maximum time: {interview.max_time_minutes} minutes
- Check in with the guest every 5 questions or so
- When wrapping up, thank them and ask if there's anything they'd like to add

Remember: Follow interesting threads that emerge. The prepared questions are a guide, not a script."""

    # Build extra context
    extra_context = {
        "interview_id": interview.id,
        "topic": interview.topic,
        "persona_instructions": persona_prompt,
    }

    # Create entry message
    entry_message = (
        "Hello! I'm Boswell, your AI interviewer. "
        "Thank you for joining. When you're ready, we can begin the interview."
    )

    with MeetingBaaSClient(config.meetingbaas_api_key) as client:
        result = client.create_bot(
            meeting_url=interview.meeting_link,
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


# =============================================================================
# No-Show Handling
# =============================================================================


def check_guest_joined(client: MeetingBaaSClient, bot_id: str) -> bool:
    """Check if a guest has joined the meeting via bot status.

    Interprets the bot status to determine if a guest (non-bot participant)
    has joined the meeting. MeetingBaaS returns status with participant info.

    Args:
        client: The MeetingBaaS client instance.
        bot_id: The bot ID to check status for.

    Returns:
        True if a guest has joined (participants > 1 and status is "in_meeting"),
        False otherwise.

    Raises:
        MeetingBaaSError: If the status check fails.
    """
    status_data = client.get_bot_status(bot_id)
    status = status_data.get("status", "")

    # Check if bot is in meeting
    if status != "in_meeting":
        return False

    # Check participant count - if more than just the bot, guest has joined
    # MeetingBaaS may report participants in different ways depending on version
    participants = status_data.get("participants", [])
    participant_count = status_data.get("participant_count", len(participants))

    # If we have participants > 1, or status indicates active conversation,
    # consider guest joined
    if participant_count > 1:
        return True

    # Also check for other indicators that guest joined
    if status_data.get("conversation_active", False):
        return True

    return False


async def wait_for_guest(
    interview_id: str,
    timeout_minutes: int = NO_SHOW_TIMEOUT_MINUTES,
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
    progress_callback: callable = None,
) -> bool:
    """Wait for guest to join the meeting, polling bot status.

    Polls the MeetingBaaS bot status at regular intervals to detect when
    a guest joins. Updates interview status accordingly.

    Args:
        interview_id: The interview ID to monitor.
        timeout_minutes: Maximum time to wait in minutes (default: 10).
        poll_interval_seconds: Interval between status checks (default: 30).
        progress_callback: Optional callback(elapsed_seconds, remaining_seconds)
            called after each poll to report progress.

    Returns:
        True if guest joined within timeout, False if timeout expired.

    Raises:
        ValueError: If interview not found or has no bot_id.
        RuntimeError: If config not available.
        MeetingBaaSError: If status checks fail repeatedly.
    """
    interview = load_interview(interview_id)
    if interview is None:
        raise ValueError(f"Interview not found: {interview_id}")

    if not interview.bot_id:
        raise ValueError(f"Interview {interview_id} has no bot_id set")

    config = load_config()
    if config is None or not config.meetingbaas_api_key:
        raise RuntimeError(
            "MeetingBaaS API key not configured. Run 'boswell init' to set up."
        )

    timeout_seconds = timeout_minutes * 60
    start_time = time.time()

    with MeetingBaaSClient(config.meetingbaas_api_key) as client:
        while True:
            elapsed = time.time() - start_time
            remaining = timeout_seconds - elapsed

            if remaining <= 0:
                # Timeout - guest didn't join
                return False

            try:
                if check_guest_joined(client, interview.bot_id):
                    # Guest joined - update status to IN_PROGRESS
                    interview.status = InterviewStatus.IN_PROGRESS
                    from datetime import UTC, datetime
                    interview.started_at = datetime.now(UTC)
                    save_interview(interview)
                    return True
            except MeetingBaaSError:
                # Log error but continue polling - may be transient
                pass

            # Report progress if callback provided
            if progress_callback:
                progress_callback(int(elapsed), int(remaining))

            # Wait before next poll
            await asyncio.sleep(poll_interval_seconds)


def wait_for_guest_sync(
    interview_id: str,
    timeout_minutes: int = NO_SHOW_TIMEOUT_MINUTES,
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
    progress_callback: callable = None,
) -> bool:
    """Synchronous version of wait_for_guest for CLI use.

    Wraps the async wait_for_guest function for use in synchronous contexts.

    Args:
        interview_id: The interview ID to monitor.
        timeout_minutes: Maximum time to wait in minutes (default: 10).
        poll_interval_seconds: Interval between status checks (default: 30).
        progress_callback: Optional callback(elapsed_seconds, remaining_seconds).

    Returns:
        True if guest joined within timeout, False if timeout expired.
    """
    return asyncio.run(
        wait_for_guest(
            interview_id,
            timeout_minutes,
            poll_interval_seconds,
            progress_callback,
        )
    )


def handle_no_show(interview_id: str) -> Interview | None:
    """Update interview status to NO_SHOW and clean up.

    Called when a guest doesn't join within the timeout period.
    Updates the interview status and sets completion timestamp.

    Args:
        interview_id: The interview ID to mark as no-show.

    Returns:
        The updated Interview object, or None if not found.
    """
    interview = load_interview(interview_id)
    if interview is None:
        return None

    interview.status = InterviewStatus.NO_SHOW
    from datetime import UTC, datetime
    interview.completed_at = datetime.now(UTC)
    save_interview(interview)

    return interview
