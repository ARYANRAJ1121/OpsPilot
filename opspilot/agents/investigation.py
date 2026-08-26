"""
Investigation Agent — collect live (simulated) evidence via tools.

When LLM planning is active, Groq selects which tools to run based on the
alert text and severity. Otherwise, a hardcoded set of 5 tools is used
(unchanged from the original heuristic).
"""

from __future__ import annotations

import structlog

from opspilot.agents._parsing import infer_service_name
from opspilot.llm_planner import plan_investigation
from opspilot.schemas import IngestionOutput, InvestigationOutput, RouterOutput
from opspilot.tools.simulated import execute_tool

log = structlog.get_logger(__name__)

# Default heuristic tools when LLM is unavailable
_HEURISTIC_TOOLS: list[tuple[str, dict]] = [
    ("fetch_logs", {}),
    ("read_metrics", {}),
    ("list_pods", {"namespace": "production"}),
    ("describe_service", {}),
    ("query_apm", {}),
]


def run_investigation(
    ingestion: IngestionOutput,
    router: RouterOutput,
) -> InvestigationOutput:
    service = infer_service_name(
        f"{ingestion.normalized_title} {ingestion.normalized_body}"
    )
    alert_text = f"{ingestion.normalized_title} {ingestion.normalized_body}"

    # Try LLM-driven tool selection
    llm_selections = plan_investigation(
        alert_text=alert_text,
        severity=router.severity.value,
        service_name=service,
    )

    if llm_selections is not None:
        log.info(
            "investigation.llm_path",
            tool_count=len(llm_selections),
            tools=[s.tool_name for s in llm_selections],
        )
        tool_outputs = []
        for sel in llm_selections:
            params = {**sel.parameters}
            # Inject service name into params if missing (most tools need it)
            if "service" not in params and "namespace" not in params:
                params["service"] = service
            tool_outputs.append(execute_tool(sel.tool_name, params))
    else:
        log.info("investigation.heuristic_path", tool_count=len(_HEURISTIC_TOOLS))
        tool_outputs = []
        for tool_name, extra_params in _HEURISTIC_TOOLS:
            params = {"service": service, **extra_params}
            tool_outputs.append(execute_tool(tool_name, params))

    findings = _summarize(service, tool_outputs)
    return InvestigationOutput(
        event_id=ingestion.event_id,
        tool_outputs=tool_outputs,
        findings_summary=f"[{router.incident_type}] {findings}",
    )


def _summarize(service: str, tool_outputs: list) -> str:
    """Build a compact findings summary from whatever tools ran."""
    parts = [service + ":"]
    for t in tool_outputs:
        if t.tool_name == "read_metrics":
            parts.append(
                f"error_rate={t.result.get('error_rate_pct', '?')}% "
                f"p99={t.result.get('p99_latency_ms', '?')}ms"
            )
        elif t.tool_name == "list_pods":
            crash = sum(
                1
                for p in t.result.get("pods", [])
                if p.get("status") == "CrashLoopBackOff"
            )
            parts.append(f"crashloop_pods={crash}")
        elif t.tool_name == "fetch_logs":
            parts.append(f"errors_5m={t.result.get('total_errors_last_5m', '?')}")
        elif t.tool_name == "query_apm":
            parts.append(f"error_traces={t.result.get('error_traces_pct', '?')}%")
        elif t.tool_name == "describe_service":
            parts.append(f"health={t.result.get('health', '?')}")
    return " ".join(parts)
