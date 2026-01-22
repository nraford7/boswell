"""Tests for Boswell conversation engine."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from boswell.conversation import (
    CHECK_IN_PROMPT,
    CLOSING_PROMPT,
    NEXT_TURN_PROMPT,
    OPENING_PROMPT,
    ConversationEngine,
    ConversationState,
)
from boswell.interview import Interview


class TestConversationState:
    """Tests for the ConversationState model."""

    def test_required_fields(self):
        """Test that ConversationState requires interview_id."""
        state = ConversationState(interview_id="int_test1")
        assert state.interview_id == "int_test1"

    def test_default_values(self):
        """Test ConversationState default values."""
        state = ConversationState(interview_id="int_test1")

        assert state.questions_asked == []
        assert state.questions_not_asked == []
        assert state.transcript == []
        assert state.started_at is None
        assert state.target_time_minutes == 30
        assert state.max_time_minutes == 45
        assert state.questions_since_checkin == 0

    def test_custom_values(self):
        """Test ConversationState with custom values."""
        started = datetime.now(UTC)
        state = ConversationState(
            interview_id="int_custom",
            questions_asked=["Q1?", "Q2?"],
            questions_not_asked=["Q3?", "Q4?"],
            transcript=[{
                "speaker": "boswell",
                "text": "Hello",
                "timestamp": "2025-01-22T10:00:00Z",
            }],
            started_at=started,
            target_time_minutes=20,
            max_time_minutes=30,
            questions_since_checkin=3,
        )

        assert state.interview_id == "int_custom"
        assert len(state.questions_asked) == 2
        assert len(state.questions_not_asked) == 2
        assert len(state.transcript) == 1
        assert state.started_at == started
        assert state.target_time_minutes == 20
        assert state.max_time_minutes == 30
        assert state.questions_since_checkin == 3


class TestConversationEngineInit:
    """Tests for ConversationEngine initialization."""

    def test_init_with_interview_and_questions(self):
        """Test engine initializes with Interview and questions."""
        interview = Interview(id="int_test1", topic="AI Ethics")
        questions = ["What is AI?", "What are the ethical concerns?"]

        engine = ConversationEngine(interview=interview, questions=questions)

        assert engine.interview == interview
        assert engine.state.interview_id == "int_test1"
        assert engine.state.questions_not_asked == questions
        assert engine.state.questions_asked == []

    def test_init_copies_questions_list(self):
        """Test that questions list is copied, not referenced."""
        interview = Interview(id="int_test1", topic="AI Ethics")
        original_questions = ["Q1?", "Q2?"]

        engine = ConversationEngine(interview=interview, questions=original_questions)

        # Modify original list
        original_questions.append("Q3?")

        # Engine's copy should be unchanged
        assert len(engine.state.questions_not_asked) == 2

    def test_init_with_custom_times(self):
        """Test engine respects interview time settings."""
        interview = Interview(
            id="int_test1",
            topic="Test",
            target_time_minutes=20,
            max_time_minutes=30,
        )

        engine = ConversationEngine(interview=interview, questions=[])

        assert engine.state.target_time_minutes == 20
        assert engine.state.max_time_minutes == 30

    def test_init_with_custom_client(self):
        """Test engine accepts custom Anthropic client."""
        interview = Interview(id="int_test1", topic="Test")
        mock_client = MagicMock()

        engine = ConversationEngine(
            interview=interview,
            questions=[],
            client=mock_client,
        )

        assert engine._client == mock_client

    def test_init_with_custom_model(self):
        """Test engine accepts custom model name."""
        interview = Interview(id="int_test1", topic="Test")

        engine = ConversationEngine(
            interview=interview,
            questions=[],
            model="claude-3-opus-20240229",
        )

        assert engine.model == "claude-3-opus-20240229"


class TestTimeRemaining:
    """Tests for time_remaining_minutes property."""

    def test_time_remaining_not_started(self):
        """Test time remaining equals target time when not started."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(interview=interview, questions=[])

        assert engine.time_remaining_minutes == 30.0

    def test_time_remaining_after_start(self):
        """Test time remaining decreases after start."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(interview=interview, questions=[])

        # Set started_at to 10 minutes ago
        engine.state.started_at = datetime.now(UTC) - timedelta(minutes=10)

        remaining = engine.time_remaining_minutes
        # Should be approximately 20 minutes (allowing for test execution time)
        assert 19.9 <= remaining <= 20.1

    def test_time_remaining_never_negative(self):
        """Test time remaining never goes below zero."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(interview=interview, questions=[])

        # Set started_at to way in the past
        engine.state.started_at = datetime.now(UTC) - timedelta(hours=2)

        assert engine.time_remaining_minutes == 0


class TestShouldCheckIn:
    """Tests for should_check_in property."""

    def test_should_not_check_in_initially(self):
        """Test no check-in needed at start."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        assert not engine.should_check_in

    def test_should_check_in_after_5_questions(self):
        """Test check-in triggered after 5 questions."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.state.questions_since_checkin = 5

        assert engine.should_check_in

    def test_should_check_in_after_more_than_5(self):
        """Test check-in still triggered after more than 5 questions."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.state.questions_since_checkin = 7

        assert engine.should_check_in


class TestShouldWrapUp:
    """Tests for should_wrap_up property."""

    def test_should_not_wrap_up_initially(self):
        """Test no wrap-up needed at start with questions remaining."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?", "Q2?"],
        )

        assert not engine.should_wrap_up

    def test_should_wrap_up_low_time(self):
        """Test wrap-up triggered when time is low."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?", "Q2?"],
        )

        # Set started_at to 26 minutes ago (4 minutes remaining)
        engine.state.started_at = datetime.now(UTC) - timedelta(minutes=26)

        assert engine.should_wrap_up

    def test_should_wrap_up_no_questions(self):
        """Test wrap-up triggered when all questions asked."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        assert engine.should_wrap_up

    def test_should_wrap_up_at_exactly_5_minutes(self):
        """Test wrap-up triggered at exactly 5 minutes remaining."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)
        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?"],
        )

        # Set started_at to 25 minutes ago (exactly 5 minutes remaining)
        engine.state.started_at = datetime.now(UTC) - timedelta(minutes=25)

        assert engine.should_wrap_up


class TestAddToTranscript:
    """Tests for add_to_transcript method."""

    def test_add_boswell_entry(self):
        """Test adding a Boswell entry to transcript."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.add_to_transcript("boswell", "Hello, welcome!")

        assert len(engine.state.transcript) == 1
        assert engine.state.transcript[0]["speaker"] == "boswell"
        assert engine.state.transcript[0]["text"] == "Hello, welcome!"
        assert "timestamp" in engine.state.transcript[0]

    def test_add_guest_entry(self):
        """Test adding a guest entry to transcript."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.add_to_transcript("guest", "Thanks for having me.")

        assert len(engine.state.transcript) == 1
        assert engine.state.transcript[0]["speaker"] == "guest"
        assert engine.state.transcript[0]["text"] == "Thanks for having me."

    def test_add_multiple_entries(self):
        """Test adding multiple entries preserves order."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.add_to_transcript("boswell", "First")
        engine.add_to_transcript("guest", "Second")
        engine.add_to_transcript("boswell", "Third")

        assert len(engine.state.transcript) == 3
        assert engine.state.transcript[0]["text"] == "First"
        assert engine.state.transcript[1]["text"] == "Second"
        assert engine.state.transcript[2]["text"] == "Third"


class TestMarkQuestionAsked:
    """Tests for mark_question_asked method."""

    def test_mark_existing_question(self):
        """Test marking an existing question as asked."""
        interview = Interview(id="int_test1", topic="Test")
        questions = ["Q1?", "Q2?", "Q3?"]
        engine = ConversationEngine(interview=interview, questions=questions)

        engine.mark_question_asked("Q2?")

        assert "Q2?" not in engine.state.questions_not_asked
        assert "Q2?" in engine.state.questions_asked
        assert len(engine.state.questions_not_asked) == 2
        assert len(engine.state.questions_asked) == 1

    def test_mark_nonexistent_question(self):
        """Test marking a question that doesn't exist (no error)."""
        interview = Interview(id="int_test1", topic="Test")
        questions = ["Q1?", "Q2?"]
        engine = ConversationEngine(interview=interview, questions=questions)

        # Should not raise an error
        engine.mark_question_asked("Q99?")

        assert len(engine.state.questions_not_asked) == 2
        assert len(engine.state.questions_asked) == 0

    def test_mark_multiple_questions(self):
        """Test marking multiple questions as asked."""
        interview = Interview(id="int_test1", topic="Test")
        questions = ["Q1?", "Q2?", "Q3?"]
        engine = ConversationEngine(interview=interview, questions=questions)

        engine.mark_question_asked("Q1?")
        engine.mark_question_asked("Q3?")

        assert engine.state.questions_not_asked == ["Q2?"]
        assert engine.state.questions_asked == ["Q1?", "Q3?"]


class TestFormatHelpers:
    """Tests for internal formatting helper methods."""

    def test_format_recent_transcript_empty(self):
        """Test formatting empty transcript."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        result = engine._format_recent_transcript()

        assert result == "(conversation just started)"

    def test_format_recent_transcript_with_entries(self):
        """Test formatting transcript with entries."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        engine.add_to_transcript("boswell", "Hello")
        engine.add_to_transcript("guest", "Hi there")

        result = engine._format_recent_transcript()

        assert "Boswell: Hello" in result
        assert "Guest: Hi there" in result

    def test_format_recent_transcript_limits_entries(self):
        """Test that transcript formatting limits to recent entries."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        # Add 10 entries
        for i in range(10):
            speaker = "boswell" if i % 2 == 0 else "guest"
            engine.add_to_transcript(speaker, f"Message {i}")

        result = engine._format_recent_transcript(last_n=3)

        # Should only contain last 3
        assert "Message 7" in result
        assert "Message 8" in result
        assert "Message 9" in result
        assert "Message 0" not in result

    def test_format_questions_empty(self):
        """Test formatting empty questions list."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        result = engine._format_questions([])

        assert result == "(none)"

    def test_format_questions_with_items(self):
        """Test formatting questions list with items."""
        interview = Interview(id="int_test1", topic="Test")
        engine = ConversationEngine(interview=interview, questions=[])

        result = engine._format_questions(["Q1?", "Q2?", "Q3?"])

        assert "- Q1?" in result
        assert "- Q2?" in result
        assert "- Q3?" in result


class TestGetOpening:
    """Tests for get_opening method (mocked Claude calls)."""

    def test_get_opening_calls_claude(self):
        """Test that get_opening calls Claude with correct prompt."""
        interview = Interview(id="int_test1", topic="AI Ethics")
        questions = ["What is AI?", "What are ethical concerns?"]

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello and welcome!")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=questions,
            client=mock_client,
        )

        result = engine.get_opening()

        # Verify Claude was called
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args

        # Check prompt contains topic and questions
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "AI Ethics" in prompt
        assert "What is AI?" in prompt

        # Verify result
        assert result == "Hello and welcome!"

    def test_get_opening_sets_started_at(self):
        """Test that get_opening sets the started_at timestamp."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Welcome!")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=[],
            client=mock_client,
        )

        assert engine.state.started_at is None

        before = datetime.now(UTC)
        engine.get_opening()
        after = datetime.now(UTC)

        assert engine.state.started_at is not None
        assert before <= engine.state.started_at <= after

    def test_get_opening_adds_to_transcript(self):
        """Test that get_opening adds response to transcript."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Welcome message!")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=[],
            client=mock_client,
        )

        engine.get_opening()

        assert len(engine.state.transcript) == 1
        assert engine.state.transcript[0]["speaker"] == "boswell"
        assert engine.state.transcript[0]["text"] == "Welcome message!"


class TestNextTurn:
    """Tests for next_turn method (mocked Claude calls)."""

    def test_next_turn_calls_claude(self):
        """Test that next_turn calls Claude with correct context."""
        interview = Interview(id="int_test1", topic="AI Ethics")
        questions = ["What is AI?"]

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="That's interesting. Tell me more.")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=questions,
            client=mock_client,
        )
        engine.state.started_at = datetime.now(UTC)

        result = engine.next_turn("I think AI is transformative.")

        # Verify Claude was called
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args

        # Check prompt contains relevant info
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "AI Ethics" in prompt
        assert "I think AI is transformative." in prompt
        assert "What is AI?" in prompt

        # Verify result
        assert result == "That's interesting. Tell me more."

    def test_next_turn_adds_guest_and_response_to_transcript(self):
        """Test that next_turn adds both guest response and Boswell's reply."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Follow up question?")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?"],
            client=mock_client,
        )
        engine.state.started_at = datetime.now(UTC)

        engine.next_turn("Guest says something.")

        assert len(engine.state.transcript) == 2
        assert engine.state.transcript[0]["speaker"] == "guest"
        assert engine.state.transcript[0]["text"] == "Guest says something."
        assert engine.state.transcript[1]["speaker"] == "boswell"
        assert engine.state.transcript[1]["text"] == "Follow up question?"

    def test_next_turn_increments_checkin_counter(self):
        """Test that next_turn increments questions_since_checkin."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Response")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?"],
            client=mock_client,
        )
        engine.state.started_at = datetime.now(UTC)

        assert engine.state.questions_since_checkin == 0

        engine.next_turn("Guest response 1")
        assert engine.state.questions_since_checkin == 1

        engine.next_turn("Guest response 2")
        assert engine.state.questions_since_checkin == 2

    def test_next_turn_triggers_check_in(self):
        """Test that next_turn triggers check-in after 5 questions."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Check in message")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?", "Q2?"],
            client=mock_client,
        )
        engine.state.started_at = datetime.now(UTC)
        engine.state.questions_since_checkin = 4  # Next turn will be 5th

        engine.next_turn("Fifth response")

        # Should have triggered check-in, which resets counter
        assert engine.state.questions_since_checkin == 0

        # Verify check-in prompt was used
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "check in" in prompt.lower() or "time" in prompt.lower()

    def test_next_turn_triggers_wrap_up_on_low_time(self):
        """Test that next_turn triggers closing when time is low."""
        interview = Interview(id="int_test1", topic="Test", target_time_minutes=30)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Closing statement")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?"],
            client=mock_client,
        )
        # Set time to be almost up
        engine.state.started_at = datetime.now(UTC) - timedelta(minutes=27)

        engine.next_turn("Guest response")

        # Verify closing prompt was used
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "closing" in prompt.lower() or "thank" in prompt.lower()

    def test_next_turn_triggers_wrap_up_when_no_questions(self):
        """Test that next_turn triggers closing when all questions asked."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Closing statement")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=[],  # No questions left
            client=mock_client,
        )
        engine.state.started_at = datetime.now(UTC)

        engine.next_turn("Guest response")

        # Verify closing prompt was used
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "closing" in prompt.lower() or "thank" in prompt.lower()


class TestGetClosing:
    """Tests for get_closing method (mocked Claude calls)."""

    def test_get_closing_calls_claude(self):
        """Test that get_closing calls Claude with correct context."""
        interview = Interview(id="int_test1", topic="AI Ethics")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Thank you for this conversation!")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=["Q1?", "Q2?"],
            client=mock_client,
        )
        engine.mark_question_asked("Q1?")

        result = engine.get_closing()

        # Verify Claude was called
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args

        # Check prompt contains topic and question status
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "AI Ethics" in prompt
        assert "Q1?" in prompt  # In asked
        assert "Q2?" in prompt  # In not asked

        # Verify result
        assert result == "Thank you for this conversation!"

    def test_get_closing_adds_to_transcript(self):
        """Test that get_closing adds response to transcript."""
        interview = Interview(id="int_test1", topic="Test")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Goodbye!")]
        mock_client.messages.create.return_value = mock_response

        engine = ConversationEngine(
            interview=interview,
            questions=[],
            client=mock_client,
        )

        engine.get_closing()

        assert len(engine.state.transcript) == 1
        assert engine.state.transcript[0]["speaker"] == "boswell"
        assert engine.state.transcript[0]["text"] == "Goodbye!"


class TestPromptTemplates:
    """Tests for prompt template content."""

    def test_next_turn_prompt_has_required_placeholders(self):
        """Test NEXT_TURN_PROMPT has all required placeholders."""
        assert "{topic}" in NEXT_TURN_PROMPT
        assert "{questions_not_asked}" in NEXT_TURN_PROMPT
        assert "{recent_transcript}" in NEXT_TURN_PROMPT
        assert "{guest_response}" in NEXT_TURN_PROMPT
        assert "{time_remaining}" in NEXT_TURN_PROMPT

    def test_opening_prompt_has_required_placeholders(self):
        """Test OPENING_PROMPT has all required placeholders."""
        assert "{topic}" in OPENING_PROMPT
        assert "{questions}" in OPENING_PROMPT

    def test_closing_prompt_has_required_placeholders(self):
        """Test CLOSING_PROMPT has all required placeholders."""
        assert "{topic}" in CLOSING_PROMPT
        assert "{questions_asked}" in CLOSING_PROMPT
        assert "{questions_not_asked}" in CLOSING_PROMPT

    def test_check_in_prompt_has_required_placeholders(self):
        """Test CHECK_IN_PROMPT has all required placeholders."""
        assert "{topic}" in CHECK_IN_PROMPT
        assert "{recent_transcript}" in CHECK_IN_PROMPT
        assert "{time_remaining}" in CHECK_IN_PROMPT


class TestIntegration:
    """Integration tests simulating a full conversation flow."""

    def test_full_conversation_flow(self):
        """Test a simulated full interview flow."""
        interview = Interview(
            id="int_flow",
            topic="Future of Work",
            target_time_minutes=30,
        )
        questions = [
            "How has remote work changed your organization?",
            "What skills will be most valuable in the future?",
            "How do you see AI impacting jobs?",
        ]

        mock_client = MagicMock()

        # Set up mock responses for the conversation
        responses = [
            "Hello! Thank you for joining. Ready to begin?",
            "That's a great point about flexibility. Tell me more?",
            "Interesting insight about communication tools. What skills matter?",
            "Thank you so much for sharing your thoughts today.",
        ]
        response_iter = iter(responses)

        def mock_create(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text=next(response_iter))]
            return mock_resp

        mock_client.messages.create.side_effect = mock_create

        engine = ConversationEngine(
            interview=interview,
            questions=questions,
            client=mock_client,
        )

        # Opening
        opening = engine.get_opening()
        assert "Hello" in opening
        assert engine.state.started_at is not None

        # First turn
        response1 = engine.next_turn("Remote work has given us much more flexibility.")
        assert "flexibility" in response1.lower() or "great" in response1.lower()

        # Mark a question as covered
        engine.mark_question_asked("How has remote work changed your organization?")

        # Second turn
        response2 = engine.next_turn("We use Slack and Zoom a lot more now.")
        assert "communication" in response2.lower() or "skills" in response2.lower()

        # Clear remaining questions to trigger wrap-up
        engine.state.questions_not_asked.clear()

        # Final turn should trigger closing
        closing = engine.next_turn("I think adaptability will be key.")
        assert "thank" in closing.lower()

        # Verify transcript captured everything
        assert len(engine.state.transcript) == 7  # opening + 3 guest + 3 boswell
