# src/boswell/server/config.py
"""Server configuration."""

import os
from dataclasses import dataclass, field
from functools import lru_cache


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""

    pass


def _require_env(name: str) -> str:
    """Get a required environment variable or raise an error."""
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"Required environment variable {name} is not set")
    return value


@dataclass
class Settings:
    """Application settings from environment variables."""

    # Database
    database_url: str

    # External services
    daily_api_key: str
    daily_domain: str  # Daily.co subdomain (e.g., "emirbot" for emirbot.daily.co)
    claude_api_key: str
    deepgram_api_key: str
    elevenlabs_api_key: str
    resend_api_key: str
    sender_email: str

    # App config
    secret_key: str
    base_url: str

    # Defaults
    session_expire_days: int = 7
    magic_link_expire_days: int = 7
    debug: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables.

        Required variables:
            DATABASE_URL: PostgreSQL connection string
            DAILY_API_KEY: Daily.co API key for video rooms
            CLAUDE_API_KEY: Anthropic Claude API key
            DEEPGRAM_API_KEY: Deepgram API key for STT
            ELEVENLABS_API_KEY: ElevenLabs API key for TTS
            RESEND_API_KEY: Resend API key for email
            SECRET_KEY: Secret key for session signing (required in production)

        Optional variables:
            BASE_URL: Base URL for the application (default: http://localhost:8000)

        Raises:
            ConfigurationError: If any required variable is missing.
        """
        # SECRET_KEY has a dev default but should be set in production
        secret_key = os.environ.get("SECRET_KEY", "")
        if not secret_key:
            if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PRODUCTION"):
                raise ConfigurationError(
                    "SECRET_KEY must be set in production environment"
                )
            secret_key = "dev-secret-change-me"

        # Debug mode: explicitly enabled via DEBUG env var (Vite dev server has cross-origin issues)
        debug = os.environ.get("DEBUG", "").lower() in ("true", "1", "yes")

        return cls(
            database_url=_require_env("DATABASE_URL"),
            daily_api_key=_require_env("DAILY_API_KEY"),
            daily_domain=os.environ.get("DAILY_DOMAIN", "emirbot"),
            claude_api_key=_require_env("CLAUDE_API_KEY"),
            deepgram_api_key=_require_env("DEEPGRAM_API_KEY"),
            elevenlabs_api_key=_require_env("ELEVENLABS_API_KEY"),
            resend_api_key=_require_env("RESEND_API_KEY"),
            sender_email=os.environ.get("SENDER_EMAIL", "Boswell <boswell@emirintelligence.com>"),
            secret_key=secret_key,
            base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
            debug=debug,
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings.from_env()
