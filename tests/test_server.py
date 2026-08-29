"""Tests for unified OpsPilot ingest server (signature + health)."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from opspilot.config import Settings, reset_settings_cache
from opspilot.server import create_app


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
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def client(monkeypatch):
    reset_settings_cache()
    s = _settings()
    monkeypatch.setattr("opspilot.server.get_settings", lambda: s)

    # Avoid real Slack Bolt init requiring tokens during lifespan
    fake_bolt = MagicMock()
    with (
        patch("opspilot.server.build_bolt_app", return_value=fake_bolt),
        patch("opspilot.server.get_adapter", return_value=MagicMock()),
        patch(
            "opspilot.server.AsyncSlackRequestHandler",
            return_value=MagicMock(),
        ),
    ):
        app = create_app()
        with TestClient(app) as c:
            yield c
    reset_settings_cache()


class TestHealthz:
    def test_ok(self, client: TestClient) -> None:
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "integrations" in body


class TestGitHubAuth:
    def test_rejects_bad_signature(self, client: TestClient) -> None:
        r = client.post(
            "/github/webhook",
            content=b'{"action":"opened","issue":{}}',
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert r.status_code == 401

    def test_accepts_valid_signature(self, client: TestClient) -> None:
        body = b'{"action":"opened","issue":{"number":1,"title":"x","labels":[]}}'
        secret = "gh-test-secret"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch("opspilot.server.handle_github_webhook", return_value=None):
            r = client.post(
                "/github/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "issues",
                    "X-Hub-Signature-256": sig,
                },
            )
        assert r.status_code == 202


class TestJiraAuth:
    def test_rejects_without_secret(self, client: TestClient) -> None:
        r = client.post(
            "/jira/webhook",
            content=b'{"webhookEvent":"jira:issue_created"}',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    def test_accepts_shared_secret_header(self, client: TestClient) -> None:
        with patch("opspilot.server.handle_jira_webhook", return_value=None):
            r = client.post(
                "/jira/webhook",
                content=b'{"webhookEvent":"jira:issue_created"}',
                headers={
                    "Content-Type": "application/json",
                    "X-OpsPilot-Webhook-Secret": "jira-test-secret",
                },
            )
        assert r.status_code == 202
