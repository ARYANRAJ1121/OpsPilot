"""
Log / alert webhook adapter — normalises log-forwarder or alertmanager-style
payloads into IncidentEvent objects.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from opspilot.graph import run_incident
from opspilot.schemas import IncidentEvent, IncidentSource

log = structlog.get_logger(__name__)

_SEVERITY_RE = re.compile(r"\b(critical|fatal|error|sev0|sev1|p0|alert)\b", re.I)
_INCIDENT_KEYWORDS = re.compile(
    r"(outage|error.rate|latency|timeout|crash|oom|unavailable|5\d\d)",
    re.IGNORECASE,
)


def _flatten_text(raw: dict[str, Any]) -> str:
    if "alerts" in raw and isinstance(raw["alerts"], list):
        chunks: list[str] = []
        for alert in raw["alerts"][:10]:
            if not isinstance(alert, dict):
                continue
            labels = alert.get("labels") or {}
            ann = alert.get("annotations") or {}
            chunks.append(
                " ".join(
                    str(x)
                    for x in (
                        labels.get("alertname"),
                        labels.get("severity"),
                        labels.get("service"),
                        ann.get("summary"),
                        ann.get("description"),
                        alert.get("status"),
                    )
                    if x
                )
            )
        return " | ".join(chunks)
    return " ".join(
        str(raw.get(k) or "")
        for k in ("message", "msg", "text", "log", "service", "level", "severity")
    )


def _is_incident(raw: dict[str, Any]) -> bool:
    text = _flatten_text(raw)
    level = str(raw.get("level") or raw.get("severity") or "").lower()
    if level in {"critical", "fatal", "error", "alert"}:
        return True
    if _SEVERITY_RE.search(text) or _INCIDENT_KEYWORDS.search(text):
        return True
    # Alertmanager firing
    if raw.get("status") == "firing":
        return True
    alerts = raw.get("alerts")
    if isinstance(alerts, list) and any(
        isinstance(a, dict) and a.get("status") == "firing" for a in alerts
    ):
        return True
    return False


def handle_logs_webhook(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Triage a logs/alert webhook payload; return graph state or None."""
    if not isinstance(raw, dict):
        return None
    if not _is_incident(raw):
        log.info("logs.skipped_non_incident")
        return None

    text = _flatten_text(raw) or str(raw)[:400]
    content = f"[Logs] {text[:800]}"
    event = IncidentEvent(
        source=IncidentSource.LOGS,
        content=content,
        raw_metadata={"logs": raw},
    )
    log.info("logs.triaging", event_id=str(event.event_id))
    return run_incident(event, persist=True)
