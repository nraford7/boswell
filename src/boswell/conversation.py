"""Conversation engine for Boswell.

Handles dynamic interview conversation logic - letting Claude decide each turn.
No graph structures, no scoring algorithms.
"""

from datetime import UTC, datetime

import anthropic
from pydantic import BaseModel, Field

from boswell.interview import Interview


class ConversationState(BaseModel):
    """Current state of an interview conversation."""

    interview_id: str = Field(..., description="Interview ID")
    questions_asked: list[str] = Field(default_factory=list)
    questions_not_asked: list[str] = Field(default_factory=list)
    transcript: list[dict] = Field(default_factory=list)  # {speaker, text, timestamp}
    started_at: datetime | None = Field(default=None)
    target_time_minutes: int = Field(default=30)
    max_time_minutes: int = Field(default=45)
    questions_since_checkin: int = Field(default=0)


# Prompt template for Claude to decide next turn
NEXT_TURN_PROMPT = """\
You're a skilled interviewer conducting a research interview.

Interview topic: {topic}

Prepared questions not yet asked:
{questions_not_asked}

Recent conversation:
{recent_transcript}

The guest just said:
"{guest_response}"

Time remaining: {time_remaining} minutes

What's the most natural next move?
- Follow an interesting thread they opened?
- Connect to one of your unasked questions?
- Loop back to something you skipped earlier?
- Check in on the guest's time/energy?
- Begin wrapping up?

Respond with just your next question or comment. Be conversational and natural, \
like an NPR interviewer - intellectually curious but personable. \
Acknowledge what they said briefly before moving on."""

OPENING_PROMPT = """\
You're Boswell, a skilled AI interviewer about to begin a research interview.

Interview topic: {topic}

You have these prepared questions (but will follow the conversation naturally):
{questions}

Create a warm, professional opening that:
1. Greets the guest and thanks them for joining
2. Briefly explains the format (questions prepared, but want a natural conversation)
3. Asks if they're ready to begin

Keep it concise and natural - about 3-4 sentences. Don't be overly formal."""

CLOSING_PROMPT = """\
You're Boswell, a skilled AI interviewer wrapping up a research interview.

Interview topic: {topic}

Questions that were covered:
{questions_asked}

Questions not asked (that's okay):
{questions_not_asked}

Create a warm, professional closing that:
1. Thanks them genuinely for their time and insights
2. Asks if there's anything they'd like to add that wasn't covered
3. Lets them know what happens next (the transcript will be processed)

Keep it concise and natural - about 3-4 sentences."""

CHECK_IN_PROMPT = """\
You're a skilled interviewer who has asked several questions and should check in.

Interview topic: {topic}

Recent conversation:
{recent_transcript}

Time remaining: {time_remaining} minutes

Create a brief, natural check-in that:
- Shows respect for their time
- Asks if there's anything they'd like to make sure we cover

Keep it to 1-2 sentences, warm and conversational."""


class ConversationEngine:
    """Manages the dynamic interview conversation.

    This engine provides the "brain" for the Boswell interviewer, deciding
    what to say next based on the conversation so far, prepared questions,
    and time remaining.
    """

    def __init__(
        self,
        interview: Interview,
        questions: list[str],
        client: anthropic.Anthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        """Initialize the conversation engine.

        Args:
            interview: The Interview model with topic and configuration
            questions: List of prepared questions for the interview
            client: Optional Anthropic client (created if not provided)
            model: Claude model to use for generating responses
        """
        self.interview = interview
        self.model = model
        self._client = client

        # Initialize conversation state
        self.state = ConversationState(
            interview_id=interview.id,
            questions_not_asked=list(questions),  # Copy the list
            target_time_minutes=interview.target_time_minutes,
            max_time_minutes=interview.max_time_minutes,
        )

    @property
    def client(self) -> anthropic.Anthropic:
        """Get or create the Anthropic client."""
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    @property
    def time_remaining_minutes(self) -> float:
        """Calculate remaining interview time.

        Returns:
            Minutes remaining until target time, or target time if not started.
        """
        if not self.state.started_at:
            return float(self.state.target_time_minutes)
        elapsed = (datetime.now(UTC) - self.state.started_at).total_seconds() / 60
        return max(0, self.state.target_time_minutes - elapsed)

    @property
    def should_check_in(self) -> bool:
        """Check if we should do a guest check-in (~every 5 questions).

        Returns:
            True if it's time to check in with the guest.
        """
        return self.state.questions_since_checkin >= 5

    @property
    def should_wrap_up(self) -> bool:
        """Check if we should begin wrapping up the interview.

        Returns:
            True if approaching max time or all questions covered.
        """
        # Wrap up if approaching max time or all questions covered
        if self.time_remaining_minutes <= 5:
            return True
        if not self.state.questions_not_asked:
            return True
        return False

    def _format_recent_transcript(self, last_n: int = 6) -> str:
        """Format recent transcript entries for prompt context.

        Args:
            last_n: Number of recent entries to include.

        Returns:
            Formatted string of recent conversation.
        """
        recent = self.state.transcript[-last_n:] if self.state.transcript else []
        if not recent:
            return "(conversation just started)"

        lines = []
        for entry in recent:
            speaker = "Boswell" if entry["speaker"] == "boswell" else "Guest"
            lines.append(f"{speaker}: {entry['text']}")
        return "\n".join(lines)

    def _format_questions(self, questions: list[str]) -> str:
        """Format questions list for prompt context.

        Args:
            questions: List of questions.

        Returns:
            Formatted string with numbered questions.
        """
        if not questions:
            return "(none)"
        return "\n".join(f"- {q}" for q in questions)

    def _call_claude(self, prompt: str) -> str:
        """Call Claude API with the given prompt.

        Args:
            prompt: The prompt to send to Claude.

        Returns:
            Claude's response text.
        """
        message = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )
        # Extract text from response
        return message.content[0].text

    def get_opening(self) -> str:
        """Get the interview opening statement.

        This generates a warm, professional opening that:
        - Greets the guest
        - Explains the interview format
        - Asks if they're ready to begin

        Also marks the interview as started.

        Returns:
            Opening statement to begin the interview.
        """
        # Mark interview as started
        self.state.started_at = datetime.now(UTC)

        prompt = OPENING_PROMPT.format(
            topic=self.interview.topic,
            questions=self._format_questions(self.state.questions_not_asked),
        )

        opening = self._call_claude(prompt)

        # Add to transcript
        self.add_to_transcript("boswell", opening)

        return opening

    def next_turn(self, guest_response: str) -> str:
        """Determine the next interviewer turn based on guest response.

        Uses Claude to decide the most natural next move:
        - Follow an interesting thread
        - Connect to unasked questions
        - Loop back to something skipped
        - Check in on guest
        - Begin wrapping up

        Args:
            guest_response: What the guest just said.

        Returns:
            The interviewer's next question or comment.
        """
        # Add guest response to transcript
        self.add_to_transcript("guest", guest_response)

        # Increment questions since checkin (we count guest turns as progress)
        self.state.questions_since_checkin += 1

        # Check if we should wrap up
        if self.should_wrap_up:
            return self.get_closing()

        # Check if we should check in with the guest
        if self.should_check_in:
            # Reset counter
            self.state.questions_since_checkin = 0
            return self._get_check_in()

        # Normal turn - let Claude decide what to ask next
        prompt = NEXT_TURN_PROMPT.format(
            topic=self.interview.topic,
            questions_not_asked=self._format_questions(self.state.questions_not_asked),
            recent_transcript=self._format_recent_transcript(),
            guest_response=guest_response,
            time_remaining=f"{self.time_remaining_minutes:.0f}",
        )

        response = self._call_claude(prompt)

        # Add to transcript
        self.add_to_transcript("boswell", response)

        return response

    def _get_check_in(self) -> str:
        """Generate a check-in message for the guest.

        Returns:
            A brief check-in question about time/energy.
        """
        prompt = CHECK_IN_PROMPT.format(
            topic=self.interview.topic,
            recent_transcript=self._format_recent_transcript(),
            time_remaining=f"{self.time_remaining_minutes:.0f}",
        )

        check_in = self._call_claude(prompt)

        # Add to transcript
        self.add_to_transcript("boswell", check_in)

        return check_in

    def get_closing(self) -> str:
        """Get the interview closing statement.

        This generates a warm, professional closing that:
        - Thanks the guest
        - Asks if there's anything to add
        - Explains next steps

        Returns:
            Closing statement to end the interview.
        """
        prompt = CLOSING_PROMPT.format(
            topic=self.interview.topic,
            questions_asked=self._format_questions(self.state.questions_asked),
            questions_not_asked=self._format_questions(self.state.questions_not_asked),
        )

        closing = self._call_claude(prompt)

        # Add to transcript
        self.add_to_transcript("boswell", closing)

        return closing

    def add_to_transcript(self, speaker: str, text: str) -> None:
        """Add an utterance to the transcript.

        Args:
            speaker: "boswell" or "guest"
            text: What was said
        """
        self.state.transcript.append({
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def mark_question_asked(self, question: str) -> None:
        """Mark a question as asked, moving it from not_asked to asked.

        This should be called when the conversation naturally covers one
        of the prepared questions (either directly or through follow-up).

        Args:
            question: The question that was asked.
        """
        if question in self.state.questions_not_asked:
            self.state.questions_not_asked.remove(question)
            self.state.questions_asked.append(question)
