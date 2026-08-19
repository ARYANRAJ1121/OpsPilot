"""Investigation Agent — collect live (simulated) evidence via tools. No LLM."""

from __future__ import annotations

from opspilot.agents._parsing import infer_service_name
from opspilot.schemas import IngestionOutput, InvestigationOutput, RouterOutput
from opspilot.tools.simulated import execute_tool


def run_investigation(
    ingestion: IngestionOutput,
    router: RouterOutput,
) -> InvestigationOutput:
    service = infer_service_name(f"{ingestion.normalized_title} {ingestion.normalized_body}")

    tool_outputs = [
        execute_tool("fetch_logs", {"service": service}),
        execute_tool("read_metrics", {"service": service}),
        execute_tool("list_pods", {"namespace": "production"}),
        execute_tool("describe_service", {"service": service}),
        execute_tool("query_apm", {"service": service}),
    ]

    findings = _summarize(service, tool_outputs)
    return InvestigationOutput(
        event_id=ingestion.event_id,
        tool_outputs=tool_outputs,
        findings_summary=f"[{router.incident_type}] {findings}",
    )


def _summarize(service: str, tool_outputs: list) -> str:
    metrics = next(t for t in tool_outputs if t.tool_name == "read_metrics").result
    pods = next(t for t in tool_outputs if t.tool_name == "list_pods").result
    crash = sum(1 for p in pods["pods"] if p["status"] == "CrashLoopBackOff")
    return (
        f"{service}: error_rate={metrics['error_rate_pct']}% "
        f"p99={metrics['p99_latency_ms']}ms crashloop_pods={crash}"
    )
