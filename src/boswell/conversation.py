"""Conversation engine for Boswell.

Handles dynamic interview conversation logic - letting Claude decide each turn.
No graph structures, no scoring algorithms.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ConversationState(BaseModel):
    """Current state of an interview conversation."""

    interview_id: str = Field(..., description="Interview ID")
    questions_asked: list[str] = Field(default_factory=list)
    questions_not_asked: list[str] = Field(default_factory=list)
    transcript: list[dict] = Field(default_factory=list)
    started_at: datetime | None = Field(default=None)
    target_time_minutes: int = Field(default=30)
    max_time_minutes: int = Field(default=45)
    questions_since_checkin: int = Field(default=0)


class ConversationEngine:
    """Manages the dynamic interview conversation."""

    def __init__(self, state: ConversationState):
        """Initialize the conversation engine.

        Args:
            state: Initial conversation state
        """
        self.state = state

    @property
    def time_remaining_minutes(self) -> float:
        """Calculate remaining interview time."""
        if not self.state.started_at:
            return float(self.state.target_time_minutes)
        elapsed = (datetime.now(timezone.utc) - self.state.started_at).total_seconds() / 60
        return max(0, self.state.target_time_minutes - elapsed)

    @property
    def should_check_in(self) -> bool:
        """Check if we should do a guest check-in (~every 5 questions)."""
        return self.state.questions_since_checkin >= 5

    @property
    def should_wrap_up(self) -> bool:
        """Check if we should begin wrapping up the interview."""
        # Wrap up if approaching max time or all questions covered
        if self.time_remaining_minutes <= 5:
            return True
        if not self.state.questions_not_asked:
            return True
        return False

    def get_opening(self) -> str:
        """Get the interview opening statement.

        Returns:
            Opening statement to begin the interview
        """
        # TODO: Implement opening generation
        raise NotImplementedError("Opening generation not yet implemented")

    def next_turn(self, guest_response: str) -> str:
        """Determine the next interviewer turn based on guest response.

        Uses Claude to decide the most natural next move:
        - Follow an interesting thread
        - Connect to unasked questions
        - Loop back to something skipped
        - Check in on guest
        - Begin wrapping up

        Args:
            guest_response: What the guest just said

        Returns:
            The interviewer's next question or comment
        """
        # TODO: Implement next turn logic via Claude
        raise NotImplementedError("Next turn logic not yet implemented")

    def get_closing(self) -> str:
        """Get the interview closing statement.

        Returns:
            Closing statement to end the interview
        """
        # TODO: Implement closing generation
        raise NotImplementedError("Closing generation not yet implemented")

    def add_to_transcript(self, speaker: str, text: str) -> None:
        """Add an utterance to the transcript.

        Args:
            speaker: "boswell" or "guest"
            text: What was said
        """
        self.state.transcript.append({
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
