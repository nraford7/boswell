"""Configuration handling for Boswell.

Manages API keys and settings. Supports two modes:
1. File-based: ~/.boswell/config.json (for CLI usage)
2. Environment variables: CLAUDE_API_KEY, etc. (for Docker/CI)

Environment variables take precedence over config file values.
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field


# Environment variable mappings
ENV_VAR_MAPPING = {
    "claude_api_key": "CLAUDE_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "deepgram_api_key": "DEEPGRAM_API_KEY",
    "daily_api_key": "DAILY_API_KEY",
    "meetingbaas_api_key": "MEETINGBAAS_API_KEY",
    "meeting_provider": "BOSWELL_MEETING_PROVIDER",
    "default_target_time": "BOSWELL_DEFAULT_TARGET_TIME",
    "default_max_time": "BOSWELL_DEFAULT_MAX_TIME",
}


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
    daily_api_key: str = Field(
        default="", description="Daily.co API key for video rooms"
    )
    meetingbaas_api_key: str = Field(
        default="", description="MeetingBaaS API key (legacy)"
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


def load_config_from_env() -> dict:
    """Load configuration values from environment variables.

    Returns:
        Dictionary of config values found in environment.
    """
    config_dict = {}
    for config_key, env_var in ENV_VAR_MAPPING.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Convert to int for numeric fields
            if config_key in ("default_target_time", "default_max_time"):
                try:
                    config_dict[config_key] = int(value)
                except ValueError:
                    pass  # Skip invalid values
            else:
                config_dict[config_key] = value
    return config_dict


def load_config() -> BoswellConfig | None:
    """Load configuration from file and/or environment variables.

    Priority: Environment variables override config file values.

    Returns:
        BoswellConfig if any configuration found, None if no config exists.

    Raises:
        ValidationError: If the config file exists but has invalid content.
    """
    config_dict = {}

    # Load from file if it exists
    config_path = get_config_path()
    if config_path.exists():
        file_config = BoswellConfig.model_validate_json(config_path.read_text())
        config_dict = file_config.model_dump()

    # Override with environment variables (they take precedence)
    env_config = load_config_from_env()
    config_dict.update(env_config)

    # Return None only if no config file AND no env vars set
    if not config_path.exists() and not env_config:
        return None

    return BoswellConfig(**config_dict)


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
        "daily_api_key": bool(config.daily_api_key.strip()),
        "meetingbaas_api_key": bool(config.meetingbaas_api_key.strip()),
    }
