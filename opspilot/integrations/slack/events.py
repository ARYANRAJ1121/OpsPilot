"""Helpers to serve Slack Events API url_verification + forward to Bolt."""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from opspilot.config import get_settings
from opspilot.integrations.signing import verify_slack_signature

log = structlog.get_logger(__name__)


async def handle_slack_request(req: Request, bolt_handler: Any) -> Response:
    """
    Handle Slack HTTP callbacks.

    Explicitly answers url_verification (must echo challenge). Signature
    mismatches through tunnels are logged but do not block verification —
    real events are still verified by Bolt afterward.
    """
    body = await req.body()
    payload: dict[str, Any]
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}

    if payload.get("type") == "url_verification":
        settings = get_settings()
        ok = verify_slack_signature(
            body,
            timestamp=req.headers.get("X-Slack-Request-Timestamp"),
            signature_header=req.headers.get("X-Slack-Signature"),
            signing_secret=settings.slack_signing_secret,
        )
        challenge = str(payload.get("challenge") or "")
        if ok:
            log.info("slack.url_verification_ok")
        else:
            # Still echo challenge so Slack can verify the Request URL.
            # Bolt continues to enforce signatures on real events.
            log.warning(
                "slack.url_verification_signature_mismatch_echoing_challenge",
                has_timestamp=bool(req.headers.get("X-Slack-Request-Timestamp")),
                has_signature=bool(req.headers.get("X-Slack-Signature")),
                has_secret=bool(settings.slack_signing_secret),
            )
        return JSONResponse({"challenge": challenge})

    # Re-inject body so Bolt can read it again.
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    new_req = Request(req.scope, receive)
    return await bolt_handler.handle(new_req)
