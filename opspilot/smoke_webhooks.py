"""Offline smoke checks for Jira / GitHub / tickets / logs webhook handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from opspilot.integrations.github.adapter import handle_github_webhook
from opspilot.integrations.jira.adapter import handle_jira_webhook
from opspilot.integrations.logs.adapter import handle_logs_webhook
from opspilot.integrations.tickets.adapter import handle_ticket_webhook


def _fake_state() -> dict[str, Any]:
    return {"status": "smoked", "execution": {"success": True}}


def run_webhook_smokes() -> list[tuple[str, bool, str]]:
    """
    Exercise each ingest adapter with a representative payload.

    Graph execution is mocked so this stays offline and free.
    Returns list of (name, ok, detail).
    """
    results: list[tuple[str, bool, str]] = []

    jira_payload = {
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "OPS-1",
            "fields": {
                "summary": "production outage api-service",
                "description": "error rate spike",
                "priority": {"name": "Highest"},
                "issuetype": {"name": "Incident"},
                "status": {"name": "Open"},
                "labels": ["incident"],
                "project": {"key": "OPS", "name": "Ops"},
            },
        },
    }
    github_payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "incident: api latency critical",
            "body": "p99 5s",
            "labels": [{"name": "incident"}],
            "html_url": "https://github.com/example/repo/issues/42",
            "user": {"login": "ops"},
        },
        "repository": {"full_name": "example/repo", "name": "repo"},
    }
    ticket_payload = {
        "id": "T-100",
        "subject": "production outage",
        "priority": "urgent",
        "description": "checkout down",
        "tags": ["incident"],
    }
    logs_payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighErrorRate", "severity": "critical"},
                "annotations": {"summary": "error rate 20%"},
            }
        ],
    }

    cases: list[tuple[str, Any, Any]] = [
        ("jira", handle_jira_webhook, jira_payload),
        ("github", lambda p: handle_github_webhook(p, "issues"), github_payload),
        ("tickets", handle_ticket_webhook, ticket_payload),
        ("logs", handle_logs_webhook, logs_payload),
    ]

    with patch("opspilot.integrations.jira.adapter.run_incident", return_value=_fake_state()):
        with patch(
            "opspilot.integrations.github.adapter.run_incident", return_value=_fake_state()
        ):
            with patch(
                "opspilot.integrations.tickets.adapter.run_incident",
                return_value=_fake_state(),
            ):
                with patch(
                    "opspilot.integrations.logs.adapter.run_incident",
                    return_value=_fake_state(),
                ):
                    for name, fn, payload in cases:
                        try:
                            out = fn(payload)
                            ok = out is not None
                            detail = "triaged" if ok else "skipped/ignored"
                            results.append((name, ok, detail))
                        except Exception as exc:  # pragma: no cover
                            results.append((name, False, str(exc)))
    return results


def main() -> int:
    print("OpsPilot webhook smoke (offline, mocked graph)")
    rows = run_webhook_smokes()
    failed = 0
    for name, ok, detail in rows:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}: {detail}")
        if not ok:
            failed += 1
    print(f"{len(rows) - failed}/{len(rows)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
