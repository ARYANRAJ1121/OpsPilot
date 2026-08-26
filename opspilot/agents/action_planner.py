"""
Action Planner Agent — propose remediations that cite ToolOutputs only.

When LLM planning is active, Groq proposes actions based on the diagnosis
and evidence. Every proposal must cite tool_output_ids — the Provenance Gate
still validates these downstream. When the LLM is unavailable, the original
if/elif heuristic runs unchanged.

The enrich() call for rationale prose is applied in both paths.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from opspilot.agents._parsing import infer_service_name
from opspilot.llm import enrich
from opspilot.llm_planner import plan_actions
from opspilot.schemas import (
    ActionPlannerOutput,
    ActionProposal,
    EvidenceAndDiagnosisOutput,
    IngestionOutput,
    InvestigationOutput,
    KnowledgeRetrievalOutput,
    ToolOutput,
)

log = structlog.get_logger(__name__)

_RATIONALE_SYSTEM = (
    "You are an SRE. Rewrite the remediation rationale in one clear sentence. "
    "Keep it factual and tied to the evidence provided; do not change the action."
)


def _rationale(fallback: str, tool_name: str) -> str:
    return enrich(
        _RATIONALE_SYSTEM,
        f"Action: {tool_name}. Draft rationale: {fallback}",
        fallback=fallback,
    )


def run_action_planner(
    ingestion: IngestionOutput,
    investigation: InvestigationOutput,
    knowledge: KnowledgeRetrievalOutput,
    diagnosis: EvidenceAndDiagnosisOutput,
) -> ActionPlannerOutput:
    all_tool_outputs = [*investigation.tool_outputs, *knowledge.tool_outputs]
    tools = {t.tool_name: t for t in all_tool_outputs}
    service = infer_service_name(
        f"{ingestion.normalized_title} {ingestion.normalized_body}"
    )

    # Build evidence summaries and IDs for the LLM planner
    evidence_summaries = [
        {"id": str(e.tool_output_id), "summary": e.summary}
        for e in diagnosis.evidence
    ]
    available_evidence_ids = [str(t.tool_output_id) for t in all_tool_outputs]

    # Try LLM-driven action planning
    llm_plans = plan_actions(
        diagnosis=diagnosis.diagnosis,
        confidence_score=diagnosis.confidence_score,
        evidence_summaries=evidence_summaries,
        available_evidence_ids=available_evidence_ids,
    )

    if llm_plans is not None:
        log.info(
            "action_planner.llm_path",
            plan_count=len(llm_plans),
            tools=[p.tool_name for p in llm_plans],
        )
        proposals = _build_llm_proposals(llm_plans, all_tool_outputs)
    else:
        log.info("action_planner.heuristic_path")
        proposals = _build_heuristic_proposals(tools, service)

    return ActionPlannerOutput(event_id=diagnosis.event_id, proposals=proposals)


def _build_llm_proposals(
    llm_plans: list,
    all_tool_outputs: list[ToolOutput],
) -> list[ActionProposal]:
    """Convert LLM ActionPlan objects into ActionProposal with enriched rationale."""
    valid_ids = {str(t.tool_output_id) for t in all_tool_outputs}
    proposals: list[ActionProposal] = []

    for plan in llm_plans:
        # Filter evidence refs to only include valid UUIDs from our tool outputs
        filtered_refs: list[UUID] = []
        for ref_str in plan.evidence_ref_ids:
            if ref_str in valid_ids:
                filtered_refs.append(UUID(ref_str))

        if not filtered_refs:
            log.debug(
                "action_planner.skip_plan_no_valid_refs",
                tool_name=plan.tool_name,
            )
            continue

        proposals.append(
            ActionProposal(
                tool_name=plan.tool_name,
                parameters=plan.parameters,
                evidence_refs=filtered_refs,
                rationale=_rationale(plan.rationale, plan.tool_name),
            )
        )

    return proposals


def _build_heuristic_proposals(
    tools: dict[str, ToolOutput],
    service: str,
) -> list[ActionProposal]:
    """Original heuristic logic — unchanged from before LLM planning."""
    pods = tools.get("list_pods")
    metrics = tools.get("read_metrics")
    runbook = tools.get("search_runbook")

    crash = 0
    if pods:
        crash = sum(
            1
            for p in pods.result.get("pods", [])
            if p.get("status") == "CrashLoopBackOff"
        )
    error_rate = float(metrics.result.get("error_rate_pct", 0)) if metrics else 0.0

    proposals: list[ActionProposal] = []

    if crash and pods and metrics:
        refs = _refs(pods, metrics, runbook)
        proposals.append(
            ActionProposal(
                tool_name="restart_service",
                parameters={"service": service, "target": "crashed-pods"},
                evidence_refs=refs,
                rationale=_rationale(
                    f"CrashLoopBackOff on {crash} pod(s) with error_rate={error_rate}%. "
                    "Restart is reversible and matches the recovery runbook.",
                    "restart_service",
                ),
            )
        )
    elif error_rate >= 10 and metrics:
        refs = _refs(metrics, runbook)
        proposals.append(
            ActionProposal(
                tool_name="throttle_traffic",
                parameters={"service": service, "rate_pct": 50},
                evidence_refs=refs,
                rationale=_rationale(
                    f"Elevated error_rate={error_rate}% without a clear crashloop signal.",
                    "throttle_traffic",
                ),
            )
        )

    return proposals


def _refs(*tools: ToolOutput | None) -> list[UUID]:
    return [t.tool_output_id for t in tools if t is not None]
