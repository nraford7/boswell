"""Tests for MeetingBaaS integration module."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from boswell.config import BoswellConfig
from boswell.interview import Interview, InterviewStatus
from boswell.meeting import (
    NO_SHOW_TIMEOUT_MINUTES,
    POLL_INTERVAL_SECONDS,
    MeetingBaaSClient,
    MeetingBaaSError,
    check_guest_joined,
    create_interview_bot,
    generate_meeting_url,
    get_persona_path,
    handle_no_show,
    load_persona,
    validate_meeting_url,
    wait_for_guest,
    wait_for_guest_sync,
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
            entry_message="Hello!",
            extra={"topic": "AI", "persona_instructions": "You are a helpful assistant."},
        )

        assert result["bot_id"] == "bot_123abc"
        assert result["status"] == "created"

        # Verify the API was called correctly
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert call_args[0][0] == "https://speaking.meetingbaas.com/bots"

        # Check headers for API key authentication
        headers = call_args[1]["headers"]
        assert headers["x-meeting-baas-api-key"] == "test-api-key"

        payload = call_args[1]["json"]
        assert payload["meeting_url"] == "https://meet.google.com/abc-defg-hij"
        assert payload["entry_message"] == "Hello!"
        assert payload["prompt"] == "You are a helpful assistant."
        assert payload["bot_name"] == "Boswell"

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
        assert "Hello" in call_kwargs["entry_message"]
        assert call_kwargs["extra"]["interview_id"] == "int_test123"
        assert call_kwargs["extra"]["topic"] == "Test Topic"
        assert "persona_instructions" in call_kwargs["extra"]
        assert "Test Topic" in call_kwargs["extra"]["persona_instructions"]


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


# =============================================================================
# No-Show Handling Tests
# =============================================================================


class TestNoShowConstants:
    """Tests for no-show handling constants."""

    def test_default_timeout_value(self):
        """Test that default timeout is 10 minutes."""
        assert NO_SHOW_TIMEOUT_MINUTES == 10

    def test_poll_interval_value(self):
        """Test that poll interval is 30 seconds."""
        assert POLL_INTERVAL_SECONDS == 30


class TestCheckGuestJoined:
    """Tests for check_guest_joined function."""

    def test_guest_joined_with_multiple_participants(self):
        """Test guest detection when participant_count > 1."""
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "bot_id": "bot_123",
            "status": "in_meeting",
            "participant_count": 2,
            "participants": ["bot", "guest"],
        }

        result = check_guest_joined(mock_client, "bot_123")

        assert result is True
        mock_client.get_bot_status.assert_called_once_with("bot_123")

    def test_guest_not_joined_only_bot(self):
        """Test no guest when only bot is in meeting."""
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "bot_id": "bot_123",
            "status": "in_meeting",
            "participant_count": 1,
            "participants": ["bot"],
        }

        result = check_guest_joined(mock_client, "bot_123")

        assert result is False

    def test_guest_not_joined_bot_not_in_meeting(self):
        """Test no guest when bot not in meeting yet."""
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "bot_id": "bot_123",
            "status": "joining",
            "participant_count": 0,
        }

        result = check_guest_joined(mock_client, "bot_123")

        assert result is False

    def test_guest_joined_with_conversation_active(self):
        """Test guest detection via conversation_active flag."""
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "bot_id": "bot_123",
            "status": "in_meeting",
            "participant_count": 1,
            "conversation_active": True,
        }

        result = check_guest_joined(mock_client, "bot_123")

        assert result is True

    def test_guest_joined_inferred_from_participants_list(self):
        """Test guest detection from participants list length."""
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "bot_id": "bot_123",
            "status": "in_meeting",
            "participants": ["bot", "guest"],
        }

        # participant_count not provided, should use len(participants)
        result = check_guest_joined(mock_client, "bot_123")

        assert result is True

    def test_check_guest_raises_on_api_error(self):
        """Test that API errors are propagated."""
        mock_client = MagicMock()
        mock_client.get_bot_status.side_effect = MeetingBaaSError("API error")

        with pytest.raises(MeetingBaaSError, match="API error"):
            check_guest_joined(mock_client, "bot_123")


class TestHandleNoShow:
    """Tests for handle_no_show function."""

    def test_handle_no_show_updates_status(self, tmp_path, monkeypatch):
        """Test that handle_no_show updates interview status to NO_SHOW."""
        # Create a test interview file
        interviews_dir = tmp_path / ".boswell" / "interviews"
        interviews_dir.mkdir(parents=True)

        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            status=InterviewStatus.WAITING,
            bot_id="bot_abc",
        )
        interview_file = interviews_dir / "int_test123.json"
        interview_file.write_text(interview.model_dump_json())

        # Mock the interviews directory
        monkeypatch.setattr(
            "boswell.interview.get_interviews_dir",
            lambda: interviews_dir,
        )
        monkeypatch.setattr(
            "boswell.meeting.load_interview",
            lambda id: Interview.model_validate_json(
                (interviews_dir / f"{id}.json").read_text()
            )
            if (interviews_dir / f"{id}.json").exists()
            else None,
        )

        def mock_save(i):
            (interviews_dir / f"{i.id}.json").write_text(i.model_dump_json())

        monkeypatch.setattr("boswell.meeting.save_interview", mock_save)

        # Call handle_no_show
        result = handle_no_show("int_test123")

        assert result is not None
        assert result.status == InterviewStatus.NO_SHOW
        assert result.completed_at is not None

    def test_handle_no_show_not_found(self, monkeypatch):
        """Test handle_no_show returns None for non-existent interview."""
        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: None)

        result = handle_no_show("nonexistent")

        assert result is None


class TestWaitForGuest:
    """Tests for wait_for_guest async function."""

    def test_wait_for_guest_interview_not_found(self, monkeypatch):
        """Test wait_for_guest raises ValueError when interview not found."""
        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: None)

        with pytest.raises(ValueError, match="Interview not found"):
            asyncio.run(wait_for_guest("nonexistent"))

    def test_wait_for_guest_no_bot_id(self, monkeypatch):
        """Test wait_for_guest raises ValueError when no bot_id."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id=None,
        )
        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)

        with pytest.raises(ValueError, match="has no bot_id"):
            asyncio.run(wait_for_guest("int_test123"))

    def test_wait_for_guest_no_config(self, monkeypatch):
        """Test wait_for_guest raises RuntimeError when no config."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc",
        )
        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)
        monkeypatch.setattr("boswell.meeting.load_config", lambda: None)

        with pytest.raises(RuntimeError, match="API key not configured"):
            asyncio.run(wait_for_guest("int_test123"))

    def test_wait_for_guest_success(self, monkeypatch):
        """Test wait_for_guest returns True when guest joins."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc",
            status=InterviewStatus.WAITING,
        )
        config = BoswellConfig(meetingbaas_api_key="test-key")

        saved_interview = None

        def mock_save(i):
            nonlocal saved_interview
            saved_interview = i

        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)
        monkeypatch.setattr("boswell.meeting.save_interview", mock_save)

        # Mock MeetingBaaSClient
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "status": "in_meeting",
            "participant_count": 2,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("boswell.meeting.MeetingBaaSClient", return_value=mock_client):
            result = asyncio.run(
                wait_for_guest(
                    "int_test123",
                    timeout_minutes=1,
                    poll_interval_seconds=0.01,  # Very short for testing
                )
            )

        assert result is True
        assert saved_interview is not None
        assert saved_interview.status == InterviewStatus.IN_PROGRESS
        assert saved_interview.started_at is not None

    def test_wait_for_guest_timeout(self, monkeypatch):
        """Test wait_for_guest returns False on timeout."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc",
            status=InterviewStatus.WAITING,
        )
        config = BoswellConfig(meetingbaas_api_key="test-key")

        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)

        # Mock MeetingBaaSClient - never report guest joined
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "status": "in_meeting",
            "participant_count": 1,  # Only bot, no guest
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("boswell.meeting.MeetingBaaSClient", return_value=mock_client):
            # Use very short timeout for testing
            result = asyncio.run(
                wait_for_guest(
                    "int_test123",
                    timeout_minutes=0.001,  # ~60ms timeout
                    poll_interval_seconds=0.01,
                )
            )

        assert result is False

    def test_wait_for_guest_calls_progress_callback(self, monkeypatch):
        """Test that progress callback is called during wait."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc",
            status=InterviewStatus.WAITING,
        )
        config = BoswellConfig(meetingbaas_api_key="test-key")

        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)

        # Track callback calls
        callback_calls = []

        def progress_callback(elapsed, remaining):
            callback_calls.append((elapsed, remaining))

        # Mock MeetingBaaSClient - never report guest (will timeout)
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "status": "in_meeting",
            "participant_count": 1,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("boswell.meeting.MeetingBaaSClient", return_value=mock_client):
            asyncio.run(
                wait_for_guest(
                    "int_test123",
                    timeout_minutes=0.002,  # ~120ms
                    poll_interval_seconds=0.02,  # 20ms
                    progress_callback=progress_callback,
                )
            )

        # At least one callback should have been made
        assert len(callback_calls) >= 1


class TestWaitForGuestSync:
    """Tests for wait_for_guest_sync synchronous wrapper."""

    def test_wait_for_guest_sync_wraps_async(self, monkeypatch):
        """Test that sync wrapper properly wraps async function."""
        interview = Interview(
            id="int_test123",
            topic="Test Topic",
            bot_id="bot_abc",
            status=InterviewStatus.WAITING,
        )
        config = BoswellConfig(meetingbaas_api_key="test-key")

        monkeypatch.setattr("boswell.meeting.load_interview", lambda id: interview)
        monkeypatch.setattr("boswell.meeting.load_config", lambda: config)
        monkeypatch.setattr("boswell.meeting.save_interview", lambda i: None)

        # Mock MeetingBaaSClient - report guest joined immediately
        mock_client = MagicMock()
        mock_client.get_bot_status.return_value = {
            "status": "in_meeting",
            "participant_count": 2,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("boswell.meeting.MeetingBaaSClient", return_value=mock_client):
            result = wait_for_guest_sync(
                "int_test123",
                timeout_minutes=1,
                poll_interval_seconds=0.01,
            )

        assert result is True
