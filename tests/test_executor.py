"""Remediation executor modes."""

from __future__ import annotations

import pytest

from opspilot.config import reset_settings_cache
from opspilot.tools.executor import clear_tool_overrides, execute_tool, register_tool_override


@pytest.fixture(autouse=True)
def _clean_overrides():
    clear_tool_overrides()
    yield
    clear_tool_overrides()


def test_simulated_default() -> None:
    out = execute_tool("fetch_logs", {"service": "api"})
    assert out.tool_name == "fetch_logs"
    assert "dry_run" not in out.result


def test_dry_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPSPILOT_REMEDIATION_MODE", "dry_run")
    reset_settings_cache()
    out = execute_tool("restart_service", {"service": "api"})
    assert out.result.get("dry_run") is True
    reset_settings_cache()


def test_override() -> None:
    register_tool_override("fetch_logs", lambda p: {"custom": True, "service": p.get("service")})
    out = execute_tool("fetch_logs", {"service": "billing"})
    assert out.result == {"custom": True, "service": "billing"}
