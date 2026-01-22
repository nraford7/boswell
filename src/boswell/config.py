"""Configuration handling for Boswell.

Manages API keys and settings stored in ~/.boswell/config.json
"""

from pathlib import Path

from pydantic import BaseModel, Field


class BoswellConfig(BaseModel):
    """Configuration model for Boswell."""

    claude_api_key: str | None = Field(
        default=None, description="Anthropic Claude API key"
    )
    elevenlabs_api_key: str | None = Field(
        default=None, description="ElevenLabs TTS API key"
    )
    deepgram_api_key: str | None = Field(
        default=None, description="Deepgram STT API key"
    )
    meetingbaas_api_key: str | None = Field(
        default=None, description="MeetingBaaS API key"
    )
    meeting_provider: str = Field(
        default="google_meet", description="Meeting provider"
    )
    default_target_time: int = Field(
        default=30, description="Default target interview time in minutes"
    )
    default_max_time: int = Field(
        default=45, description="Default maximum interview time in minutes"
    )


def get_config_path() -> Path:
    """Get the path to the Boswell config file."""
    return Path.home() / ".boswell" / "config.json"


def load_config() -> BoswellConfig | None:
    """Load configuration from ~/.boswell/config.json."""
    config_path = get_config_path()
    if not config_path.exists():
        return None
    return BoswellConfig.model_validate_json(config_path.read_text())


def save_config(config: BoswellConfig) -> None:
    """Save configuration to ~/.boswell/config.json."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config.model_dump_json(indent=2))
