"""
Action Planner Agent — propose remediations that cite ToolOutputs only.

Tool selection is deterministic (no LLM decides what runs). The LLM, when
configured, only rewrites each proposal's human-readable rationale.
"""

from __future__ import annotations

from uuid import UUID

from opspilot.agents._parsing import infer_service_name
from opspilot.llm import enrich
from opspilot.schemas import (
    ActionPlannerOutput,
    ActionProposal,
    EvidenceAndDiagnosisOutput,
    IngestionOutput,
    InvestigationOutput,
    KnowledgeRetrievalOutput,
    ToolOutput,
)

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
    tools = {t.tool_name: t for t in [*investigation.tool_outputs, *knowledge.tool_outputs]}
    service = infer_service_name(f"{ingestion.normalized_title} {ingestion.normalized_body}")

    pods = tools.get("list_pods")
    metrics = tools.get("read_metrics")
    runbook = tools.get("search_runbook")

    crash = 0
    if pods:
        crash = sum(1 for p in pods.result.get("pods", []) if p.get("status") == "CrashLoopBackOff")
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

    return ActionPlannerOutput(event_id=diagnosis.event_id, proposals=proposals)


def _refs(*tools: ToolOutput | None) -> list[UUID]:
    return [t.tool_output_id for t in tools if t is not None]
