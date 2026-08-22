"""Human-in-the-loop interrupt / resume tests. Offline — no LLM."""

from __future__ import annotations

import os

import pytest

from opspilot.config import reset_settings_cache
from opspilot.graph import resume_incident, run_incident
from opspilot.schemas import HumanApprovalDecision, IncidentEvent, IncidentSource


@pytest.fixture
def force_human_approval(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPSPILOT_CONFIDENCE_THRESHOLD", "0.99")
    reset_settings_cache()
    yield
    os.environ.pop("OPSPILOT_CONFIDENCE_THRESHOLD", None)
    reset_settings_cache()


def _alert() -> IncidentEvent:
    return IncidentEvent(
        source=IncidentSource.SLACK,
        content="ALERT: api-service error rate 18% — p99 latency 4200ms",
    )


def test_interrupt_then_approve_executes(force_human_approval) -> None:
    state = run_incident(_alert(), persist=False)
    assert "__interrupt__" in state
    assert "thread_id" in state

    payload = state["__interrupt__"][0].value
    request_id = payload["request"]["request_id"]

    final = resume_incident(
        state["thread_id"],
        {
            "request_id": request_id,
            "decision": HumanApprovalDecision.APPROVED.value,
            "reviewer_id": "tester",
            "notes": "looks good",
        },
        persist=False,
    )

    assert "__interrupt__" not in final
    assert final["execution"] is not None
    assert final["execution"].success is True
    assert final.get("escalation") is None


def test_interrupt_then_reject_escalates(force_human_approval) -> None:
    state = run_incident(_alert(), persist=False)
    assert "__interrupt__" in state

    request_id = state["__interrupt__"][0].value["request"]["request_id"]
    final = resume_incident(
        state["thread_id"],
        {
            "request_id": request_id,
            "decision": HumanApprovalDecision.REJECTED.value,
            "reviewer_id": "tester",
            "notes": "too risky",
        },
        persist=False,
    )

    assert final.get("execution") is None
    assert final["escalation"] is not None
    assert "human" in final["escalation"].reason or "reject" in final["escalation"].reason


def test_default_threshold_still_auto_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPSPILOT_CONFIDENCE_THRESHOLD", raising=False)
    os.environ.pop("OPSPILOT_CONFIDENCE_THRESHOLD", None)
    reset_settings_cache()

    state = run_incident(_alert(), persist=False)
    assert "__interrupt__" not in state
    assert state["execution"].success is True
