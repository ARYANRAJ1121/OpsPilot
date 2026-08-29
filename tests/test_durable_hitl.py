"""Durable approval queue + SQLite checkpoint resume."""

from __future__ import annotations

import os

import pytest

from opspilot.approval_queue import clear_queue, get_by_thread, list_pending
from opspilot.config import reset_settings_cache
from opspilot.graph import reset_graph_app, resume_incident, run_incident
from opspilot.schemas import HumanApprovalDecision, IncidentEvent, IncidentSource


@pytest.fixture
def force_human(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("OPSPILOT_CONFIDENCE_THRESHOLD", "0.99")
    monkeypatch.setenv("OPSPILOT_CHECKPOINT_BACKEND", "sqlite")
    monkeypatch.setenv(
        "OPSPILOT_CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite")
    )
    monkeypatch.setenv(
        "OPSPILOT_APPROVAL_QUEUE_PATH", str(tmp_path / "pending.json")
    )
    reset_settings_cache()
    reset_graph_app()
    clear_queue()
    yield
    clear_queue()
    reset_graph_app()
    os.environ.pop("OPSPILOT_CONFIDENCE_THRESHOLD", None)
    reset_settings_cache()


def test_interrupt_registers_durable_queue(force_human) -> None:
    state = run_incident(
        IncidentEvent(
            source=IncidentSource.SLACK,
            content="ALERT: api-service error rate 18%",
        ),
        persist=False,
    )
    assert "__interrupt__" in state
    pending = list_pending()
    assert len(pending) == 1
    assert pending[0].thread_id == state["thread_id"]
    assert get_by_thread(state["thread_id"]) is not None


def test_sqlite_checkpoint_survives_graph_reset(force_human) -> None:
    state = run_incident(
        IncidentEvent(
            source=IncidentSource.SLACK,
            content="ALERT: api-service error rate 18%",
        ),
        persist=False,
    )
    assert "__interrupt__" in state
    thread_id = state["thread_id"]
    request_id = state["__interrupt__"][0].value["request"]["request_id"]

    # Simulate process bounce: drop compiled graph, keep SQLite file.
    reset_graph_app()

    final = resume_incident(
        thread_id,
        {
            "request_id": request_id,
            "decision": HumanApprovalDecision.APPROVED.value,
            "reviewer_id": "durability-test",
        },
        persist=False,
    )
    assert "__interrupt__" not in final
    assert final["execution"] is not None
    assert list_pending() == []
