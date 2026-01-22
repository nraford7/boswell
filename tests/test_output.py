"""Tests for Boswell output processing."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from boswell.interview import Interview
from boswell.output import (
    CLEAN_TRANSCRIPT_PROMPT,
    EXTRACT_INSIGHTS_PROMPT,
    InsightsOutput,
    TranscriptOutput,
    _calculate_duration,
    _format_raw_transcript,
    clean_transcript,
    export_interview,
    extract_insights,
    generate_output_path,
)


class TestTranscriptOutput:
    """Tests for the TranscriptOutput model."""

    def test_required_fields(self):
        """Test that TranscriptOutput has required fields."""
        output = TranscriptOutput(
            interview_id="int_test1",
            guest_name="Jane Smith",
            date="2024-01-22",
            duration_minutes=32,
            topic="AI safety",
            content="**Boswell:** Hello!",
        )

        assert output.interview_id == "int_test1"
        assert output.guest_name == "Jane Smith"
        assert output.date == "2024-01-22"
        assert output.duration_minutes == 32
        assert output.topic == "AI safety"
        assert output.content == "**Boswell:** Hello!"

    def test_nullable_guest_name(self):
        """Test that guest_name can be None."""
        output = TranscriptOutput(
            interview_id="int_test1",
            guest_name=None,
            date="2024-01-22",
            duration_minutes=30,
            topic="Test topic",
            content="Content",
        )

        assert output.guest_name is None


class TestInsightsOutput:
    """Tests for the InsightsOutput model."""

    def test_required_fields(self):
        """Test that InsightsOutput has required fields."""
        output = InsightsOutput(
            interview_id="int_test1",
            content="# Key Insights\n\n## Theme 1",
        )

        assert output.interview_id == "int_test1"
        assert output.content == "# Key Insights\n\n## Theme 1"

    def test_default_lists(self):
        """Test that themes and key_quotes default to empty lists."""
        output = InsightsOutput(
            interview_id="int_test1",
            content="Content",
        )

        assert output.themes == []
        assert output.key_quotes == []

    def test_with_themes_and_quotes(self):
        """Test InsightsOutput with themes and quotes."""
        output = InsightsOutput(
            interview_id="int_test1",
            themes=[
                {"name": "Theme 1", "description": "Description"},
            ],
            key_quotes=[
                {"text": "Quote 1", "timestamp": "4:32"},
            ],
            content="# Key Insights",
        )

        assert len(output.themes) == 1
        assert len(output.key_quotes) == 1


class TestCalculateDuration:
    """Tests for the _calculate_duration helper."""

    def test_empty_transcript(self):
        """Test duration calculation with empty transcript."""
        assert _calculate_duration([]) == 0

    def test_with_valid_timestamps(self):
        """Test duration calculation with valid ISO timestamps."""
        transcript = [
            {
                "speaker": "boswell",
                "text": "Hello",
                "timestamp": "2024-01-22T10:00:00Z",
            },
            {
                "speaker": "guest",
                "text": "Hi there",
                "timestamp": "2024-01-22T10:15:00Z",
            },
            {
                "speaker": "boswell",
                "text": "Goodbye",
                "timestamp": "2024-01-22T10:32:00Z",
            },
        ]

        duration = _calculate_duration(transcript)
        assert duration == 32

    def test_with_missing_timestamps(self):
        """Test duration calculation falls back to word count."""
        transcript = [
            {"speaker": "boswell", "text": "Hello there friend"},
            {"speaker": "guest", "text": " ".join(["word"] * 300)},  # 300 words
        ]

        duration = _calculate_duration(transcript)
        # 303 words / 150 wpm = 2 minutes
        assert duration == 2

    def test_with_invalid_timestamps(self):
        """Test duration calculation handles invalid timestamps."""
        transcript = [
            {"speaker": "boswell", "text": "Hello", "timestamp": "invalid"},
            {"speaker": "guest", "text": " ".join(["word"] * 150)},
        ]

        duration = _calculate_duration(transcript)
        # Falls back to word count
        assert duration >= 1

    def test_minimum_duration(self):
        """Test minimum duration is 1 minute."""
        transcript = [
            {"speaker": "boswell", "text": "Hi"},
        ]

        duration = _calculate_duration(transcript)
        assert duration >= 1


class TestFormatRawTranscript:
    """Tests for the _format_raw_transcript helper."""

    def test_empty_transcript(self):
        """Test formatting empty transcript."""
        assert _format_raw_transcript([]) == ""

    def test_basic_formatting(self):
        """Test basic transcript formatting."""
        transcript = [
            {"speaker": "boswell", "text": "Hello!"},
            {"speaker": "guest", "text": "Hi there."},
        ]

        formatted = _format_raw_transcript(transcript)
        assert "[boswell]: Hello!" in formatted
        assert "[guest]: Hi there." in formatted

    def test_with_timestamps(self):
        """Test formatting includes timestamps."""
        transcript = [
            {
                "speaker": "boswell",
                "text": "Hello!",
                "timestamp": "2024-01-22T10:00:00Z",
            },
        ]

        formatted = _format_raw_transcript(transcript)
        assert "[boswell]" in formatted
        assert "[10:00:00]" in formatted
        assert "Hello!" in formatted

    def test_handles_missing_fields(self):
        """Test formatting handles missing fields gracefully."""
        transcript = [
            {"speaker": "boswell"},  # No text
            {"text": "Hello"},  # No speaker
            {},  # Empty entry
        ]

        # Should not raise
        formatted = _format_raw_transcript(transcript)
        assert "[boswell]" in formatted
        assert "[unknown]" in formatted


class TestGenerateOutputPath:
    """Tests for the generate_output_path function."""

    def test_with_guest_name(self):
        """Test path generation with guest name."""
        path = generate_output_path(
            interview_id="int_test1",
            guest_name="Jane Smith",
            date="2024-01-22",
        )

        assert path == Path("outputs/2024-01-22-jane-smith")

    def test_without_guest_name(self):
        """Test path generation without guest name."""
        path = generate_output_path(
            interview_id="int_test1",
            guest_name=None,
            date="2024-01-22",
        )

        assert path == Path("outputs/2024-01-22-int_test1")

    def test_sanitizes_special_characters(self):
        """Test that special characters are sanitized."""
        path = generate_output_path(
            interview_id="int_test1",
            guest_name="Jane O'Brien-Smith!",
            date="2024-01-22",
        )

        # Special chars replaced with dashes
        assert "'" not in str(path)
        assert "!" not in str(path)
        assert "jane" in str(path).lower()

    def test_removes_consecutive_dashes(self):
        """Test that consecutive dashes are collapsed."""
        path = generate_output_path(
            interview_id="int_test1",
            guest_name="Jane   Smith",  # Multiple spaces
            date="2024-01-22",
        )

        assert "--" not in str(path)


class TestCleanTranscript:
    """Tests for the clean_transcript function."""

    def test_calls_claude_with_correct_prompt(self):
        """Test that clean_transcript calls Claude with proper prompt."""
        interview = Interview(
            id="int_test1",
            topic="AI Safety",
            guest_name="Jane Smith",
            created_at=datetime(2024, 1, 22, tzinfo=UTC),
        )

        raw_transcript = [
            {
                "speaker": "boswell",
                "text": "Hello Jane!",
                "timestamp": "2024-01-22T10:00:00Z",
            },
            {
                "speaker": "guest",
                "text": "Hi Boswell!",
                "timestamp": "2024-01-22T10:01:00Z",
            },
        ]

        mock_client = MagicMock()
        mock_message = MagicMock()
        cleaned_text = "**Boswell:** Hello Jane!\n\n**Jane Smith:** Hi Boswell!"
        mock_message.content = [MagicMock(text=cleaned_text)]
        mock_client.messages.create.return_value = mock_message

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                clean_transcript(raw_transcript, interview)

        # Verify Claude was called
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args

        # Check model and max_tokens
        assert call_args.kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_args.kwargs["max_tokens"] == 4096

        # Check prompt content
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "AI Safety" in prompt
        assert "Jane Smith" in prompt

    def test_returns_markdown_with_frontmatter(self):
        """Test that result includes YAML frontmatter."""
        interview = Interview(
            id="int_test1",
            topic="AI Safety",
            guest_name="Jane Smith",
            created_at=datetime(2024, 1, 22, tzinfo=UTC),
        )

        raw_transcript = [
            {
                "speaker": "boswell",
                "text": "Hello!",
                "timestamp": "2024-01-22T10:00:00Z",
            },
        ]

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="**Boswell:** Hello!")]
        mock_client.messages.create.return_value = mock_message

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                result = clean_transcript(raw_transcript, interview)

        # Check frontmatter
        assert result.startswith("---\n")
        assert "interview_id: int_test1" in result
        assert "guest: Jane Smith" in result
        assert "topic: AI Safety" in result
        assert "# Interview Transcript" in result
        assert "**Boswell:** Hello!" in result

    def test_uses_guest_fallback(self):
        """Test that 'Guest' is used when no guest name provided."""
        interview = Interview(
            id="int_test1",
            topic="AI Safety",
            guest_name=None,
            created_at=datetime(2024, 1, 22, tzinfo=UTC),
        )

        raw_transcript = [
            {
                "speaker": "boswell",
                "text": "Hello!",
                "timestamp": "2024-01-22T10:00:00Z",
            },
        ]

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="**Boswell:** Hello!")]
        mock_client.messages.create.return_value = mock_message

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                result = clean_transcript(raw_transcript, interview)

        assert "guest: Guest" in result

    def test_raises_without_api_key(self):
        """Test that RuntimeError is raised without API key."""
        interview = Interview(id="int_test1", topic="Test")
        raw_transcript = [{"speaker": "boswell", "text": "Hi"}]

        with patch("boswell.output.load_config", return_value=None):
            with pytest.raises(RuntimeError, match="Claude API key not configured"):
                clean_transcript(raw_transcript, interview)


class TestExtractInsights:
    """Tests for the extract_insights function."""

    def test_calls_claude_with_correct_prompt(self):
        """Test that extract_insights calls Claude with proper prompt."""
        transcript = "# Interview Transcript\n\n**Boswell:** Hello!\n\n**Jane:** Hi!"
        topic = "AI Safety"

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="# Key Insights\n\n## Theme 1")]
        mock_client.messages.create.return_value = mock_message

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                extract_insights(transcript, topic)

        # Verify Claude was called
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args

        # Check prompt content
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "AI Safety" in prompt
        assert "Interview Transcript" in prompt

    def test_returns_insights_content(self):
        """Test that extract_insights returns Claude's response."""
        transcript = "Transcript content"
        topic = "Test"

        expected_insights = (
            "# Key Insights\n\n## Theme 1: Important Topic\n\nDescription..."
        )

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=expected_insights)]
        mock_client.messages.create.return_value = mock_message

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                result = extract_insights(transcript, topic)

        assert result == expected_insights

    def test_raises_without_api_key(self):
        """Test that RuntimeError is raised without API key."""
        with patch("boswell.output.load_config", return_value=None):
            with pytest.raises(RuntimeError, match="Claude API key not configured"):
                extract_insights("transcript", "topic")


class TestExportInterview:
    """Tests for the export_interview function."""

    def test_exports_transcript_and_insights(self, tmp_path):
        """Test that export creates both files."""
        interview = Interview(
            id="int_test1",
            topic="AI Safety",
            guest_name="Jane Smith",
            created_at=datetime(2024, 1, 22, tzinfo=UTC),
        )

        raw_transcript = [
            {
                "speaker": "boswell",
                "text": "Hello Jane!",
                "timestamp": "2024-01-22T10:00:00Z",
            },
            {
                "speaker": "guest",
                "text": "Hi Boswell!",
                "timestamp": "2024-01-22T10:30:00Z",
            },
        ]

        mock_client = MagicMock()

        # First call: clean_transcript
        mock_clean_response = MagicMock()
        clean_text = "**Boswell:** Hello!\n\n**Jane:** Hi!"
        mock_clean_response.content = [MagicMock(text=clean_text)]

        # Second call: extract_insights
        mock_insights_response = MagicMock()
        insights_text = "# Key Insights\n\n## Theme 1"
        mock_insights_response.content = [MagicMock(text=insights_text)]

        mock_client.messages.create.side_effect = [
            mock_clean_response,
            mock_insights_response,
        ]

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                with patch("boswell.output.load_interview", return_value=interview):
                    with patch("boswell.output.save_interview") as mock_save:
                        transcript_path, insights_path = export_interview(
                            interview_id="int_test1",
                            output_dir=tmp_path,
                            raw_transcript=raw_transcript,
                        )

        # Verify files were created
        assert transcript_path.exists()
        assert insights_path.exists()
        assert transcript_path.name == "transcript.md"
        assert insights_path.name == "insights.md"

        # Verify transcript content
        transcript_content = transcript_path.read_text()
        assert "interview_id: int_test1" in transcript_content
        assert "# Interview Transcript" in transcript_content

        # Verify insights content
        insights_content = insights_path.read_text()
        assert "# Key Insights" in insights_content

        # Verify interview was updated
        mock_save.assert_called_once()
        saved_interview = mock_save.call_args[0][0]
        assert saved_interview.output_dir == str(tmp_path)

    def test_creates_output_directory(self, tmp_path):
        """Test that export creates output directory if needed."""
        output_dir = tmp_path / "nested" / "output"

        interview = Interview(
            id="int_test1",
            topic="Test",
            created_at=datetime(2024, 1, 22, tzinfo=UTC),
        )

        raw_transcript = [
            {"speaker": "boswell", "text": "Hi", "timestamp": "2024-01-22T10:00:00Z"},
        ]

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Content")]
        mock_client.messages.create.return_value = mock_response

        mock_config = MagicMock()
        mock_config.claude_api_key = "test-key"

        with patch("boswell.output.load_config", return_value=mock_config):
            with patch("boswell.output.anthropic.Anthropic", return_value=mock_client):
                with patch("boswell.output.load_interview", return_value=interview):
                    with patch("boswell.output.save_interview"):
                        export_interview(
                            interview_id="int_test1",
                            output_dir=output_dir,
                            raw_transcript=raw_transcript,
                        )

        assert output_dir.exists()

    def test_raises_for_missing_interview(self, tmp_path):
        """Test that ValueError is raised for missing interview."""
        with patch("boswell.output.load_interview", return_value=None):
            with pytest.raises(ValueError, match="Interview not found"):
                export_interview(
                    interview_id="int_nonexistent",
                    output_dir=tmp_path,
                    raw_transcript=[{"speaker": "test", "text": "hi"}],
                )

    def test_raises_without_transcript_data(self, tmp_path):
        """Test that RuntimeError is raised without transcript data."""
        interview = Interview(id="int_test1", topic="Test")

        with patch("boswell.output.load_interview", return_value=interview):
            with pytest.raises(RuntimeError, match="No transcript data provided"):
                export_interview(
                    interview_id="int_test1",
                    output_dir=tmp_path,
                    raw_transcript=None,
                )


class TestPromptTemplates:
    """Tests for prompt template content."""

    def test_clean_transcript_prompt_has_required_placeholders(self):
        """Test CLEAN_TRANSCRIPT_PROMPT has all required placeholders."""
        assert "{topic}" in CLEAN_TRANSCRIPT_PROMPT
        assert "{guest_name}" in CLEAN_TRANSCRIPT_PROMPT
        assert "{date}" in CLEAN_TRANSCRIPT_PROMPT
        assert "{raw_transcript}" in CLEAN_TRANSCRIPT_PROMPT
        assert "{guest_label}" in CLEAN_TRANSCRIPT_PROMPT

    def test_extract_insights_prompt_has_required_placeholders(self):
        """Test EXTRACT_INSIGHTS_PROMPT has all required placeholders."""
        assert "{topic}" in EXTRACT_INSIGHTS_PROMPT
        assert "{transcript}" in EXTRACT_INSIGHTS_PROMPT

    def test_clean_transcript_prompt_mentions_speaker_format(self):
        """Test prompt instructs on speaker label format."""
        assert "**Boswell:**" in CLEAN_TRANSCRIPT_PROMPT

    def test_extract_insights_prompt_requests_themes(self):
        """Test prompt requests theme extraction."""
        assert "Theme" in EXTRACT_INSIGHTS_PROMPT
        assert "Quote" in EXTRACT_INSIGHTS_PROMPT
