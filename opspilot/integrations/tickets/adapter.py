"""
Support-ticket webhook adapter — normalises generic ticket events into
IncidentEvent objects (Zendesk / Freshdesk / custom ticketing JSON).
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from opspilot.graph import run_incident
from opspilot.schemas import IncidentEvent, IncidentSource

log = structlog.get_logger(__name__)

_INCIDENT_KEYWORDS = re.compile(
    r"(outage|down|p0|sev0|sev1|incident|degraded|alert|crash|"
    r"latency|timeout|unavailable|production)",
    re.IGNORECASE,
)


def _ticket_text(raw: dict[str, Any]) -> str:
    parts = [
        str(raw.get("subject") or raw.get("title") or ""),
        str(raw.get("description") or raw.get("body") or raw.get("comment") or ""),
        " ".join(str(t) for t in (raw.get("tags") or raw.get("labels") or [])),
    ]
    return " ".join(parts)


def _is_incident(raw: dict[str, Any]) -> bool:
    priority = str(raw.get("priority") or raw.get("urgency") or "").lower()
    if priority in {"urgent", "high", "critical", "p0", "p1"}:
        return True
    tags = {str(t).lower() for t in (raw.get("tags") or raw.get("labels") or [])}
    if tags & {"incident", "outage", "sev0", "sev1", "p0"}:
        return True
    return bool(_INCIDENT_KEYWORDS.search(_ticket_text(raw)))


def handle_ticket_webhook(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Triage a support-ticket webhook payload; return graph state or None."""
    if not isinstance(raw, dict):
        return None
    if not _is_incident(raw):
        log.info("tickets.skipped_non_incident")
        return None

    ticket_id = raw.get("id") or raw.get("ticket_id") or "unknown"
    subject = raw.get("subject") or raw.get("title") or "support ticket"
    body = raw.get("description") or raw.get("body") or ""
    content = f"[Ticket:{ticket_id}] {subject}"
    if body:
        content += f" — {str(body)[:500]}"

    event = IncidentEvent(
        source=IncidentSource.SUPPORT_TICKET,
        content=content,
        raw_metadata={"ticket": raw},
    )
    log.info("tickets.triaging", event_id=str(event.event_id), ticket_id=ticket_id)
    return run_incident(event, persist=True)
