"""Tests for Boswell configuration management."""

import json
from pathlib import Path

from boswell.config import (
    BoswellConfig,
    config_exists,
    get_config_dir,
    get_config_path,
    load_config,
    load_config_from_env,
    save_config,
    validate_api_keys,
)


class TestBoswellConfig:
    """Tests for the BoswellConfig Pydantic model."""

    def test_default_values(self):
        """Test that BoswellConfig has correct default values."""
        config = BoswellConfig()

        # API keys default to empty string
        assert config.claude_api_key == ""
        assert config.elevenlabs_api_key == ""
        assert config.deepgram_api_key == ""
        assert config.meetingbaas_api_key == ""

        # Settings have sensible defaults
        assert config.meeting_provider == "google_meet"
        assert config.default_target_time == 30
        assert config.default_max_time == 45

    def test_custom_values(self):
        """Test that BoswellConfig accepts custom values."""
        config = BoswellConfig(
            claude_api_key="sk-test-claude",
            elevenlabs_api_key="el-test-key",
            deepgram_api_key="dg-test-key",
            meetingbaas_api_key="mb-test-key",
            meeting_provider="zoom",
            default_target_time=20,
            default_max_time=30,
        )

        assert config.claude_api_key == "sk-test-claude"
        assert config.elevenlabs_api_key == "el-test-key"
        assert config.deepgram_api_key == "dg-test-key"
        assert config.meetingbaas_api_key == "mb-test-key"
        assert config.meeting_provider == "zoom"
        assert config.default_target_time == 20
        assert config.default_max_time == 30

    def test_json_serialization(self):
        """Test that BoswellConfig serializes to JSON correctly."""
        config = BoswellConfig(
            claude_api_key="sk-test",
            meeting_provider="zoom",
        )

        json_str = config.model_dump_json()
        data = json.loads(json_str)

        assert data["claude_api_key"] == "sk-test"
        assert data["meeting_provider"] == "zoom"
        assert data["default_target_time"] == 30
        assert data["default_max_time"] == 45

    def test_json_deserialization(self):
        """Test that BoswellConfig deserializes from JSON correctly."""
        json_str = json.dumps({
            "claude_api_key": "sk-from-json",
            "elevenlabs_api_key": "",
            "deepgram_api_key": "",
            "meetingbaas_api_key": "",
            "meeting_provider": "google_meet",
            "default_target_time": 25,
            "default_max_time": 40,
        })

        config = BoswellConfig.model_validate_json(json_str)

        assert config.claude_api_key == "sk-from-json"
        assert config.default_target_time == 25
        assert config.default_max_time == 40


class TestConfigFunctions:
    """Tests for config file functions."""

    def test_get_config_dir(self, monkeypatch, tmp_path):
        """Test get_config_dir returns ~/.boswell and creates it."""
        # Mock Path.home() to return temp directory
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config_dir = get_config_dir()

        assert config_dir == tmp_path / ".boswell"
        assert config_dir.exists()
        assert config_dir.is_dir()

    def test_get_config_path(self, monkeypatch, tmp_path):
        """Test get_config_path returns ~/.boswell/config.json."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config_path = get_config_path()

        assert config_path == tmp_path / ".boswell" / "config.json"

    def test_config_exists_false(self, monkeypatch, tmp_path):
        """Test config_exists returns False when config doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        assert config_exists() is False

    def test_config_exists_true(self, monkeypatch, tmp_path):
        """Test config_exists returns True when config exists."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create config directory and file
        config_dir = tmp_path / ".boswell"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")

        assert config_exists() is True

    def test_load_config_nonexistent(self, monkeypatch, tmp_path):
        """Test load_config returns None when config doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config = load_config()

        assert config is None

    def test_load_config_existing(self, monkeypatch, tmp_path):
        """Test load_config loads existing config correctly."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create config file
        config_dir = tmp_path / ".boswell"
        config_dir.mkdir()
        config_data = {
            "claude_api_key": "sk-loaded",
            "elevenlabs_api_key": "el-loaded",
            "deepgram_api_key": "",
            "meetingbaas_api_key": "",
            "meeting_provider": "zoom",
            "default_target_time": 35,
            "default_max_time": 50,
        }
        (config_dir / "config.json").write_text(json.dumps(config_data))

        config = load_config()

        assert config is not None
        assert config.claude_api_key == "sk-loaded"
        assert config.elevenlabs_api_key == "el-loaded"
        assert config.meeting_provider == "zoom"
        assert config.default_target_time == 35
        assert config.default_max_time == 50

    def test_save_config_creates_directory(self, monkeypatch, tmp_path):
        """Test save_config creates directory if it doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config = BoswellConfig(claude_api_key="sk-saved")

        save_config(config)

        config_path = tmp_path / ".boswell" / "config.json"
        assert config_path.exists()

    def test_save_config_content(self, monkeypatch, tmp_path):
        """Test save_config writes correct content."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config = BoswellConfig(
            claude_api_key="sk-saved",
            meeting_provider="zoom",
            default_target_time=25,
        )

        save_config(config)

        config_path = tmp_path / ".boswell" / "config.json"
        saved_data = json.loads(config_path.read_text())

        assert saved_data["claude_api_key"] == "sk-saved"
        assert saved_data["meeting_provider"] == "zoom"
        assert saved_data["default_target_time"] == 25

    def test_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        """Test that save and load work together correctly."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        original = BoswellConfig(
            claude_api_key="sk-roundtrip",
            elevenlabs_api_key="el-roundtrip",
            deepgram_api_key="dg-roundtrip",
            meetingbaas_api_key="mb-roundtrip",
            meeting_provider="zoom",
            default_target_time=20,
            default_max_time=35,
        )

        save_config(original)
        loaded = load_config()

        assert loaded is not None
        assert loaded.claude_api_key == original.claude_api_key
        assert loaded.elevenlabs_api_key == original.elevenlabs_api_key
        assert loaded.deepgram_api_key == original.deepgram_api_key
        assert loaded.meetingbaas_api_key == original.meetingbaas_api_key
        assert loaded.meeting_provider == original.meeting_provider
        assert loaded.default_target_time == original.default_target_time
        assert loaded.default_max_time == original.default_max_time


class TestValidateApiKeys:
    """Tests for validate_api_keys function."""

    def test_all_keys_empty(self):
        """Test validation with all empty keys."""
        config = BoswellConfig()

        result = validate_api_keys(config)

        assert result == {
            "claude_api_key": False,
            "elevenlabs_api_key": False,
            "deepgram_api_key": False,
            "daily_api_key": False,
            "meetingbaas_api_key": False,
        }

    def test_all_keys_set(self):
        """Test validation with all keys set."""
        config = BoswellConfig(
            claude_api_key="sk-test",
            elevenlabs_api_key="el-test",
            deepgram_api_key="dg-test",
            daily_api_key="daily-test",
            meetingbaas_api_key="mb-test",
        )

        result = validate_api_keys(config)

        assert result == {
            "claude_api_key": True,
            "elevenlabs_api_key": True,
            "deepgram_api_key": True,
            "daily_api_key": True,
            "meetingbaas_api_key": True,
        }

    def test_some_keys_set(self):
        """Test validation with some keys set."""
        config = BoswellConfig(
            claude_api_key="sk-test",
            deepgram_api_key="dg-test",
        )

        result = validate_api_keys(config)

        assert result == {
            "claude_api_key": True,
            "elevenlabs_api_key": False,
            "deepgram_api_key": True,
            "daily_api_key": False,
            "meetingbaas_api_key": False,
        }

    def test_whitespace_only_is_falsy(self):
        """Test that whitespace-only values are considered unset."""
        config = BoswellConfig(claude_api_key="   ")

        result = validate_api_keys(config)

        # Whitespace-only strings are stripped, so they are considered unset
        assert result["claude_api_key"] is False


class TestEnvironmentVariables:
    """Tests for environment variable configuration."""

    def test_load_config_from_env_empty(self, monkeypatch):
        """Test load_config_from_env returns empty dict when no env vars set."""
        # Clear any existing env vars
        for env_var in [
            "CLAUDE_API_KEY",
            "ELEVENLABS_API_KEY",
            "DEEPGRAM_API_KEY",
            "MEETINGBAAS_API_KEY",
        ]:
            monkeypatch.delenv(env_var, raising=False)

        result = load_config_from_env()

        assert result == {}

    def test_load_config_from_env_with_api_keys(self, monkeypatch):
        """Test load_config_from_env loads API keys from environment."""
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-env-claude")
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-env-key")

        result = load_config_from_env()

        assert result["claude_api_key"] == "sk-env-claude"
        assert result["deepgram_api_key"] == "dg-env-key"
        assert "elevenlabs_api_key" not in result

    def test_load_config_from_env_with_numeric_values(self, monkeypatch):
        """Test load_config_from_env converts numeric env vars correctly."""
        monkeypatch.setenv("BOSWELL_DEFAULT_TARGET_TIME", "20")
        monkeypatch.setenv("BOSWELL_DEFAULT_MAX_TIME", "40")

        result = load_config_from_env()

        assert result["default_target_time"] == 20
        assert result["default_max_time"] == 40

    def test_load_config_from_env_invalid_numeric_ignored(self, monkeypatch):
        """Test load_config_from_env ignores invalid numeric values."""
        monkeypatch.setenv("BOSWELL_DEFAULT_TARGET_TIME", "not-a-number")

        result = load_config_from_env()

        assert "default_target_time" not in result

    def test_load_config_env_overrides_file(self, monkeypatch, tmp_path):
        """Test that environment variables override config file values."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Create config file with one value
        config_dir = tmp_path / ".boswell"
        config_dir.mkdir()
        config_data = {
            "claude_api_key": "sk-from-file",
            "elevenlabs_api_key": "el-from-file",
            "deepgram_api_key": "",
            "meetingbaas_api_key": "",
            "meeting_provider": "google_meet",
            "default_target_time": 30,
            "default_max_time": 45,
        }
        (config_dir / "config.json").write_text(json.dumps(config_data))

        # Set env var to override
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-from-env")

        config = load_config()

        # Env var should override file
        assert config.claude_api_key == "sk-from-env"
        # File value should remain for non-overridden keys
        assert config.elevenlabs_api_key == "el-from-file"

    def test_load_config_env_only_no_file(self, monkeypatch, tmp_path):
        """Test load_config works with only env vars, no config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-env-only")
        monkeypatch.setenv("MEETINGBAAS_API_KEY", "mb-env-only")

        config = load_config()

        assert config is not None
        assert config.claude_api_key == "sk-env-only"
        assert config.meetingbaas_api_key == "mb-env-only"
        # Defaults for non-set values
        assert config.elevenlabs_api_key == ""
        assert config.default_target_time == 30

    def test_load_config_none_when_no_file_and_no_env(self, monkeypatch, tmp_path):
        """Test load_config returns None when no config file and no env vars."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Clear all env vars
        for env_var in [
            "CLAUDE_API_KEY",
            "ELEVENLABS_API_KEY",
            "DEEPGRAM_API_KEY",
            "MEETINGBAAS_API_KEY",
            "BOSWELL_MEETING_PROVIDER",
            "BOSWELL_DEFAULT_TARGET_TIME",
            "BOSWELL_DEFAULT_MAX_TIME",
        ]:
            monkeypatch.delenv(env_var, raising=False)

        config = load_config()

        assert config is None
