"""
Offline evaluation harness for OpsPilot.

Runs fixed incident scenarios through the graph (heuristics only — no LLM
required) and checks structural invariants:

  - provenance must pass for valid evidence-backed proposals
  - auto-execute path must produce a successful execution
  - human-approval path must interrupt, then execute or escalate on resume
  - customer_comm branch always produces a draft
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opspilot.config import get_settings, reset_settings_cache
from opspilot.graph import resume_incident, run_incident
from opspilot.schemas import IncidentEvent, IncidentSource, RoutingDecision


@dataclass(frozen=True)
class Scenario:
    name: str
    content: str
    source: IncidentSource = IncidentSource.SLACK
    env: dict[str, str] | None = None
    on_interrupt: str | None = "approved"
    check: Callable[[dict[str, Any]], tuple[bool, str]] | None = None


def _check_auto_restart(state: dict[str, Any]) -> tuple[bool, str]:
    if "__interrupt__" in state:
        return False, "expected auto-execute, got interrupt"
    routing = state.get("routing")
    if routing is None:
        return False, "missing routing"
    if routing.routing_decision is not RoutingDecision.AUTO_EXECUTE:
        return False, f"expected auto_execute, got {routing.routing_decision.value}"
    execution = state.get("execution")
    if execution is None or not execution.success:
        return False, "expected successful execution"
    tools = [t.tool_name for t in execution.executed_tool_outputs]
    if "restart_service" not in tools:
        return False, f"expected restart_service, got {tools}"
    if state.get("customer_comm") is None:
        return False, "missing customer_comm draft"
    return True, "auto-executed restart_service"


def _check_human_then_execute(state: dict[str, Any]) -> tuple[bool, str]:
    if state.get("execution") is None or not state["execution"].success:
        return False, "expected successful execution after approval"
    if state.get("escalation") is not None:
        return False, "unexpected escalation after approval"
    return True, "human-approved then executed"


def _check_human_reject(state: dict[str, Any]) -> tuple[bool, str]:
    if state.get("execution") is not None:
        return False, "execution should not run after rejection"
    esc = state.get("escalation")
    if esc is None:
        return False, "expected escalation after rejection"
    if "reject" not in esc.reason and "human" not in esc.reason:
        return False, f"unexpected escalation reason: {esc.reason}"
    return True, "human-rejected then escalated"


def _check_provenance_intact(state: dict[str, Any]) -> tuple[bool, str]:
    # May still be interrupted; provenance is set before the interrupt.
    prov = state.get("provenance")
    if prov is None:
        return False, "missing provenance"
    if not prov.passed:
        return False, "provenance unexpectedly failed"
    if not prov.approved_proposals:
        return False, "no approved proposals"
    for p in prov.approved_proposals:
        if not p.evidence_refs:
            return False, f"proposal {p.tool_name} has empty evidence_refs"
    return True, f"{len(prov.approved_proposals)} provenance-valid proposal(s)"


SCENARIOS: list[Scenario] = [
    Scenario(
        name="degraded_api_auto_restart",
        content="ALERT: api-service error rate 18% — p99 latency 4200ms",
        check=_check_auto_restart,
        on_interrupt=None,
    ),
    Scenario(
        name="provenance_citations_valid",
        content="ALERT: api-service error rate 18% — CrashLoopBackOff pods",
        check=_check_provenance_intact,
        # Provenance is available before interrupt; no need to resume for this check.
        on_interrupt=None,
    ),
    Scenario(
        name="low_confidence_approve_then_execute",
        content="ALERT: api-service error rate 18% — p99 latency 4200ms",
        env={"OPSPILOT_CONFIDENCE_THRESHOLD": "0.99"},
        on_interrupt="approved",
        check=_check_human_then_execute,
    ),
    Scenario(
        name="low_confidence_reject_then_escalate",
        content="ALERT: api-service error rate 18% — p99 latency 4200ms",
        env={"OPSPILOT_CONFIDENCE_THRESHOLD": "0.99"},
        on_interrupt="rejected",
        check=_check_human_reject,
    ),
]


def run_scenario(scenario: Scenario) -> dict[str, Any]:
    saved = {k: os.environ.get(k) for k in (scenario.env or {})}
    try:
        for k, v in (scenario.env or {}).items():
            os.environ[k] = v
        if scenario.env:
            reset_settings_cache()
            _ = get_settings()

        event = IncidentEvent(source=scenario.source, content=scenario.content)
        state = run_incident(event, persist=False)

        if "__interrupt__" in state:
            if scenario.on_interrupt is None:
                # Allowed for checks that only inspect pre-interrupt state.
                check = scenario.check or (lambda s: (True, "no check"))
                ok, detail = check(state)
                return {"name": scenario.name, "ok": ok, "detail": detail}

            interrupt = state["__interrupt__"][0]
            payload = interrupt.value if hasattr(interrupt, "value") else interrupt
            request_id = (payload.get("request") or {}).get("request_id")
            state = resume_incident(
                state["thread_id"],
                {
                    "request_id": request_id,
                    "decision": scenario.on_interrupt,
                    "reviewer_id": "eval-harness",
                    "notes": f"eval:{scenario.name}",
                },
                persist=False,
            )

        check = scenario.check or (lambda s: (True, "no check"))
        ok, detail = check(state)
        return {"name": scenario.name, "ok": ok, "detail": detail}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if scenario.env:
            reset_settings_cache()


def run_eval_suite(scenarios: list[Scenario] | None = None) -> dict[str, Any]:
    rows = [run_scenario(s) for s in (scenarios or SCENARIOS)]
    passed = sum(1 for r in rows if r["ok"])
    failed = len(rows) - passed
    return {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "results": rows,
    }
