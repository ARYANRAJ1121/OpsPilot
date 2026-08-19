"""Unit tests for heuristic agents. Offline — no LLM, no network."""

from opspilot.agents.action_planner import run_action_planner
from opspilot.agents.evidence_diagnosis import run_evidence_diagnosis
from opspilot.agents.ingestion import run_ingestion
from opspilot.agents.investigation import run_investigation
from opspilot.agents.knowledge_retrieval import run_knowledge_retrieval
from opspilot.agents.router import run_router
from opspilot.schemas import IncidentEvent, IncidentSource, Severity


def _ingested(content: str):
    event = IncidentEvent(source=IncidentSource.SLACK, content=content)
    return event, run_ingestion(event)


class TestIngestionAndRouter:
    def test_strips_alert_prefix(self) -> None:
        _, ingestion = _ingested("ALERT: api-service error rate 18%")
        assert ingestion.normalized_title == "api-service error rate 18%"

    def test_high_severity_for_error_rate(self) -> None:
        _, ingestion = _ingested("ALERT: api-service error rate 18% — p99 latency 4200ms")
        router = run_router(ingestion)
        assert router.severity is Severity.HIGH
        assert router.incident_type == "service_degradation"

    def test_critical_for_outage(self) -> None:
        _, ingestion = _ingested("P0 outage: checkout fully down")
        assert run_router(ingestion).severity is Severity.CRITICAL


class TestInvestigationThroughPlanner:
    def test_proposals_cite_real_tool_outputs(self) -> None:
        _, ingestion = _ingested("ALERT: api-service error rate 18% — p99 latency 4200ms")
        router = run_router(ingestion)
        investigation = run_investigation(ingestion, router)
        knowledge = run_knowledge_retrieval(ingestion, router)
        diagnosis = run_evidence_diagnosis(investigation, knowledge)
        planner = run_action_planner(ingestion, investigation, knowledge, diagnosis)

        known_ids = {
            t.tool_output_id
            for t in [*investigation.tool_outputs, *knowledge.tool_outputs]
        }
        assert planner.proposals
        assert planner.proposals[0].tool_name == "restart_service"
        for proposal in planner.proposals:
            assert proposal.evidence_refs
            assert set(proposal.evidence_refs) <= known_ids

    def test_diagnosis_confidence_in_range(self) -> None:
        _, ingestion = _ingested("ALERT: api-service error rate 18%")
        router = run_router(ingestion)
        diagnosis = run_evidence_diagnosis(
            run_investigation(ingestion, router),
            run_knowledge_retrieval(ingestion, router),
        )
        assert 0.7 <= diagnosis.confidence_score <= 1.0
        assert diagnosis.evidence
