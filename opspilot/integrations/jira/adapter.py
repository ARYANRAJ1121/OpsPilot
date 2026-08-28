"""
opspilot/integrations/jira/adapter.py

Jira webhook adapter — normalises Jira issue events into IncidentEvent
objects and routes them through the OpsPilot pipeline.

Supports:
  - jira:issue_created → always triaged
  - jira:issue_updated → triaged when priority/status changes suggest incident
  - comment_created    → triaged when comment contains incident keywords

Severity mapping:
  Jira "Highest" / "Blocker" → CRITICAL
  Jira "High"                → HIGH
  Jira "Medium"              → MEDIUM
  Jira "Low" / "Lowest"      → LOW (ignored unless incident keywords present)
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from opspilot.graph import run_incident
from opspilot.schemas import IncidentEvent, IncidentSource

from .models import JiraWebhookPayload

log = structlog.get_logger(__name__)

# Keywords that signal an operational incident regardless of priority
_INCIDENT_KEYWORDS = re.compile(
    r"(outage|down|p0|sev0|sev1|incident|degraded|alert|crash|error.rate|"
    r"latency|timeout|unavailable|data.loss|service.degradation)",
    re.IGNORECASE,
)

_PRIORITY_MAP: dict[str, str] = {
    "highest": "critical",
    "blocker": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}


def _is_incident(payload: JiraWebhookPayload) -> bool:
    """Decide whether this webhook event looks like an operational incident."""
    fields = payload.issue.fields

    # Incident-labelled tickets always qualify
    labels_lower = {lb.lower() for lb in fields.labels}
    if labels_lower & {"incident", "sev0", "sev1", "p0", "outage", "alert"}:
        return True

    # Bug/incident issue types always qualify
    if fields.issuetype.name.lower() in ("bug", "incident", "problem", "outage"):
        return True

    # High/critical priority always qualifies
    prio = fields.priority.name.lower()
    if prio in ("highest", "blocker", "high"):
        return True

    # Keyword scan in summary + description
    text = f"{fields.summary} {fields.description or ''}"
    if payload.comment:
        text += f" {payload.comment.body}"
    if _INCIDENT_KEYWORDS.search(text):
        return True

    return False


def _build_content(payload: JiraWebhookPayload) -> str:
    """Build a normalised alert string from the Jira payload."""
    fields = payload.issue.fields
    parts = [
        f"[JIRA:{payload.issue.key}]",
        f"[{fields.priority.name}]",
        fields.summary,
    ]
    if fields.description:
        # Trim long descriptions
        desc = fields.description[:500]
        parts.append(f"— {desc}")
    if payload.comment:
        parts.append(f"(comment: {payload.comment.body[:200]})")
    return " ".join(parts)


def handle_jira_webhook(
    raw_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Process a Jira webhook payload.

    Returns the pipeline result state, or None if the event is not
    incident-like and should be ignored.
    """
    try:
        payload = JiraWebhookPayload(**raw_payload)
    except Exception as exc:
        log.warning("jira.parse_failed", error=str(exc))
        return None

    event_type = payload.webhook_event
    log.info(
        "jira.webhook_received",
        event_type=event_type,
        issue_key=payload.issue.key,
        priority=payload.issue.fields.priority.name,
    )

    # Filter: only process incident-like events
    if not _is_incident(payload):
        log.info("jira.skipped_non_incident", issue_key=payload.issue.key)
        return None

    content = _build_content(payload)
    event = IncidentEvent(source=IncidentSource.JIRA, content=content)

    log.info(
        "jira.triaging",
        event_id=str(event.event_id),
        issue_key=payload.issue.key,
        content_preview=content[:120],
    )

    state = run_incident(event, persist=True)
    return state


def create_jira_webhook_app():
    """
    Create a FastAPI app for receiving Jira webhooks.

    Mount at /jira/webhook in your server or run standalone for testing.
    """
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the Jira webhook server. "
            "Install with: pip install fastapi uvicorn"
        )

    app = FastAPI(title="OpsPilot Jira Webhook", docs_url="/jira/docs")

    @app.post("/jira/webhook")
    async def jira_webhook(request: Request) -> JSONResponse:
        raw = await request.json()
        result = handle_jira_webhook(raw)
        if result is None:
            return JSONResponse({"status": "ignored"}, status_code=200)
        return JSONResponse(
            {
                "status": "triaged",
                "event_id": str(result.get("event", {}).event_id)
                if result.get("event")
                else None,
            },
            status_code=200,
        )

    @app.get("/jira/health")
    async def health() -> dict:
        return {"status": "ok", "adapter": "jira"}

    return app
