"""Configuration handling for Boswell.

Manages API keys and settings stored in ~/.boswell/config.json
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class BoswellConfig(BaseModel):
    """Configuration model for Boswell.

    API keys default to empty string. Non-API-key fields have sensible defaults.
    """

    claude_api_key: str = Field(
        default="", description="Anthropic Claude API key"
    )
    elevenlabs_api_key: str = Field(
        default="", description="ElevenLabs TTS API key"
    )
    deepgram_api_key: str = Field(
        default="", description="Deepgram STT API key"
    )
    meetingbaas_api_key: str = Field(
        default="", description="MeetingBaaS API key"
    )
    meeting_provider: str = Field(
        default="google_meet", description="Meeting provider (google_meet or zoom)"
    )
    default_target_time: int = Field(
        default=30, description="Default target interview time in minutes"
    )
    default_max_time: int = Field(
        default=45, description="Default maximum interview time in minutes"
    )


def get_config_dir() -> Path:
    """Get the Boswell config directory (~/.boswell).

    Creates the directory if it doesn't exist.

    Returns:
        Path to the config directory.
    """
    config_dir = Path.home() / ".boswell"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Get the path to the Boswell config file (~/.boswell/config.json).

    Returns:
        Path to the config file.
    """
    return Path.home() / ".boswell" / "config.json"


def config_exists() -> bool:
    """Check if the config file exists.

    Returns:
        True if config file exists, False otherwise.
    """
    return get_config_path().exists()


def load_config() -> BoswellConfig | None:
    """Load configuration from ~/.boswell/config.json.

    Returns:
        BoswellConfig if file exists and is valid, None if file doesn't exist.

    Raises:
        ValidationError: If the config file exists but has invalid content.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return None
    return BoswellConfig.model_validate_json(config_path.read_text())


def save_config(config: BoswellConfig) -> None:
    """Save configuration to ~/.boswell/config.json.

    Creates the config directory if it doesn't exist.
    Sets file permissions to 0600 to protect API keys.

    Args:
        config: The configuration to save.
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2))
    # Set restrictive permissions (owner read/write only) to protect API keys
    os.chmod(config_path, 0o600)


def validate_api_keys(config: BoswellConfig) -> dict[str, bool]:
    """Check which API keys are set (non-empty).

    Args:
        config: The configuration to validate.

    Returns:
        Dictionary mapping API key names to whether they are set (non-empty).
    """
    return {
        "claude_api_key": bool(config.claude_api_key.strip()),
        "elevenlabs_api_key": bool(config.elevenlabs_api_key.strip()),
        "deepgram_api_key": bool(config.deepgram_api_key.strip()),
        "meetingbaas_api_key": bool(config.meetingbaas_api_key.strip()),
    }
