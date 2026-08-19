"""Evidence & Diagnosis Agent — cite only ToolOutputs. No LLM."""

from __future__ import annotations

from opspilot.schemas import (
    Evidence,
    EvidenceAndDiagnosisOutput,
    InvestigationOutput,
    KnowledgeRetrievalOutput,
)


def run_evidence_diagnosis(
    investigation: InvestigationOutput,
    knowledge: KnowledgeRetrievalOutput,
) -> EvidenceAndDiagnosisOutput:
    tool_outputs = [*investigation.tool_outputs, *knowledge.tool_outputs]
    evidence = [Evidence(tool_output_id=t.tool_output_id, summary=_summarize_tool(t)) for t in tool_outputs]

    metrics = _first_result(investigation.tool_outputs, "read_metrics")
    pods = _first_result(investigation.tool_outputs, "list_pods")
    crash = 0
    if pods:
        crash = sum(1 for p in pods["pods"] if p["status"] == "CrashLoopBackOff")

    error_rate = float(metrics["error_rate_pct"]) if metrics else 0.0
    diagnosis = (
        f"{investigation.findings_summary}. "
        f"{knowledge.articles_summary}. "
        f"Primary cause hypothesis: pod crashloop driving elevated error rate "
        f"({error_rate}%, crashloop={crash})."
    )

    confidence = 0.35
    if crash:
        confidence += 0.25
    if error_rate >= 10:
        confidence += 0.25
    if knowledge.tool_outputs:
        confidence += 0.15
    confidence = min(confidence, 0.95)

    return EvidenceAndDiagnosisOutput(
        event_id=investigation.event_id,
        evidence=evidence,
        diagnosis=diagnosis,
        confidence_score=round(confidence, 2),
    )


def _first_result(tool_outputs: list, name: str) -> dict | None:
    for t in tool_outputs:
        if t.tool_name == name:
            return t.result
    return None


def _summarize_tool(tool) -> str:
    result = tool.result
    if tool.tool_name == "read_metrics":
        return (
            f"error_rate={result.get('error_rate_pct')}% "
            f"p99={result.get('p99_latency_ms')}ms"
        )
    if tool.tool_name == "list_pods":
        crash = sum(1 for p in result.get("pods", []) if p.get("status") == "CrashLoopBackOff")
        return f"{crash} pod(s) in CrashLoopBackOff"
    if tool.tool_name == "fetch_logs":
        return f"{result.get('total_errors_last_5m', 0)} errors in last 5m"
    if tool.tool_name == "search_runbook":
        titles = [a.get("title", "") for a in result.get("results", [])]
        return f"runbooks: {', '.join(titles) or 'none'}"
    return f"{tool.tool_name} completed"
