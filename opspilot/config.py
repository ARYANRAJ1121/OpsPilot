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
    # Guardrails (deterministic always; optional Groq judge)
    guardrails_enabled: bool
    guardrails_llm: bool
    # LLM-driven tool selection / action planning
    llm_planning: bool
    llm_planning_model: str
    # Jira / GitHub webhook secrets
    jira_webhook_secret: str | None
    github_webhook_secret: str | None
    webhook_require_signatures: bool
    # Durable HITL / checkpoints
    checkpoint_backend: str  # "sqlite" | "memory"
    checkpoint_path: Path
    approval_queue_path: Path
    approval_api_token: str | None
    # Remediation: simulated | dry_run ($0). Real cloud via register_tool_override.
    remediation_mode: str
    tickets_webhook_secret: str | None
    logs_webhook_secret: str | None
    # Local tunnel only — skips Bolt request signature checks
    slack_skip_request_verification: bool = False

    @property
    def llm_active(self) -> bool:
        """True only when an LLM is both enabled and has credentials."""
        return self.llm_enabled and bool(self.groq_api_key)

    @property
    def llm_planning_active(self) -> bool:
        """True when LLM-driven tool/action planning is enabled and usable."""
        return self.llm_active and self.llm_planning

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_bot_token and self.slack_signing_secret)

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_webhook_secret) or not self.webhook_require_signatures

    @property
    def github_configured(self) -> bool:
        return bool(self.github_webhook_secret) or not self.webhook_require_signatures

    @property
    def tickets_configured(self) -> bool:
        return bool(self.tickets_webhook_secret) or not self.webhook_require_signatures

    @property
    def logs_configured(self) -> bool:
        return bool(self.logs_webhook_secret) or not self.webhook_require_signatures


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
        guardrails_enabled=_env_bool("OPSPILOT_GUARDRAILS_ENABLED", True),
        guardrails_llm=_env_bool("OPSPILOT_GUARDRAILS_LLM", False),
        llm_planning=_env_bool("OPSPILOT_LLM_PLANNING", True),
        llm_planning_model=os.getenv(
            "OPSPILOT_LLM_PLANNING_MODEL", "llama-3.3-70b-versatile"
        ),
        jira_webhook_secret=os.getenv("JIRA_WEBHOOK_SECRET") or None,
        github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET") or None,
        webhook_require_signatures=_env_bool(
            # Prefer signed webhooks. Set false explicitly for local unsigned smoke.
            "OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES",
            True,
        ),
        checkpoint_backend=os.getenv("OPSPILOT_CHECKPOINT_BACKEND", "sqlite")
        .strip()
        .lower(),
        checkpoint_path=Path(
            os.getenv("OPSPILOT_CHECKPOINT_PATH", str(trace_dir / "checkpoints.sqlite"))
        ).expanduser(),
        approval_queue_path=Path(
            os.getenv(
                "OPSPILOT_APPROVAL_QUEUE_PATH",
                str(trace_dir / "pending_approvals.json"),
            )
        ).expanduser(),
        approval_api_token=os.getenv("OPSPILOT_APPROVAL_API_TOKEN") or None,
        remediation_mode=os.getenv("OPSPILOT_REMEDIATION_MODE", "simulated")
        .strip()
        .lower(),
        tickets_webhook_secret=os.getenv("TICKETS_WEBHOOK_SECRET") or None,
        logs_webhook_secret=os.getenv("LOGS_WEBHOOK_SECRET") or None,
        slack_skip_request_verification=_env_bool(
            "OPSPILOT_SLACK_SKIP_REQUEST_VERIFICATION", False
        ),
    )


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that patch env vars)."""
    get_settings.cache_clear()
