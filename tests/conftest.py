"""Pytest defaults — ephemeral memory checkpointer + temp approval queue."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ephemeral_persistence(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("OPSPILOT_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv(
        "OPSPILOT_APPROVAL_QUEUE_PATH", str(tmp_path / "pending_approvals.json")
    )
    monkeypatch.setenv("OPSPILOT_REMEDIATION_MODE", "simulated")
    monkeypatch.setenv("OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES", "false")

    from opspilot.approval_queue import clear_queue
    from opspilot.config import reset_settings_cache
    from opspilot.graph import reset_graph_app

    reset_settings_cache()
    reset_graph_app()
    clear_queue()
    yield
    clear_queue()
    reset_graph_app()
    reset_settings_cache()
