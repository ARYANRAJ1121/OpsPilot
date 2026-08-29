"""
opspilot/integrations/github/adapter.py

GitHub Issues webhook adapter — normalises issue events into IncidentEvent
objects and routes them through the OpsPilot pipeline.

Supports:
  - issues (action: opened, edited, labeled) → triaged when incident-like
  - issue_comment (action: created) → triaged when comment has incident keywords

Incident detection uses label names and keyword scanning — same strategy
as the Jira adapter.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from opspilot.graph import run_incident
from opspilot.schemas import IncidentEvent, IncidentSource

from .models import GitHubWebhookPayload

log = structlog.get_logger(__name__)

# Keywords that signal an operational incident
_INCIDENT_KEYWORDS = re.compile(
    r"(outage|down|p0|sev0|sev1|incident|degraded|alert|crash|error.rate|"
    r"latency|timeout|unavailable|data.loss|service.degradation|"
    r"production.issue|critical.bug|hotfix)",
    re.IGNORECASE,
)

# Labels that always indicate an incident
_INCIDENT_LABELS = {
    "incident",
    "outage",
    "p0",
    "sev0",
    "sev1",
    "production",
    "critical",
    "urgent",
    "bug-critical",
}


def _is_incident(payload: GitHubWebhookPayload) -> bool:
    """Decide whether this webhook event looks like an operational incident."""
    # Incident labels
    issue_labels = {lb.name.lower() for lb in payload.issue.labels}
    if issue_labels & _INCIDENT_LABELS:
        return True

    # Keyword scan in title + body + comment
    text = f"{payload.issue.title} {payload.issue.body or ''}"
    if payload.comment:
        text += f" {payload.comment.body}"
    if _INCIDENT_KEYWORDS.search(text):
        return True

    return False


def _build_content(payload: GitHubWebhookPayload) -> str:
    """Build a normalised alert string from the GitHub payload."""
    repo = payload.repository.full_name or payload.repository.name
    parts = [
        f"[GitHub:{repo}#{payload.issue.number}]",
        payload.issue.title,
    ]
    if payload.issue.body:
        body = payload.issue.body[:500]
        parts.append(f"— {body}")
    if payload.comment:
        parts.append(f"(comment: {payload.comment.body[:200]})")

    labels = [lb.name for lb in payload.issue.labels]
    if labels:
        parts.append(f"[labels: {', '.join(labels)}]")

    return " ".join(parts)


def handle_github_webhook(
    raw_payload: dict[str, Any],
    event_type: str = "issues",
) -> dict[str, Any] | None:
    """
    Process a GitHub webhook payload.

    Args:
        raw_payload: the JSON body of the webhook.
        event_type: the X-GitHub-Event header value (e.g., "issues",
            "issue_comment").

    Returns the pipeline result state, or None if the event is not
    incident-like and should be ignored.
    """
    # Only process relevant event types
    if event_type not in ("issues", "issue_comment"):
        log.info("github.skipped_event_type", event_type=event_type)
        return None

    try:
        payload = GitHubWebhookPayload(**raw_payload)
    except Exception as exc:
        log.warning("github.parse_failed", error=str(exc))
        return None

    # Only process relevant actions
    relevant_actions = {"opened", "edited", "labeled", "created"}
    if payload.action not in relevant_actions:
        log.info(
            "github.skipped_action",
            action=payload.action,
            issue=payload.issue.number,
        )
        return None

    log.info(
        "github.webhook_received",
        event_type=event_type,
        action=payload.action,
        issue=payload.issue.number,
        repo=payload.repository.full_name,
    )

    if not _is_incident(payload):
        log.info("github.skipped_non_incident", issue=payload.issue.number)
        return None

    content = _build_content(payload)
    event = IncidentEvent(source=IncidentSource.GITHUB_ISSUES, content=content)

    log.info(
        "github.triaging",
        event_id=str(event.event_id),
        issue=payload.issue.number,
        content_preview=content[:120],
    )

    state = run_incident(event, persist=True)
    return state


def create_github_webhook_app():
    """
    Create a FastAPI app for receiving GitHub webhooks.

    Prefer the unified server: ``uvicorn opspilot.server:app``.
    """
    try:
        import json

        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the GitHub webhook server. "
            "Install with: pip install fastapi uvicorn"
        )

    from opspilot.config import get_settings
    from opspilot.integrations.signing import verify_github_signature

    app = FastAPI(title="OpsPilot GitHub Webhook", docs_url="/github/docs")

    @app.post("/github/webhook")
    async def github_webhook(request: Request) -> JSONResponse:
        s = get_settings()
        body = await request.body()
        ok = verify_github_signature(
            body,
            request.headers.get("X-Hub-Signature-256"),
            s.github_webhook_secret,
            require=s.webhook_require_signatures,
        )
        if not ok:
            return JSONResponse({"status": "unauthorized"}, status_code=401)
        event_type = request.headers.get("X-GitHub-Event", "issues")
        try:
            raw = json.loads(body.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)
        result = handle_github_webhook(raw, event_type=event_type)
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

    @app.get("/github/health")
    async def health() -> dict:
        return {"status": "ok", "adapter": "github"}

    return app
