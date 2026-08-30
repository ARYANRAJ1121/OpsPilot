"""Approvals UI auth + webhook smoke tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from opspilot.config import Settings, reset_settings_cache
from opspilot.server import create_app
from opspilot.smoke_webhooks import run_webhook_smokes


def _settings(**overrides) -> Settings:
    base = dict(
        groq_api_key=None,
        llm_model="openai/gpt-oss-20b",
        llm_temperature=0.1,
        llm_enabled=False,
        confidence_auto_execute_threshold=0.7,
        trace_dir=__import__("pathlib").Path("trace_store"),
        slack_bot_token=None,
        slack_signing_secret=None,
        slack_app_token=None,
        slack_allowed_channels=(),
        slack_status_poll_seconds=5.0,
        slack_ack_timeout_seconds=3.0,
        slack_max_incidents_per_minute=30,
        guardrails_enabled=True,
        guardrails_llm=False,
        llm_planning=False,
        llm_planning_model="llama-3.3-70b-versatile",
        jira_webhook_secret="jira-test-secret",
        github_webhook_secret="gh-test-secret",
        webhook_require_signatures=True,
        checkpoint_backend="memory",
        checkpoint_path=__import__("pathlib").Path("trace_store/checkpoints.sqlite"),
        approval_queue_path=__import__("pathlib").Path("trace_store/pending_approvals.json"),
        approval_api_token="secret-token",
        remediation_mode="simulated",
        tickets_webhook_secret=None,
        logs_webhook_secret=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def locked_client(monkeypatch):
    reset_settings_cache()
    s = _settings()
    monkeypatch.setattr("opspilot.server.get_settings", lambda: s)
    monkeypatch.setattr("opspilot.approvals_ui.get_settings", lambda: s)
    with (
        patch("opspilot.server.build_bolt_app", return_value=MagicMock()),
        patch("opspilot.server.get_adapter", return_value=MagicMock()),
        patch("opspilot.server.AsyncSlackRequestHandler", return_value=MagicMock()),
    ):
        with TestClient(create_app()) as c:
            yield c
    reset_settings_cache()


class TestApprovalsAuth:
    def test_page_requires_token(self, locked_client: TestClient) -> None:
        assert locked_client.get("/approvals").status_code == 401
        ok = locked_client.get("/approvals", params={"token": "secret-token"})
        assert ok.status_code == 200
        assert "OpsPilot" in ok.text

    def test_api_requires_token(self, locked_client: TestClient) -> None:
        assert locked_client.get("/api/approvals").status_code == 401
        ok = locked_client.get(
            "/api/approvals", headers={"X-OpsPilot-Token": "secret-token"}
        )
        assert ok.status_code == 200
        assert ok.json()["count"] == 0


class TestWebhookSmoke:
    def test_all_adapters_pass(self) -> None:
        rows = run_webhook_smokes()
        assert rows
        assert all(ok for _, ok, _ in rows)
