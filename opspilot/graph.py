"""
opspilot/graph.py

LangGraph wiring for the OpsPilot pipeline.

Agents produce typed schema objects. The Provenance Gate, Policy Engine,
and Confidence Router remain pure Python with zero LLM calls. Customer
communication forks from the router and never re-joins.

Human-in-the-loop: when the Confidence Router requires human approval, the
`human_approval` node calls LangGraph's `interrupt()`, pausing the run. The
caller resumes with a HumanApprovalResponse via `resume_incident`, and the
graph then routes to execution (approved) or escalation (rejected).
"""

from __future__ import annotations

import time
from operator import add
from typing import Annotated, Any, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from opspilot.agents.action_planner import run_action_planner
from opspilot.agents.customer_communication import run_customer_communication
from opspilot.agents.evidence_diagnosis import run_evidence_diagnosis
from opspilot.agents.execution import run_execution
from opspilot.agents.ingestion import run_ingestion
from opspilot.agents.investigation import run_investigation
from opspilot.agents.knowledge_retrieval import run_knowledge_retrieval
from opspilot.agents.router import run_router
from opspilot.approval_queue import PendingApproval, remove_by_thread, upsert_pending
from opspilot.checkpoint import get_checkpointer, reset_checkpointer
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
    HumanApprovalDecision,
    HumanApprovalRequest,
    HumanApprovalResponse,
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
from opspilot.trace_store import write_traces


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
    human_approval_response: HumanApprovalResponse
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
    """Pause the graph and wait for a human decision via interrupt()."""
    t0 = time.monotonic()
    event_id = state["event"].event_id
    request = HumanApprovalRequest(
        event_id=event_id,
        proposals=state["routing"].approved_proposals,
        policy_result=state["policy"],
        context_summary=state["diagnosis"].diagnosis,
    )

    # Execution halts here until resume_incident() supplies a payload.
    payload = interrupt(
        {
            "kind": "human_approval",
            "request": request.model_dump(mode="json"),
            "proposals": [p.model_dump(mode="json") for p in request.proposals],
            "context_summary": request.context_summary,
        }
    )

    response = _coerce_response(payload, request_id=request.request_id, event_id=event_id)
    return {
        "human_approval_request": request,
        "human_approval_response": response,
        "traces": _trace(
            event_id,
            "human_approval",
            {"proposals": [p.tool_name for p in request.proposals]},
            response.model_dump(mode="json"),
            t0,
        ),
    }


def _coerce_response(
    payload: Any,
    *,
    request_id: UUID,
    event_id: UUID,
) -> HumanApprovalResponse:
    if isinstance(payload, HumanApprovalResponse):
        return payload
    if isinstance(payload, dict):
        data = {"request_id": request_id, **payload}
        return HumanApprovalResponse(**data)
    # Any unexpected payload is treated as a rejection (fail-safe).
    return HumanApprovalResponse(
        request_id=request_id,
        decision=HumanApprovalDecision.REJECTED,
        reviewer_id="unknown",
        notes="Unrecognised approval payload — defaulting to rejection.",
    )


def _route_after_human(state: GraphState) -> str:
    response = state.get("human_approval_response")
    if response and response.decision is HumanApprovalDecision.APPROVED:
        return "execution"
    return "escalate"


def _escalate_node(state: GraphState) -> dict[str, Any]:
    t0 = time.monotonic()
    event_id = state["event"].event_id
    response = state.get("human_approval_response")

    if response and response.decision is HumanApprovalDecision.REJECTED:
        reason = "human_rejected"
    elif not state["provenance"].passed:
        reason = "provenance_gate_failed"
    else:
        reason = "confidence_or_policy_escalation"

    record = EscalationRecord(event_id=event_id, reason=reason, human_response=response)
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


def build_graph(*, checkpointer: Any | None = None):
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
    graph.add_conditional_edges(
        "human_approval",
        _route_after_human,
        {
            "execution": "execution",
            "escalate": "escalate",
        },
    )
    graph.add_edge("execution", END)
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer or get_checkpointer())


# A single compiled app is reused so its checkpointer persists state across
# the invoke/resume boundary (SQLite by default — survives process restart).
_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def reset_graph_app() -> None:
    """Drop compiled graph + checkpointer cache (tests / settings changes)."""
    global _APP
    _APP = None
    reset_checkpointer()


def _thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _register_pending_approval(state: dict[str, Any]) -> None:
    interrupt_list = state.get("__interrupt__") or []
    if not interrupt_list:
        return
    first = interrupt_list[0]
    payload = first.value if hasattr(first, "value") else first
    if not isinstance(payload, dict):
        return
    request = payload.get("request") or {}
    event = state.get("event")
    event_id = str(request.get("event_id") or (event.event_id if event else ""))
    request_id = str(request.get("request_id") or event_id)
    upsert_pending(
        PendingApproval(
            thread_id=state["thread_id"],
            event_id=event_id,
            request_id=request_id,
            context_summary=str(payload.get("context_summary") or ""),
            proposals=list(payload.get("proposals") or []),
            source=event.source.value if event is not None else None,
        )
    )


def run_incident(
    event: IncidentEvent,
    *,
    thread_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Run one incident.

    Returns the final state dict. When the run pauses for human approval the
    result contains an "__interrupt__" entry and a "thread_id" so the caller
    can resume via resume_incident(). Completed runs persist their traces.
    """
    thread_id = thread_id or str(uuid4())
    app = _app()
    state = app.invoke({"event": event, "traces": []}, config=_thread_config(thread_id))
    state["thread_id"] = thread_id

    if "__interrupt__" in state:
        _register_pending_approval(state)
    elif persist:
        _persist(state)
    return state


def resume_incident(
    thread_id: str,
    response: HumanApprovalResponse | dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Resume a paused incident with a human decision and finish the run."""
    app = _app()
    payload = (
        response.model_dump(mode="json")
        if isinstance(response, HumanApprovalResponse)
        else response
    )
    state = app.invoke(Command(resume=payload), config=_thread_config(thread_id))
    state["thread_id"] = thread_id
    remove_by_thread(thread_id)

    if "__interrupt__" not in state and persist:
        _persist(state)
    return state


def _persist(state: dict[str, Any]) -> None:
    event = state.get("event")
    traces = state.get("traces") or []
    if event is not None and traces:
        path = write_traces(event.event_id, traces)
        state["trace_path"] = str(path)
