"""End-to-end graph test. Offline — simulated tools only."""

from opspilot.graph import run_incident
from opspilot.schemas import IncidentEvent, IncidentSource, RoutingDecision


def test_degraded_api_auto_executes_restart() -> None:
    event = IncidentEvent(
        source=IncidentSource.SLACK,
        content="ALERT: api-service error rate 18% — p99 latency 4200ms",
    )
    state = run_incident(event)

    assert state["router"].severity.value == "high"
    assert state["customer_comm"].message_draft
    assert state["provenance"].passed is True
    assert state["policy"].any_requires_human is False
    assert state["routing"].routing_decision is RoutingDecision.AUTO_EXECUTE
    assert state["execution"].success is True
    assert any(t.tool_name == "restart_service" for t in state["execution"].executed_tool_outputs)

    agent_names = {t.agent_name for t in state["traces"]}
    assert "customer_communication" in agent_names
    assert "provenance_gate" in agent_names
    assert "execution" in agent_names
