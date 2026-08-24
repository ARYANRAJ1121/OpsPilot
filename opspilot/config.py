"""
opspilot/config.py

Central runtime configuration. Values come from environment variables
(loaded from a local .env when present). Everything has a safe default so
the system runs fully offline with zero configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of runtime settings."""

    groq_api_key: str | None
    llm_model: str
    llm_temperature: float
    llm_enabled: bool
    confidence_auto_execute_threshold: float
    trace_dir: Path
    # Slack adapter
    slack_bot_token: str | None
    slack_signing_secret: str | None
    slack_app_token: str | None
    slack_allowed_channels: tuple[str, ...]
    slack_status_poll_seconds: float
    slack_ack_timeout_seconds: float
    slack_max_incidents_per_minute: int

    @property
    def llm_active(self) -> bool:
        """True only when an LLM is both enabled and has credentials."""
        return self.llm_enabled and bool(self.groq_api_key)

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_bot_token and self.slack_signing_secret)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once and cache them for the process lifetime."""
    trace_dir = Path(os.getenv("OPSPILOT_TRACE_DIR", "trace_store")).expanduser()
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        llm_model=os.getenv("OPSPILOT_LLM_MODEL", "openai/gpt-oss-20b"),
        llm_temperature=_env_float("OPSPILOT_LLM_TEMPERATURE", 0.1),
        llm_enabled=_env_bool("OPSPILOT_LLM_ENABLED", True),
        confidence_auto_execute_threshold=_env_float(
            "OPSPILOT_CONFIDENCE_THRESHOLD", 0.7
        ),
        trace_dir=trace_dir,
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN") or None,
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET") or None,
        slack_app_token=os.getenv("SLACK_APP_TOKEN") or None,
        slack_allowed_channels=_env_csv("SLACK_ALLOWED_CHANNELS"),
        slack_status_poll_seconds=_env_float("SLACK_STATUS_POLL_SECONDS", 5.0),
        slack_ack_timeout_seconds=_env_float("SLACK_ACK_TIMEOUT_SECONDS", 3.0),
        slack_max_incidents_per_minute=_env_int("SLACK_MAX_INCIDENTS_PER_MINUTE", 30),
    )


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that patch env vars)."""
    get_settings.cache_clear()
