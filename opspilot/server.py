"""
Unified OpsPilot ingest server — one process, one tunnel.

Mounts:
  GET  /healthz
  GET  /approvals
  GET  /api/approvals
  POST /api/approvals/{thread_id}/decide
  POST /slack/events
  POST /slack/interactions
  POST /jira/webhook
  POST /github/webhook
  POST /tickets/webhook
  POST /logs/webhook

Run:
  uvicorn opspilot.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from opspilot.approvals_ui import router as approvals_router
from opspilot.config import get_settings
from opspilot.integrations.github.adapter import handle_github_webhook
from opspilot.integrations.jira.adapter import handle_jira_webhook
from opspilot.integrations.logs.adapter import handle_logs_webhook
from opspilot.integrations.signing import verify_github_signature, verify_jira_signature
from opspilot.integrations.slack.webhook import build_bolt_app, get_adapter
from opspilot.integrations.tickets.adapter import handle_ticket_webhook

log = structlog.get_logger(__name__)

_handler: AsyncSlackRequestHandler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _handler
    bolt = build_bolt_app(adapter=get_adapter())
    _handler = AsyncSlackRequestHandler(bolt)
    s = get_settings()
    log.info(
        "opspilot.server_ready",
        slack=s.slack_configured,
        jira_secret=bool(s.jira_webhook_secret),
        github_secret=bool(s.github_webhook_secret),
        require_signatures=s.webhook_require_signatures,
        checkpoint=s.checkpoint_backend,
        remediation=s.remediation_mode,
    )
    yield


def create_app() -> FastAPI:
    api = FastAPI(
        title="OpsPilot Ingest Server",
        version="1.0.0",
        description="Unified Slack + Jira + GitHub + tickets + logs + HITL UI",
        lifespan=lifespan,
    )
    api.include_router(approvals_router)

    @api.get("/healthz")
    async def healthz() -> dict[str, Any]:
        s = get_settings()
        return {
            "status": "ok",
            "version": "1.0.0",
            "integrations": {
                "slack": s.slack_configured,
                "jira": bool(s.jira_webhook_secret) or not s.webhook_require_signatures,
                "github": bool(s.github_webhook_secret) or not s.webhook_require_signatures,
                "tickets": bool(s.tickets_webhook_secret)
                or not s.webhook_require_signatures,
                "logs": bool(s.logs_webhook_secret) or not s.webhook_require_signatures,
                "groq": s.llm_active,
                "llm_planning": s.llm_planning_active,
                "checkpoint": s.checkpoint_backend,
                "remediation_mode": s.remediation_mode,
            },
        }

    @api.post("/slack/events")
    async def slack_events(req: Request) -> Response:
        assert _handler is not None
        return await _handler.handle(req)

    @api.post("/slack/interactions")
    async def slack_interactions(req: Request) -> Response:
        assert _handler is not None
        return await _handler.handle(req)

    @api.post("/jira/webhook")
    async def jira_webhook(req: Request) -> JSONResponse:
        s = get_settings()
        body = await req.body()
        ok = verify_jira_signature(
            body,
            signature_header=req.headers.get("X-Hub-Signature"),
            shared_secret_header=req.headers.get("X-OpsPilot-Webhook-Secret"),
            secret=s.jira_webhook_secret,
            require=s.webhook_require_signatures,
        )
        if not ok:
            log.warning("jira.signature_rejected")
            return JSONResponse({"status": "unauthorized"}, status_code=401)
        try:
            raw = json.loads(body.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)
        asyncio.create_task(_run_jira(raw))
        return JSONResponse({"status": "accepted"}, status_code=202)

    @api.post("/github/webhook")
    async def github_webhook(req: Request) -> JSONResponse:
        s = get_settings()
        body = await req.body()
        ok = verify_github_signature(
            body,
            req.headers.get("X-Hub-Signature-256"),
            s.github_webhook_secret,
            require=s.webhook_require_signatures,
        )
        if not ok:
            log.warning("github.signature_rejected")
            return JSONResponse({"status": "unauthorized"}, status_code=401)
        event_type = req.headers.get("X-GitHub-Event", "issues")
        try:
            raw = json.loads(body.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)
        asyncio.create_task(_run_github(raw, event_type))
        return JSONResponse({"status": "accepted"}, status_code=202)

    @api.post("/tickets/webhook")
    async def tickets_webhook(req: Request) -> JSONResponse:
        s = get_settings()
        body = await req.body()
        ok = verify_jira_signature(
            body,
            signature_header=req.headers.get("X-Hub-Signature"),
            shared_secret_header=req.headers.get("X-OpsPilot-Webhook-Secret"),
            secret=s.tickets_webhook_secret,
            require=s.webhook_require_signatures,
        )
        if not ok:
            return JSONResponse({"status": "unauthorized"}, status_code=401)
        try:
            raw = json.loads(body.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)
        asyncio.create_task(_run_tickets(raw))
        return JSONResponse({"status": "accepted"}, status_code=202)

    @api.post("/logs/webhook")
    async def logs_webhook(req: Request) -> JSONResponse:
        s = get_settings()
        body = await req.body()
        ok = verify_jira_signature(
            body,
            signature_header=req.headers.get("X-Hub-Signature"),
            shared_secret_header=req.headers.get("X-OpsPilot-Webhook-Secret"),
            secret=s.logs_webhook_secret,
            require=s.webhook_require_signatures,
        )
        if not ok:
            return JSONResponse({"status": "unauthorized"}, status_code=401)
        try:
            raw = json.loads(body.decode("utf-8"))
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)
        asyncio.create_task(_run_logs(raw))
        return JSONResponse({"status": "accepted"}, status_code=202)

    return api


async def _run_jira(raw: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(handle_jira_webhook, raw)
    except Exception:
        log.exception("jira.background_failed")


async def _run_github(raw: dict[str, Any], event_type: str) -> None:
    try:
        await asyncio.to_thread(handle_github_webhook, raw, event_type)
    except Exception:
        log.exception("github.background_failed")


async def _run_tickets(raw: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(handle_ticket_webhook, raw)
    except Exception:
        log.exception("tickets.background_failed")


async def _run_logs(raw: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(handle_logs_webhook, raw)
    except Exception:
        log.exception("logs.background_failed")


app = create_app()
