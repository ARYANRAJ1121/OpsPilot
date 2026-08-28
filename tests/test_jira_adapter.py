"""
tests/test_jira_adapter.py

Unit tests for the Jira webhook adapter. No network, no real Jira.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from opspilot.integrations.jira.adapter import _build_content, _is_incident, handle_jira_webhook
from opspilot.integrations.jira.models import (
    JiraFields,
    JiraIssue,
    JiraIssueType,
    JiraPriority,
    JiraWebhookPayload,
)


def _make_payload(**overrides) -> JiraWebhookPayload:
    fields = JiraFields(
        summary=overrides.get("summary", "API latency spike in production"),
        description=overrides.get("description", None),
        priority=JiraPriority(name=overrides.get("priority", "Medium")),
        issuetype=JiraIssueType(name=overrides.get("issuetype", "Task")),
        labels=overrides.get("labels", []),
    )
    issue = JiraIssue(
        id="10001",
        key=overrides.get("key", "OPS-42"),
        fields=fields,
    )
    return JiraWebhookPayload(
        webhookEvent=overrides.get("event", "jira:issue_created"),
        issue=issue,
    )


# ---------------------------------------------------------------------------
# _is_incident detection
# ---------------------------------------------------------------------------


class TestIsIncident:
    def test_high_priority_is_incident(self) -> None:
        p = _make_payload(priority="High")
        assert _is_incident(p) is True

    def test_blocker_priority_is_incident(self) -> None:
        p = _make_payload(priority="Blocker")
        assert _is_incident(p) is True

    def test_medium_priority_no_keywords_not_incident(self) -> None:
        p = _make_payload(summary="Update documentation", priority="Medium")
        assert _is_incident(p) is False

    def test_incident_label_is_incident(self) -> None:
        p = _make_payload(labels=["incident"], priority="Low")
        assert _is_incident(p) is True

    def test_sev0_label_is_incident(self) -> None:
        p = _make_payload(labels=["sev0"], priority="Low")
        assert _is_incident(p) is True

    def test_keyword_in_summary_is_incident(self) -> None:
        p = _make_payload(summary="Production outage on payments-api", priority="Medium")
        assert _is_incident(p) is True

    def test_keyword_in_description_is_incident(self) -> None:
        p = _make_payload(
            summary="Investigate issue",
            description="Error rate spiked to 25% in checkout-api",
            priority="Medium",
        )
        assert _is_incident(p) is True

    def test_bug_issuetype_is_incident(self) -> None:
        p = _make_payload(issuetype="Bug", priority="Medium", summary="Fix button color")
        assert _is_incident(p) is True

    def test_feature_request_not_incident(self) -> None:
        p = _make_payload(
            summary="Add dark mode to dashboard",
            priority="Low",
            issuetype="Story",
        )
        assert _is_incident(p) is False


# ---------------------------------------------------------------------------
# _build_content
# ---------------------------------------------------------------------------


class TestBuildContent:
    def test_includes_issue_key(self) -> None:
        p = _make_payload(key="OPS-99")
        content = _build_content(p)
        assert "[JIRA:OPS-99]" in content

    def test_includes_priority(self) -> None:
        p = _make_payload(priority="Highest")
        content = _build_content(p)
        assert "[Highest]" in content

    def test_includes_summary(self) -> None:
        p = _make_payload(summary="API timeout on checkout")
        content = _build_content(p)
        assert "API timeout on checkout" in content

    def test_includes_description_truncated(self) -> None:
        p = _make_payload(description="x" * 1000)
        content = _build_content(p)
        # Description should be truncated
        assert len(content) < 1100


# ---------------------------------------------------------------------------
# handle_jira_webhook
# ---------------------------------------------------------------------------


class TestHandleJiraWebhook:
    @patch("opspilot.integrations.jira.adapter.run_incident")
    def test_incident_payload_triggers_pipeline(self, mock_run) -> None:
        mock_run.return_value = {"event": None, "status": "ok"}
        raw = {
            "webhookEvent": "jira:issue_created",
            "issue": {
                "id": "10001",
                "key": "OPS-42",
                "fields": {
                    "summary": "Production outage on api-service",
                    "priority": {"name": "Highest"},
                    "issuetype": {"name": "Bug"},
                    "status": {"name": "Open"},
                    "project": {"key": "OPS"},
                    "labels": ["incident"],
                },
            },
        }
        result = handle_jira_webhook(raw)
        assert result is not None
        mock_run.assert_called_once()

    @patch("opspilot.integrations.jira.adapter.run_incident")
    def test_non_incident_payload_returns_none(self, mock_run) -> None:
        raw = {
            "webhookEvent": "jira:issue_created",
            "issue": {
                "id": "10002",
                "key": "FEAT-10",
                "fields": {
                    "summary": "Add dark mode to admin panel",
                    "priority": {"name": "Low"},
                    "issuetype": {"name": "Story"},
                    "status": {"name": "Open"},
                    "project": {"key": "FEAT"},
                    "labels": [],
                },
            },
        }
        result = handle_jira_webhook(raw)
        assert result is None
        mock_run.assert_not_called()

    def test_invalid_payload_returns_none(self) -> None:
        result = handle_jira_webhook({"garbage": True})
        # Should not crash — just returns None if no incident detected
        # (malformed payload with no incident signal)
        assert result is None
