"""Tests for MeetingBaaS integration module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from boswell.config import BoswellConfig
from boswell.interview import Interview
from boswell.meeting import (
    MeetingBaaSClient,
    MeetingBaaSError,
    create_interview_bot,
    generate_meeting_url,
    get_persona_path,
    load_persona,
    validate_meeting_url,
)


class TestMeetingBaaSClient:
    """Tests for the MeetingBaaSClient class."""

    def test_init(self):
        """Test client initialization."""
        client = MeetingBaaSClient("test-api-key")
        assert client.api_key == "test-api-key"
        assert client.BASE_URL == "https://speaking.meetingbaas.com"

    def test_context_manager(self):
        """Test client works as context manager."""
        with MeetingBaaSClient("test-api-key") as client:
            assert client.api_key == "test-api-key"

    def test_is_valid_meeting_url_google_meet(self):
        """Test validation of Google Meet URLs."""
        client = MeetingBaaSClient("")

        # Valid Google Meet URLs
        assert client._is_valid_meeting_url("https://meet.google.com/abc-defg-hij")
        assert client._is_valid_meeting_url("http://meet.google.com/abc-defg-hij")

        # Invalid Google Meet URLs
        assert not client._is_valid_meeting_url("https://meet.google.com/invalid")
        assert not client._is_valid_meeting_url("https://meet.google.com/ab-cdef-ghi")

    def test_is_valid_meeting_url_zoom(self):
        """Test validation of Zoom URLs."""
        client = MeetingBaaSClient("")

        # Valid Zoom URLs
        assert client._is_valid_meeting_url("https://zoom.us/j/1234567890")
        assert client._is_valid_meeting_url("https://us02web.zoom.us/j/1234567890")
        assert client._is_valid_meeting_url("https://zoom.us/my/myroom")

        # Invalid Zoom URLs
        assert not client._is_valid_meeting_url("https://zoom.us/invalid")

    def test_is_valid_meeting_url_teams(self):
        """Test validation of Microsoft Teams URLs."""
        client = MeetingBaaSClient("")

        # Valid Teams URLs
        assert client._is_valid_meeting_url(
            "https://teams.microsoft.com/l/meetup-join/test"
        )
        assert client._is_valid_meeting_url("https://teams.live.com/meet/test")

    def test_is_valid_meeting_url_invalid(self):
        """Test rejection of invalid URLs."""
        client = MeetingBaaSClient("")

        assert not client._is_valid_meeting_url("https://example.com/meeting")
        assert not client._is_valid_meeting_url("not-a-url")
        assert not client._is_valid_meeting_url("")
        assert not client._is_valid_meeting_url("https://youtube.com/watch?v=123")

    def test_create_bot_invalid_url(self):
        """Test create_bot raises ValueError for invalid meeting URL."""
        client = MeetingBaaSClient("test-api-key")

        with pytest.raises(ValueError, match="Invalid meeting URL"):
            client.create_bot("https://invalid-url.com/meeting")

    def test_create_bot_success(self):
        """Test successful bot creation."""
        # Mock the HTTP client response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "bot_id": "bot_123abc",
            "status": "created",
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.post.return_value = mock_response

        client = MeetingBaaSClient("test-api-key")
        client._client = mock_http_client

        result = client.create_bot(
            meeting_url="https://meet.google.com/abc-defg-hij",
            persona="boswell_interviewer",
            entry_message="Hello!",
            extra={"topic": "AI"},
        )

        assert result["bot_id"] == "bot_123abc"
        assert result["status"] == "created"

        # Verify the API was called correctly
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert call_args[0][0] == "https://speaking.meetingbaas.com/bots"

        payload = call_args[1]["json"]
        assert payload["meeting_url"] == "https://meet.google.com/abc-defg-hij"
        assert payload["meeting_baas_api_key"] == "test-api-key"
        assert payload["personas"] == ["boswell_interviewer"]
        assert payload["entry_message"] == "Hello!"
        assert payload["extra"] == {"topic": "AI"}

    def test_create_bot_http_error(self):
        """Test create_bot raises MeetingBaaSError on HTTP error."""
        with patch.object(
            MeetingBaaSClient, "_client", create=True
        ) as mock_http_client:
            error_response = MagicMock()
            error_response.json.return_value = {"detail": "Unauthorized"}
            error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=error_response
            )
            mock_http_client.post.return_value = error_response

            client = MeetingBaaSClient("bad-api-key")
            client._client = mock_http_client

            with pytest.raises(MeetingBaaSError, match="Failed to create bot"):
                client.create_bot("https://meet.google.com/abc-defg-hij")

    def test_get_bot_status_success(self):
        """Test successful bot status check."""
        with patch.object(
            MeetingBaaSClient, "_client", create=True
        ) as mock_http_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "bot_id": "bot_123abc",
                "status": "in_meeting",
                "meeting_url": "https://meet.google.com/abc-defg-hij",
            }
            mock_response.raise_for_status = MagicMock()
            mock_http_client.get.return_value = mock_response

            client = MeetingBaaSClient("test-api-key")
            client._client = mock_http_client

            result = client.get_bot_status("bot_123abc")

            assert result["bot_id"] == "bot_123abc"
            assert result["status"] == "in_meeting"
            assert result["meeting_url"] == "https://meet.google.com/abc-defg-hij"

    def test_get_bot_status_http_error(self):
        """Test get_bot_status raises MeetingBaaSError on HTTP error."""
        with patch.object(
            MeetingBaaSClient, "_client", create=True
        ) as mock_http_client:
            error_response = MagicMock()
            error_response.json.return_value = {"detail": "Bot not found"}
            error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=error_response
            )
            mock_http_client.get.return_value = error_response

            client = MeetingBaaSClient("test-api-key")
            client._client = mock_http_client

            with pytest.raises(MeetingBaaSError, match="Failed to get bot status"):
                client.get_bot_status("nonexistent_bot")


class TestPersonaFunctions:
    """Tests for persona loading functions."""

    def test_get_persona_path(self):
        """Test get_persona_path returns correct path."""
        path = get_persona_path("boswell_interviewer")

        # Should end with the expected filename
        assert path.name == "boswell_interviewer.md"
        assert "personas" in str(path)

    def test_load_persona_exists(self, tmp_path, monkeypatch):
        """Test loading a persona that exists."""
        # Create a test persona file
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        persona_file = personas_dir / "test_persona.md"
        persona_file.write_text("# Test Persona\n\nThis is a test.")

        # Mock the path resolution
        with patch("boswell.meeting.get_persona_path", return_value=persona_file):
            content = load_persona("test_persona")
            assert content == "# Test Persona\n\nThis is a test."

    def test_load_persona_not_found(self):
        """Test loading a persona that doesn't exist returns None."""
        with patch(
            "boswell.meeting.get_persona_path",
            return_value=Path("/nonexistent/persona.md"),
        ):
            content = load_persona("nonexistent")
            assert content is None


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_generate_meeting_url(self):
        """Test generate_meeting_url returns placeholder."""
        url = generate_meeting_url()
        assert "User must provide" in url
        assert "Google Meet" in url or "Zoom" in url

    def test_validate_meeting_url_valid(self):
        """Test validate_meeting_url with valid URLs."""
        assert validate_meeting_url("https://meet.google.com/abc-defg-hij")
        assert validate_meeting_url("https://zoom.us/j/1234567890")
        assert validate_meeting_url("https://teams.microsoft.com/l/meetup-join/test")

    def test_validate_meeting_url_invalid(self):
        """Test validate_meeting_url with invalid URLs."""
        assert not validate_meeting_url("https://example.com/meeting")
        assert not validate_meeting_url("not-a-url")
        assert not validate_meeting_url("")


class TestCreateInterviewBot:
    """Tests for create_interview_bot function."""

    def test_create_interview_bot_no_meeting_link(self):
        """Test create_interview_bot raises ValueError when no meeting link."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            meeting_link=None,
        )

        with pytest.raises(ValueError, match="no meeting link"):
            create_interview_bot(interview)

    def test_create_interview_bot_no_config(self, monkeypatch):
        """Test create_interview_bot raises RuntimeError when config missing."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            meeting_link="https://meet.google.com/abc-defg-hij",
        )

        # Mock load_config to return None
        monkeypatch.setattr("boswell.meeting.load_config", lambda: None)

        with pytest.raises(RuntimeError, match="API key not configured"):
            create_interview_bot(interview)

    def test_create_interview_bot_no_api_key(self, monkeypatch):
        """Test create_interview_bot raises RuntimeError when API key empty."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            meeting_link="https://meet.google.com/abc-defg-hij",
        )

        # Mock load_config to return config without API key
        config = BoswellConfig(meetingbaas_api_key="")
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)

        with pytest.raises(RuntimeError, match="API key not configured"):
            create_interview_bot(interview)

    def test_create_interview_bot_success(self, monkeypatch):
        """Test successful bot creation for interview."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            meeting_link="https://meet.google.com/abc-defg-hij",
            generated_questions=["Q1", "Q2"],
            target_time_minutes=30,
            max_time_minutes=45,
        )

        # Mock config
        config = BoswellConfig(meetingbaas_api_key="test-api-key")
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)

        # Mock persona loading
        monkeypatch.setattr("boswell.meeting.load_persona", lambda x: "Persona content")

        # Mock the MeetingBaaSClient
        mock_client = MagicMock()
        mock_client.create_bot.return_value = {
            "bot_id": "bot_123abc",
            "status": "created",
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("boswell.meeting.MeetingBaaSClient", return_value=mock_client):
            bot_id = create_interview_bot(interview)

        assert bot_id == "bot_123abc"

        # Verify the client was called with correct args
        mock_client.create_bot.assert_called_once()
        call_kwargs = mock_client.create_bot.call_args[1]
        assert call_kwargs["meeting_url"] == "https://meet.google.com/abc-defg-hij"
        assert call_kwargs["persona"] == "boswell_interviewer"
        assert "Hello" in call_kwargs["entry_message"]
        assert call_kwargs["extra"]["interview_id"] == "int_test123"
        assert call_kwargs["extra"]["topic"] == "Test Topic"
        assert call_kwargs["extra"]["questions"] == ["Q1", "Q2"]


class TestInterviewModelWithBotId:
    """Tests verifying Interview model has bot_id field."""

    def test_interview_has_bot_id_field(self):
        """Test that Interview model has bot_id field."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
        )

        # bot_id should default to None
        assert interview.bot_id is None

    def test_interview_bot_id_can_be_set(self):
        """Test that bot_id can be set on Interview."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc123",
        )

        assert interview.bot_id == "bot_abc123"

    def test_interview_bot_id_serialization(self):
        """Test that bot_id is properly serialized to JSON."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc123",
        )

        json_str = interview.model_dump_json()
        data = json.loads(json_str)

        assert data["bot_id"] == "bot_abc123"

    def test_interview_bot_id_deserialization(self):
        """Test that bot_id is properly deserialized from JSON."""
        json_str = json.dumps({
            "id": "int_test123",
            "topic": "Test Topic",
            "status": "pending",
            "created_at": "2024-01-22T12:00:00Z",
            "research_docs": [],
            "research_urls": [],
            "generated_questions": [],
            "target_time_minutes": 30,
            "max_time_minutes": 45,
            "bot_id": "bot_from_json",
        })

        interview = Interview.model_validate_json(json_str)

        assert interview.bot_id == "bot_from_json"
