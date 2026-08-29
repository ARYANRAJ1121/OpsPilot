"""Ticket and logs webhook adapter unit tests."""

from __future__ import annotations

from unittest.mock import patch

from opspilot.integrations.logs.adapter import _is_incident as logs_is_incident
from opspilot.integrations.logs.adapter import handle_logs_webhook
from opspilot.integrations.tickets.adapter import _is_incident as ticket_is_incident
from opspilot.integrations.tickets.adapter import handle_ticket_webhook
from opspilot.schemas import IncidentSource


class TestTickets:
    def test_detects_urgent(self) -> None:
        assert ticket_is_incident(
            {"id": 1, "subject": "help", "priority": "urgent", "description": "x"}
        )

    def test_skips_noise(self) -> None:
        assert not ticket_is_incident(
            {"id": 2, "subject": "password reset", "priority": "low", "description": "please"}
        )

    def test_handle_triages(self) -> None:
        with patch("opspilot.integrations.tickets.adapter.run_incident") as run:
            run.return_value = {"ok": True}
            result = handle_ticket_webhook(
                {
                    "id": "T-9",
                    "subject": "production outage",
                    "priority": "high",
                    "description": "api down",
                }
            )
        assert result == {"ok": True}
        event = run.call_args.args[0]
        assert event.source is IncidentSource.SUPPORT_TICKET


class TestLogs:
    def test_alertmanager_firing(self) -> None:
        assert logs_is_incident(
            {
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "HighErrorRate", "severity": "critical"},
                        "annotations": {"summary": "error rate high"},
                    }
                ],
            }
        )

    def test_handle_triages(self) -> None:
        with patch("opspilot.integrations.logs.adapter.run_incident") as run:
            run.return_value = {"ok": True}
            result = handle_logs_webhook(
                {"level": "error", "service": "api", "message": "crash loop"}
            )
        assert result == {"ok": True}
        assert run.call_args.args[0].source is IncidentSource.LOGS
