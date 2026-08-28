"""
tests/test_github_adapter.py

Unit tests for the GitHub Issues webhook adapter. No network, no real GitHub.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from opspilot.integrations.github.adapter import (
    _build_content,
    _is_incident,
    handle_github_webhook,
)
from opspilot.integrations.github.models import (
    GitHubIssue,
    GitHubLabel,
    GitHubRepository,
    GitHubUser,
    GitHubWebhookPayload,
)


def _make_payload(**overrides) -> GitHubWebhookPayload:
    labels = [
        GitHubLabel(name=lb) for lb in overrides.get("labels", [])
    ]
    issue = GitHubIssue(
        number=overrides.get("number", 42),
        title=overrides.get("title", "API latency spike"),
        body=overrides.get("body", None),
        labels=labels,
    )
    repo = GitHubRepository(
        full_name=overrides.get("repo", "ARYANRAJ1121/OpsPilot"),
        name="OpsPilot",
    )
    return GitHubWebhookPayload(
        action=overrides.get("action", "opened"),
        issue=issue,
        repository=repo,
    )


# ---------------------------------------------------------------------------
# _is_incident detection
# ---------------------------------------------------------------------------


class TestIsIncident:
    def test_incident_label_is_incident(self) -> None:
        p = _make_payload(labels=["incident"])
        assert _is_incident(p) is True

    def test_p0_label_is_incident(self) -> None:
        p = _make_payload(labels=["p0"])
        assert _is_incident(p) is True

    def test_critical_label_is_incident(self) -> None:
        p = _make_payload(labels=["critical"])
        assert _is_incident(p) is True

    def test_production_label_is_incident(self) -> None:
        p = _make_payload(labels=["production"])
        assert _is_incident(p) is True

    def test_no_labels_no_keywords_not_incident(self) -> None:
        p = _make_payload(title="Add dark mode", labels=[])
        assert _is_incident(p) is False

    def test_keyword_in_title_is_incident(self) -> None:
        p = _make_payload(title="Production outage on payments-api")
        assert _is_incident(p) is True

    def test_keyword_in_body_is_incident(self) -> None:
        p = _make_payload(title="Investigate", body="Error rate spiked to 25%")
        assert _is_incident(p) is True

    def test_feature_request_not_incident(self) -> None:
        p = _make_payload(
            title="Add user profile page",
            body="Users want a profile page.",
            labels=["enhancement"],
        )
        assert _is_incident(p) is False

    def test_hotfix_keyword_is_incident(self) -> None:
        p = _make_payload(title="Deploy hotfix for checkout crash")
        assert _is_incident(p) is True


# ---------------------------------------------------------------------------
# _build_content
# ---------------------------------------------------------------------------


class TestBuildContent:
    def test_includes_repo_and_issue_number(self) -> None:
        p = _make_payload(repo="ARYANRAJ1121/OpsPilot", number=99)
        content = _build_content(p)
        assert "[GitHub:ARYANRAJ1121/OpsPilot#99]" in content

    def test_includes_title(self) -> None:
        p = _make_payload(title="Service down")
        content = _build_content(p)
        assert "Service down" in content

    def test_includes_labels(self) -> None:
        p = _make_payload(labels=["incident", "p0"])
        content = _build_content(p)
        assert "incident" in content
        assert "p0" in content

    def test_body_truncated(self) -> None:
        p = _make_payload(body="x" * 1000)
        content = _build_content(p)
        assert len(content) < 1100


# ---------------------------------------------------------------------------
# handle_github_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubWebhook:
    @patch("opspilot.integrations.github.adapter.run_incident")
    def test_incident_issue_triggers_pipeline(self, mock_run) -> None:
        mock_run.return_value = {"event": None, "status": "ok"}
        raw = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "Production outage on api-service",
                "body": "Error rate at 30%",
                "state": "open",
                "labels": [{"name": "incident", "color": "ff0000"}],
                "user": {"login": "aryan", "id": 1},
                "html_url": "https://github.com/test/test/issues/42",
            },
            "repository": {
                "full_name": "ARYANRAJ1121/OpsPilot",
                "name": "OpsPilot",
                "owner": {"login": "ARYANRAJ1121", "id": 1},
            },
            "sender": {"login": "aryan", "id": 1},
        }
        result = handle_github_webhook(raw, event_type="issues")
        assert result is not None
        mock_run.assert_called_once()

    @patch("opspilot.integrations.github.adapter.run_incident")
    def test_non_incident_returns_none(self, mock_run) -> None:
        raw = {
            "action": "opened",
            "issue": {
                "number": 10,
                "title": "Add dark mode",
                "body": "Would be nice to have dark mode",
                "state": "open",
                "labels": [{"name": "enhancement", "color": "00ff00"}],
                "user": {"login": "user", "id": 1},
            },
            "repository": {
                "full_name": "test/repo",
                "name": "repo",
                "owner": {"login": "test", "id": 1},
            },
            "sender": {"login": "user", "id": 1},
        }
        result = handle_github_webhook(raw, event_type="issues")
        assert result is None
        mock_run.assert_not_called()

    def test_skips_irrelevant_event_type(self) -> None:
        result = handle_github_webhook({}, event_type="push")
        assert result is None

    def test_skips_closed_action(self) -> None:
        raw = {
            "action": "closed",
            "issue": {
                "number": 1,
                "title": "outage resolved",
                "labels": [{"name": "incident", "color": "ff0000"}],
            },
            "repository": {"full_name": "test/repo"},
            "sender": {"login": "user", "id": 1},
        }
        result = handle_github_webhook(raw, event_type="issues")
        assert result is None

    def test_invalid_payload_returns_none(self) -> None:
        result = handle_github_webhook({"garbage": True}, event_type="issues")
        assert result is None
