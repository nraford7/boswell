"""Tests for Boswell interview model and persistence."""

import json
from datetime import UTC, datetime
from pathlib import Path

from boswell.interview import (
    Interview,
    InterviewStatus,
    create_interview,
    generate_interview_id,
    get_interview_path,
    get_interviews_dir,
    list_interviews,
    load_interview,
    save_interview,
    update_interview_status,
)


class TestInterviewStatus:
    """Tests for the InterviewStatus enum."""

    def test_all_statuses_exist(self):
        """Test that all required statuses are defined."""
        assert InterviewStatus.PENDING == "pending"
        assert InterviewStatus.WAITING == "waiting"
        assert InterviewStatus.IN_PROGRESS == "in_progress"
        assert InterviewStatus.PROCESSING == "processing"
        assert InterviewStatus.COMPLETE == "complete"
        assert InterviewStatus.NO_SHOW == "no_show"
        assert InterviewStatus.ERROR == "error"

    def test_status_count(self):
        """Test that we have exactly 7 statuses."""
        assert len(InterviewStatus) == 7


class TestInterview:
    """Tests for the Interview Pydantic model."""

    def test_required_fields(self):
        """Test that Interview requires id and topic."""
        interview = Interview(id="int_test1", topic="Test topic")
        assert interview.id == "int_test1"
        assert interview.topic == "Test topic"

    def test_default_values(self):
        """Test Interview default values."""
        interview = Interview(id="int_test1", topic="Test")

        assert interview.status == InterviewStatus.PENDING
        assert interview.started_at is None
        assert interview.completed_at is None
        assert interview.guest_name is None
        assert interview.meeting_link is None
        assert interview.research_docs == []
        assert interview.research_urls == []
        assert interview.generated_questions == []
        assert interview.target_time_minutes == 30
        assert interview.max_time_minutes == 45
        assert interview.output_dir is None

    def test_created_at_is_set(self):
        """Test that created_at is automatically set to now."""
        before = datetime.now(UTC)
        interview = Interview(id="int_test1", topic="Test")
        after = datetime.now(UTC)

        assert before <= interview.created_at <= after

    def test_custom_values(self):
        """Test Interview with custom values."""
        interview = Interview(
            id="int_custom",
            topic="Custom topic",
            status=InterviewStatus.IN_PROGRESS,
            guest_name="Jane Doe",
            meeting_link="https://meet.google.com/abc-defg-hij",
            research_docs=["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
            research_urls=["https://example.com"],
            generated_questions=["Question 1?", "Question 2?"],
            target_time_minutes=20,
            max_time_minutes=30,
            output_dir="/path/to/output",
        )

        assert interview.guest_name == "Jane Doe"
        assert interview.meeting_link == "https://meet.google.com/abc-defg-hij"
        assert len(interview.research_docs) == 2
        assert len(interview.research_urls) == 1
        assert len(interview.generated_questions) == 2
        assert interview.target_time_minutes == 20
        assert interview.max_time_minutes == 30

    def test_json_serialization(self):
        """Test Interview serializes to JSON correctly."""
        interview = Interview(
            id="int_json",
            topic="JSON test",
            status=InterviewStatus.COMPLETE,
        )

        json_str = interview.model_dump_json()
        data = json.loads(json_str)

        assert data["id"] == "int_json"
        assert data["topic"] == "JSON test"
        assert data["status"] == "complete"

    def test_json_deserialization(self):
        """Test Interview deserializes from JSON correctly."""
        json_str = json.dumps({
            "id": "int_load",
            "topic": "Load test",
            "status": "processing",
            "created_at": "2025-01-22T10:00:00Z",
            "started_at": None,
            "completed_at": None,
            "guest_name": None,
            "meeting_link": None,
            "research_docs": [],
            "research_urls": [],
            "generated_questions": [],
            "target_time_minutes": 30,
            "max_time_minutes": 45,
            "output_dir": None,
        })

        interview = Interview.model_validate_json(json_str)

        assert interview.id == "int_load"
        assert interview.status == InterviewStatus.PROCESSING


class TestGenerateInterviewId:
    """Tests for generate_interview_id function."""

    def test_format(self):
        """Test that IDs have correct format."""
        interview_id = generate_interview_id()
        assert interview_id.startswith("int_")
        assert len(interview_id) == 10  # "int_" + 6 chars

    def test_uniqueness(self):
        """Test that generated IDs are unique."""
        ids = {generate_interview_id() for _ in range(100)}
        assert len(ids) == 100  # All unique

    def test_valid_characters(self):
        """Test that IDs contain only valid characters."""
        for _ in range(50):
            interview_id = generate_interview_id()
            suffix = interview_id[4:]  # Remove "int_"
            assert all(c.isalnum() and (c.isdigit() or c.islower()) for c in suffix)


class TestGetInterviewsDir:
    """Tests for get_interviews_dir function."""

    def test_returns_correct_path(self, monkeypatch, tmp_path):
        """Test get_interviews_dir returns ~/.boswell/interviews/."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interviews_dir = get_interviews_dir()

        assert interviews_dir == tmp_path / ".boswell" / "interviews"

    def test_creates_directory(self, monkeypatch, tmp_path):
        """Test get_interviews_dir creates directory if needed."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interviews_dir = get_interviews_dir()

        assert interviews_dir.exists()
        assert interviews_dir.is_dir()


class TestGetInterviewPath:
    """Tests for get_interview_path function."""

    def test_returns_correct_path(self, monkeypatch, tmp_path):
        """Test get_interview_path returns correct path."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Ensure directory exists
        (tmp_path / ".boswell" / "interviews").mkdir(parents=True)

        path = get_interview_path("int_abc123")

        assert path == tmp_path / ".boswell" / "interviews" / "int_abc123.json"


class TestPersistence:
    """Tests for save_interview, load_interview, and list_interviews."""

    def test_save_interview(self, monkeypatch, tmp_path):
        """Test save_interview creates a file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = Interview(id="int_save1", topic="Save test")
        save_interview(interview)

        interview_path = tmp_path / ".boswell" / "interviews" / "int_save1.json"
        assert interview_path.exists()

    def test_save_interview_content(self, monkeypatch, tmp_path):
        """Test save_interview writes correct content."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = Interview(
            id="int_save2",
            topic="Content test",
            status=InterviewStatus.WAITING,
        )
        save_interview(interview)

        interview_path = tmp_path / ".boswell" / "interviews" / "int_save2.json"
        data = json.loads(interview_path.read_text())

        assert data["id"] == "int_save2"
        assert data["topic"] == "Content test"
        assert data["status"] == "waiting"

    def test_load_interview_nonexistent(self, monkeypatch, tmp_path):
        """Test load_interview returns None for nonexistent interview."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = load_interview("int_nonexistent")

        assert interview is None

    def test_load_interview_existing(self, monkeypatch, tmp_path):
        """Test load_interview loads existing interview."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create interview file
        interviews_dir = tmp_path / ".boswell" / "interviews"
        interviews_dir.mkdir(parents=True)
        interview_data = {
            "id": "int_load1",
            "topic": "Load test",
            "status": "pending",
            "created_at": "2025-01-22T10:00:00Z",
            "started_at": None,
            "completed_at": None,
            "guest_name": "Test Guest",
            "meeting_link": None,
            "research_docs": [],
            "research_urls": [],
            "generated_questions": [],
            "target_time_minutes": 30,
            "max_time_minutes": 45,
            "output_dir": None,
        }
        (interviews_dir / "int_load1.json").write_text(json.dumps(interview_data))

        interview = load_interview("int_load1")

        assert interview is not None
        assert interview.id == "int_load1"
        assert interview.topic == "Load test"
        assert interview.guest_name == "Test Guest"

    def test_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        """Test save and load work together."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        original = Interview(
            id="int_round",
            topic="Roundtrip test",
            status=InterviewStatus.IN_PROGRESS,
            guest_name="Jane Smith",
            research_docs=["/doc1.pdf", "/doc2.pdf"],
            research_urls=["https://example.com"],
            generated_questions=["Q1?", "Q2?"],
            target_time_minutes=25,
            max_time_minutes=40,
        )

        save_interview(original)
        loaded = load_interview("int_round")

        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.topic == original.topic
        assert loaded.status == original.status
        assert loaded.guest_name == original.guest_name
        assert loaded.research_docs == original.research_docs
        assert loaded.research_urls == original.research_urls
        assert loaded.generated_questions == original.generated_questions
        assert loaded.target_time_minutes == original.target_time_minutes
        assert loaded.max_time_minutes == original.max_time_minutes


class TestListInterviews:
    """Tests for list_interviews function."""

    def test_empty_list(self, monkeypatch, tmp_path):
        """Test list_interviews returns empty list when no interviews."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interviews = list_interviews()

        assert interviews == []

    def test_lists_all_interviews(self, monkeypatch, tmp_path):
        """Test list_interviews returns all saved interviews."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create multiple interviews
        int1 = Interview(id="int_list1", topic="Topic 1")
        int2 = Interview(id="int_list2", topic="Topic 2")
        int3 = Interview(id="int_list3", topic="Topic 3")

        save_interview(int1)
        save_interview(int2)
        save_interview(int3)

        interviews = list_interviews()

        assert len(interviews) == 3
        ids = {i.id for i in interviews}
        assert ids == {"int_list1", "int_list2", "int_list3"}

    def test_sorted_by_created_at(self, monkeypatch, tmp_path):
        """Test list_interviews returns interviews sorted by creation date."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create interviews with different dates
        int1 = Interview(
            id="int_old",
            topic="Old",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        int2 = Interview(
            id="int_new",
            topic="New",
            created_at=datetime(2025, 1, 22, tzinfo=UTC),
        )
        int3 = Interview(
            id="int_mid",
            topic="Mid",
            created_at=datetime(2025, 1, 10, tzinfo=UTC),
        )

        save_interview(int1)
        save_interview(int2)
        save_interview(int3)

        interviews = list_interviews()

        # Newest first
        assert interviews[0].id == "int_new"
        assert interviews[1].id == "int_mid"
        assert interviews[2].id == "int_old"

    def test_skips_invalid_files(self, monkeypatch, tmp_path):
        """Test list_interviews skips invalid JSON files."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interviews_dir = tmp_path / ".boswell" / "interviews"
        interviews_dir.mkdir(parents=True)

        # Create valid interview
        int1 = Interview(id="int_valid", topic="Valid")
        save_interview(int1)

        # Create invalid file
        (interviews_dir / "int_invalid.json").write_text("not valid json")

        interviews = list_interviews()

        assert len(interviews) == 1
        assert interviews[0].id == "int_valid"


class TestCreateInterview:
    """Tests for create_interview function."""

    def test_creates_with_unique_id(self, monkeypatch, tmp_path):
        """Test create_interview generates unique ID."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Test topic")

        assert interview.id.startswith("int_")
        assert len(interview.id) == 10

    def test_creates_with_topic(self, monkeypatch, tmp_path):
        """Test create_interview sets topic."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="My test topic")

        assert interview.topic == "My test topic"

    def test_creates_with_docs_and_urls(self, monkeypatch, tmp_path):
        """Test create_interview sets docs and URLs."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(
            topic="Research topic",
            docs=["/doc1.pdf", "/doc2.pdf"],
            urls=["https://example.com", "https://test.com"],
        )

        assert interview.research_docs == ["/doc1.pdf", "/doc2.pdf"]
        assert interview.research_urls == ["https://example.com", "https://test.com"]

    def test_creates_with_pending_status(self, monkeypatch, tmp_path):
        """Test create_interview sets PENDING status."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Test")

        assert interview.status == InterviewStatus.PENDING

    def test_persists_to_disk(self, monkeypatch, tmp_path):
        """Test create_interview saves to disk."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Persist test")

        # Should be loadable
        loaded = load_interview(interview.id)
        assert loaded is not None
        assert loaded.topic == "Persist test"


class TestUpdateInterviewStatus:
    """Tests for update_interview_status function."""

    def test_updates_status(self, monkeypatch, tmp_path):
        """Test update_interview_status changes status."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Status test")
        interview_id = interview.id

        updated = update_interview_status(interview_id, InterviewStatus.WAITING)

        assert updated is not None
        assert updated.status == InterviewStatus.WAITING

        # Verify persisted
        loaded = load_interview(interview_id)
        assert loaded is not None
        assert loaded.status == InterviewStatus.WAITING

    def test_returns_none_for_nonexistent(self, monkeypatch, tmp_path):
        """Test update_interview_status returns None for nonexistent interview."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = update_interview_status("int_nonexistent", InterviewStatus.ERROR)

        assert result is None

    def test_sets_started_at_on_in_progress(self, monkeypatch, tmp_path):
        """Test started_at is set when status changes to IN_PROGRESS."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Start test")
        assert interview.started_at is None

        before = datetime.now(UTC)
        updated = update_interview_status(interview.id, InterviewStatus.IN_PROGRESS)
        after = datetime.now(UTC)

        assert updated is not None
        assert updated.started_at is not None
        assert before <= updated.started_at <= after

    def test_sets_completed_at_on_complete(self, monkeypatch, tmp_path):
        """Test completed_at is set when status changes to COMPLETE."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Complete test")
        assert interview.completed_at is None

        before = datetime.now(UTC)
        updated = update_interview_status(interview.id, InterviewStatus.COMPLETE)
        after = datetime.now(UTC)

        assert updated is not None
        assert updated.completed_at is not None
        assert before <= updated.completed_at <= after

    def test_sets_completed_at_on_no_show(self, monkeypatch, tmp_path):
        """Test completed_at is set when status changes to NO_SHOW."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="No show test")

        updated = update_interview_status(interview.id, InterviewStatus.NO_SHOW)

        assert updated is not None
        assert updated.completed_at is not None

    def test_sets_completed_at_on_error(self, monkeypatch, tmp_path):
        """Test completed_at is set when status changes to ERROR."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="Error test")

        updated = update_interview_status(interview.id, InterviewStatus.ERROR)

        assert updated is not None
        assert updated.completed_at is not None

    def test_does_not_overwrite_started_at(self, monkeypatch, tmp_path):
        """Test started_at is not overwritten on subsequent updates."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        interview = create_interview(topic="No overwrite test")
        updated1 = update_interview_status(interview.id, InterviewStatus.IN_PROGRESS)
        original_started = updated1.started_at

        # Update to another status and back
        update_interview_status(interview.id, InterviewStatus.WAITING)
        updated2 = update_interview_status(interview.id, InterviewStatus.IN_PROGRESS)

        # started_at should be unchanged
        assert updated2.started_at == original_started
