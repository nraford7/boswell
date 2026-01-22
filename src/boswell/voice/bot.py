"""Interview bot management for Boswell."""

import asyncio
import time
from dataclasses import dataclass

import httpx

from boswell.config import load_config
from boswell.interview import Interview, InterviewStatus, load_interview, save_interview
from boswell.voice.pipeline import run_interview
from boswell.voice.prompts import build_system_prompt


@dataclass
class DailyRoom:
    """Daily.co room information."""

    url: str
    name: str
    token: str


class InterviewBot:
    """Manages the voice interview bot lifecycle."""

    DAILY_API_URL = "https://api.daily.co/v1"

    def __init__(self, interview: Interview):
        """Initialize the interview bot.

        Args:
            interview: The Interview model with topic and questions.
        """
        self.interview = interview
        self.config = load_config()
        if self.config is None or not self.config.daily_api_key:
            raise RuntimeError(
                "Daily.co API key not configured. Run 'boswell init' to set up."
            )
        self._room: DailyRoom | None = None

    async def create_room(self) -> DailyRoom:
        """Create a Daily.co room for the interview.

        Returns:
            DailyRoom with url, name, and bot token.

        Raises:
            RuntimeError: If room creation fails.
        """
        room_name = f"boswell-{self.interview.id}"

        async with httpx.AsyncClient() as client:
            # Create the room
            response = await client.post(
                f"{self.DAILY_API_URL}/rooms",
                headers={
                    "Authorization": f"Bearer {self.config.daily_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": room_name,
                    "properties": {
                        "max_participants": 10,
                        "enable_chat": False,
                        "enable_knocking": False,
                        "start_video_off": True,
                        "start_audio_off": False,
                        "exp": int(time.time()) + 7200,  # 2 hours
                    },
                },
            )

            if response.status_code not in (200, 201):
                error_text = response.text
                raise RuntimeError(f"Failed to create Daily room: {error_text}")

            room_data = response.json()
            room_url = room_data["url"]

            # Create a meeting token for the bot
            token_response = await client.post(
                f"{self.DAILY_API_URL}/meeting-tokens",
                headers={
                    "Authorization": f"Bearer {self.config.daily_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "properties": {
                        "room_name": room_name,
                        "is_owner": True,
                        "user_name": "Boswell",
                        "enable_recording": "cloud",
                    },
                },
            )

            if token_response.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to create meeting token: {token_response.text}"
                )

            token_data = token_response.json()
            token = token_data["token"]

        self._room = DailyRoom(url=room_url, name=room_name, token=token)
        return self._room

    async def start(self) -> str:
        """Start the interview bot.

        Uses existing room if already created, otherwise creates a new one.
        Updates the interview status and runs the voice pipeline.

        Returns:
            The Daily.co room URL for guests to join.

        Raises:
            RuntimeError: If bot fails to start.
        """
        # Use existing room or create a new one
        if self._room is None:
            room = await self.create_room()
        else:
            room = self._room

        # Update interview status
        self.interview.meeting_link = room.url
        self.interview.status = InterviewStatus.WAITING
        save_interview(self.interview)

        # Build the system prompt
        system_prompt = build_system_prompt(
            topic=self.interview.topic,
            questions=self.interview.generated_questions,
            target_minutes=self.interview.target_time_minutes,
            max_minutes=self.interview.max_time_minutes,
        )

        # Run the voice pipeline (blocks until interview ends)
        try:
            self.interview.status = InterviewStatus.IN_PROGRESS
            save_interview(self.interview)

            transcript, conversation_history = await run_interview(
                room_url=room.url,
                room_token=room.token,
                system_prompt=system_prompt,
                bot_name="Boswell",
            )

            # Save transcript and conversation history
            self.interview.raw_transcript = transcript
            self.interview.conversation_history = conversation_history
            self.interview.status = InterviewStatus.COMPLETE
            save_interview(self.interview)

        except KeyboardInterrupt:
            # User paused the interview (Ctrl+C)
            self.interview.status = InterviewStatus.PAUSED
            save_interview(self.interview)
            raise

        except Exception as e:
            self.interview.status = InterviewStatus.ERROR
            save_interview(self.interview)
            raise RuntimeError(f"Interview failed: {e}") from e

        return room.url

    async def resume(self) -> str:
        """Resume a paused interview.

        Continues from where the interview left off using saved conversation history.

        Returns:
            The Daily.co room URL for guests to rejoin.

        Raises:
            RuntimeError: If bot fails to start or interview cannot be resumed.
        """
        if self.interview.status != InterviewStatus.PAUSED:
            raise RuntimeError(
                f"Cannot resume interview with status: {self.interview.status}. "
                "Only PAUSED interviews can be resumed."
            )

        if not self.interview.conversation_history:
            raise RuntimeError(
                "No conversation history found. Cannot resume interview."
            )

        # Create a new room for the resumed interview
        room = await self.create_room()

        # Update interview status
        self.interview.meeting_link = room.url
        self.interview.status = InterviewStatus.WAITING
        save_interview(self.interview)

        # Build the system prompt (same as original)
        system_prompt = build_system_prompt(
            topic=self.interview.topic,
            questions=self.interview.generated_questions,
            target_minutes=self.interview.target_time_minutes,
            max_minutes=self.interview.max_time_minutes,
        )

        # Run the voice pipeline with existing conversation history
        try:
            self.interview.status = InterviewStatus.IN_PROGRESS
            save_interview(self.interview)

            transcript, conversation_history = await run_interview(
                room_url=room.url,
                room_token=room.token,
                system_prompt=system_prompt,
                bot_name="Boswell",
                initial_messages=self.interview.conversation_history,
            )

            # Merge new transcript with existing
            self.interview.raw_transcript.extend(transcript)
            self.interview.conversation_history = conversation_history
            self.interview.status = InterviewStatus.COMPLETE
            save_interview(self.interview)

        except KeyboardInterrupt:
            # User paused again
            self.interview.status = InterviewStatus.PAUSED
            save_interview(self.interview)
            raise

        except Exception as e:
            self.interview.status = InterviewStatus.ERROR
            save_interview(self.interview)
            raise RuntimeError(f"Interview failed: {e}") from e

        return room.url

    async def cleanup(self) -> None:
        """Clean up the Daily room after interview."""
        if self._room is None:
            return

        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{self.DAILY_API_URL}/rooms/{self._room.name}",
                headers={
                    "Authorization": f"Bearer {self.config.daily_api_key}",
                },
            )


async def start_interview_bot(interview_id: str) -> str:
    """Start an interview bot for the given interview.

    Args:
        interview_id: The interview ID to start.

    Returns:
        The Daily.co room URL for guests to join.

    Raises:
        ValueError: If interview not found.
        RuntimeError: If bot fails to start.
    """
    interview = load_interview(interview_id)
    if interview is None:
        raise ValueError(f"Interview not found: {interview_id}")

    if not interview.generated_questions:
        raise ValueError(
            f"Interview {interview_id} has no questions. "
            "Run research ingestion first."
        )

    bot = InterviewBot(interview)
    return await bot.start()


async def resume_interview_bot(interview_id: str) -> str:
    """Resume a paused interview bot.

    Args:
        interview_id: The interview ID to resume.

    Returns:
        The Daily.co room URL for guests to rejoin.

    Raises:
        ValueError: If interview not found.
        RuntimeError: If interview cannot be resumed.
    """
    interview = load_interview(interview_id)
    if interview is None:
        raise ValueError(f"Interview not found: {interview_id}")

    if interview.status != InterviewStatus.PAUSED:
        raise ValueError(
            f"Interview {interview_id} is not paused (status: {interview.status}). "
            "Only paused interviews can be resumed."
        )

    bot = InterviewBot(interview)
    return await bot.resume()
