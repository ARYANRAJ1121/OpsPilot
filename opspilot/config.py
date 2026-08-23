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

    @property
    def llm_active(self) -> bool:
        """True only when an LLM is both enabled and has credentials."""
        return self.llm_enabled and bool(self.groq_api_key)


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
    )


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that patch env vars)."""
    get_settings.cache_clear()
