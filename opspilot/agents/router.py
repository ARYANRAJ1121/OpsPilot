"""Router & Severity Agent — triage from normalized alert text. No LLM."""

from __future__ import annotations

from opspilot.schemas import IngestionOutput, RouterOutput, Severity

_CRITICAL_MARKERS = ("outage", "down", "p0", "sev0", "unavailable", "data loss")
_HIGH_MARKERS = (
    "error rate",
    "latency",
    "timeout",
    "crashloop",
    "crash",
    "503",
    "degraded",
    "high cpu",
)
_CONFIG_MARKERS = ("config", "flag", "deploy", "rollback", "migration")


def run_router(ingestion: IngestionOutput) -> RouterOutput:
    blob = f"{ingestion.normalized_title} {ingestion.normalized_body}".lower()

    if any(m in blob for m in _CRITICAL_MARKERS):
        severity = Severity.CRITICAL
        incident_type = "outage"
    elif any(m in blob for m in _HIGH_MARKERS):
        severity = Severity.HIGH
        incident_type = "service_degradation"
    elif any(m in blob for m in _CONFIG_MARKERS):
        severity = Severity.MEDIUM
        incident_type = "config_change"
    else:
        severity = Severity.MEDIUM
        incident_type = "unknown"

    return RouterOutput(
        event_id=ingestion.event_id,
        severity=severity,
        incident_type=incident_type,
        routing_notes=f"Heuristic triage from source={ingestion.source.value}",
    )
