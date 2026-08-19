"""
opspilot/graph.py

LangGraph wiring for the OpsPilot pipeline.

Agents produce typed schema objects. Provenance Gate, Policy Engine,
and Confidence Router remain pure Python with zero LLM calls.
Customer communication forks from the router and never re-joins.
"""

from __future__ import annotations

import time
from operator import add
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from opspilot.agents.action_planner import run_action_planner
from opspilot.agents.customer_communication import run_customer_communication
from opspilot.agents.evidence_diagnosis import run_evidence_diagnosis
from opspilot.agents.execution import run_execution
from opspilot.agents.ingestion import run_ingestion
from opspilot.agents.investigation import run_investigation
from opspilot.agents.knowledge_retrieval import run_knowledge_retrieval
from opspilot.agents.router import run_router
from opspilot.confidence_router import run_confidence_router
from opspilot.policy_engine import run_policy_engine
from opspilot.provenance_gate import check_provenance
from opspilot.schemas import (
    ActionPlannerOutput,
    ConfidenceRiskRouterOutput,
    CustomerCommunicationOutput,
    EscalationRecord,
    EvidenceAndDiagnosisOutput,
    ExecutionResult,
    HumanApprovalRequest,
    IncidentEvent,
    IngestionOutput,
    InvestigationOutput,
    KnowledgeRetrievalOutput,
    PolicyEngineResult,
    ProvenanceCheckResult,
    RouterOutput,
    RoutingDecision,
    TraceEntry,
)


class GraphState(TypedDict, total=False):
    event: IncidentEvent
    ingestion: IngestionOutput
    router: RouterOutput
    investigation: InvestigationOutput
    knowledge: KnowledgeRetrievalOutput
    customer_comm: CustomerCommunicationOutput
    diagnosis: EvidenceAndDiagnosisOutput
    planner: ActionPlannerOutput
    provenance: ProvenanceCheckResult
    policy: PolicyEngineResult
    routing: ConfidenceRiskRouterOutput
    execution: ExecutionResult
    human_approval_request: HumanApprovalRequest
    escalation: EscalationRecord
    traces: Annotated[list[TraceEntry], add]


def _trace(
    event_id: UUID,
    agent_name: str,
    input_snapshot: dict[str, Any],
    output_snapshot: dict[str, Any],
    t_start: float,
) -> list[TraceEntry]:
    return [
        TraceEntry(
            event_id=event_id,
            agent_name=agent_name,
            input_snapshot=input_snapshot,
            output_snapshot=output_snapshot,
            latency_ms=(time.monotonic() - t_start) * 1000,
        )
    ]


def _ingestion_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event = state["event"]
    ingestion = run_ingestion(event)
    return {
        "ingestion": ingestion,
        "traces": _trace(
            event.event_id,
            "ingestion",
            event.model_dump(mode="json"),
            ingestion.model_dump(mode="json"),
            t0,
        ),
    }


def _router_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    ingestion = state["ingestion"]
    router = run_router(ingestion)
    return {
        "router": router,
        "traces": _trace(
            ingestion.event_id,
            "router",
            ingestion.model_dump(mode="json"),
            router.model_dump(mode="json"),
            t0,
        ),
    }


def _investigation_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    ingestion, router = state["ingestion"], state["router"]
    investigation = run_investigation(ingestion, router)
    return {
        "investigation": investigation,
        "traces": _trace(
            ingestion.event_id,
            "investigation",
            {"ingestion": ingestion.model_dump(mode="json")},
            investigation.model_dump(mode="json"),
            t0,
        ),
    }


def _knowledge_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    ingestion, router = state["ingestion"], state["router"]
    knowledge = run_knowledge_retrieval(ingestion, router)
    return {
        "knowledge": knowledge,
        "traces": _trace(
            ingestion.event_id,
            "knowledge_retrieval",
            {"router": router.model_dump(mode="json")},
            knowledge.model_dump(mode="json"),
            t0,
        ),
    }


def _customer_comm_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    ingestion, router = state["ingestion"], state["router"]
    comm = run_customer_communication(ingestion, router)
    return {
        "customer_comm": comm,
        "traces": _trace(
            ingestion.event_id,
            "customer_communication",
            {"severity": router.severity.value},
            comm.model_dump(mode="json"),
            t0,
        ),
    }


def _diagnosis_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    investigation, knowledge = state["investigation"], state["knowledge"]
    diagnosis = run_evidence_diagnosis(investigation, knowledge)
    return {
        "diagnosis": diagnosis,
        "traces": _trace(
            investigation.event_id,
            "evidence_diagnosis",
            {"findings": investigation.findings_summary},
            diagnosis.model_dump(mode="json"),
            t0,
        ),
    }


def _planner_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    planner = run_action_planner(
        state["ingestion"],
        state["investigation"],
        state["knowledge"],
        state["diagnosis"],
    )
    return {
        "planner": planner,
        "traces": _trace(
            planner.event_id,
            "action_planner",
            {"proposal_count": len(planner.proposals)},
            planner.model_dump(mode="json"),
            t0,
        ),
    }


def _provenance_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    tool_outputs = [
        *state["investigation"].tool_outputs,
        *state["knowledge"].tool_outputs,
    ]
    provenance = check_provenance(state["planner"], tool_outputs)
    return {
        "provenance": provenance,
        "traces": _trace(
            state["planner"].event_id,
            "provenance_gate",
            {"proposal_count": len(state["planner"].proposals)},
            provenance.model_dump(mode="json"),
            t0,
        ),
    }


def _policy_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    policy = run_policy_engine(state["provenance"], event_id)
    return {
        "policy": policy,
        "traces": _trace(
            event_id,
            "policy_engine",
            {"approved": len(state["provenance"].approved_proposals)},
            policy.model_dump(mode="json"),
            t0,
        ),
    }


def _confidence_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    routing = run_confidence_router(
        event_id=event_id,
        confidence_score=state["diagnosis"].confidence_score,
        provenance_result=state["provenance"],
        policy_result=state["policy"],
    )
    return {
        "routing": routing,
        "traces": _trace(
            event_id,
            "confidence_router",
            {"confidence": state["diagnosis"].confidence_score},
            routing.model_dump(mode="json"),
            t0,
        ),
    }


def _route_after_confidence(state: GraphState) -> str:
    decision = state["routing"].routing_decision
    if decision is RoutingDecision.AUTO_EXECUTE:
        return "execution"
    if decision is RoutingDecision.REQUIRE_HUMAN_APPROVAL:
        return "human_approval"
    return "escalate"


def _execution_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    execution = run_execution(event_id, state["routing"].approved_proposals)
    return {
        "execution": execution,
        "traces": _trace(
            event_id,
            "execution",
            {"tools": [p.tool_name for p in state["routing"].approved_proposals]},
            execution.model_dump(mode="json"),
            t0,
        ),
    }


def _human_approval_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    request = HumanApprovalRequest(
        event_id=event_id,
        proposals=state["routing"].approved_proposals,
        policy_result=state["policy"],
        context_summary=state["diagnosis"].diagnosis,
    )
    return {
        "human_approval_request": request,
        "traces": _trace(
            event_id,
            "human_approval",
            {"decision": state["routing"].routing_decision.value},
            request.model_dump(mode="json"),
            t0,
        ),
    }


def _escalate_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    reason = "provenance_gate_failed"
    if state["routing"].routing_decision is RoutingDecision.ESCALATE:
        if state["provenance"].passed:
            reason = "confidence_or_policy_escalation"
    record = EscalationRecord(event_id=event_id, reason=reason)
    return {
        "escalation": record,
        "traces": _trace(
            event_id,
            "escalate",
            {"reason": reason},
            record.model_dump(mode="json"),
            t0,
        ),
    }


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("ingestion", _ingestion_node)
    graph.add_node("router", _router_node)
    graph.add_node("investigation", _investigation_node)
    graph.add_node("knowledge_retrieval", _knowledge_node)
    graph.add_node("customer_communication", _customer_comm_node)
    graph.add_node("evidence_diagnosis", _diagnosis_node)
    graph.add_node("action_planner", _planner_node)
    graph.add_node("provenance_gate", _provenance_node)
    graph.add_node("policy_engine", _policy_node)
    graph.add_node("confidence_router", _confidence_node)
    graph.add_node("execution", _execution_node)
    graph.add_node("human_approval", _human_approval_node)
    graph.add_node("escalate", _escalate_node)

    graph.add_edge(START, "ingestion")
    graph.add_edge("ingestion", "router")
    graph.add_edge("router", "investigation")
    graph.add_edge("router", "knowledge_retrieval")
    graph.add_edge("router", "customer_communication")
    graph.add_edge("customer_communication", END)
    graph.add_edge("investigation", "evidence_diagnosis")
    graph.add_edge("knowledge_retrieval", "evidence_diagnosis")
    graph.add_edge("evidence_diagnosis", "action_planner")
    graph.add_edge("action_planner", "provenance_gate")
    graph.add_edge("provenance_gate", "policy_engine")
    graph.add_edge("policy_engine", "confidence_router")
    graph.add_conditional_edges(
        "confidence_router",
        _route_after_confidence,
        {
            "execution": "execution",
            "human_approval": "human_approval",
            "escalate": "escalate",
        },
    )
    graph.add_edge("execution", END)
    graph.add_edge("human_approval", END)
    graph.add_edge("escalate", END)
    return graph.compile()


def run_incident(event: IncidentEvent) -> GraphState:
    """Run a single incident through the compiled graph."""
    app = build_graph()
    return app.invoke({"event": event, "traces": []})
