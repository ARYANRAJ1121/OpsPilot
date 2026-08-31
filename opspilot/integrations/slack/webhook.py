"""
FastAPI + slack-bolt AsyncApp webhook for OpsPilot Slack Events.

Slack requires a fast ACK (~3s). We verify signatures via Bolt, ACK
immediately, and schedule OpsPilot triage on the event loop.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from opspilot.config import get_settings
from opspilot.integrations.slack.adapter import SlackAdapter
from opspilot.integrations.slack.events import handle_slack_request
from opspilot.integrations.slack.rate_limit import RateLimitError
from opspilot.schemas import HumanApprovalDecision

log = structlog.get_logger(__name__)

_adapter: SlackAdapter | None = None
_bolt_app: AsyncApp | None = None
_handler: AsyncSlackRequestHandler | None = None


def get_adapter() -> SlackAdapter:
    global _adapter
    if _adapter is None:
        settings = get_settings()
        client = None
        if settings.slack_bot_token:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=settings.slack_bot_token)
        _adapter = SlackAdapter(client=client, settings=settings)
    return _adapter


def build_bolt_app(*, adapter: SlackAdapter | None = None) -> AsyncApp:
    settings = get_settings()
    adapter = adapter or get_adapter()

    app = AsyncApp(
        token=settings.slack_bot_token or "xoxb-test",
        signing_secret=settings.slack_signing_secret or "test-signing-secret",
        process_before_response=False,  # ACK first, then process
        request_verification_enabled=not settings.slack_skip_request_verification,
    )
    if settings.slack_skip_request_verification:
        log.warning(
            "slack.request_verification_disabled",
            hint="Set OPSPILOT_SLACK_SKIP_REQUEST_VERIFICATION=false after fixing SLACK_SIGNING_SECRET",
        )

    async def _ack_and_schedule(event: dict[str, Any], body: dict[str, Any]) -> None:
        """Schedule background work; Bolt ACK is handled by the framework."""

        async def _run() -> None:
            try:
                await adapter.handle_event(event, team_id=body.get("team_id"))
            except RateLimitError as exc:
                channel = event.get("channel")
                thread = event.get("thread_ts") or event.get("ts")
                if channel and thread:
                    await adapter.post_status(
                        str(channel),
                        str(thread),
                        f"OpsPilot is rate-limited — retry in ~{int(exc.retry_after)}s.",
                    )
            except Exception:
                log.exception("slack.background_failed")

        asyncio.create_task(_run())

    @app.event("message")
    async def on_message(event: dict[str, Any], body: dict[str, Any], ack) -> None:  # type: ignore[no-untyped-def]
        await ack()
        # Ignore bot messages / message subtypes we don't want (edits handled in adapter)
        if event.get("bot_id") or event.get("subtype") in {"bot_message", "message_replied"}:
            return
        await _ack_and_schedule(event, body)

    @app.event("app_mention")
    async def on_app_mention(event: dict[str, Any], body: dict[str, Any], ack) -> None:  # type: ignore[no-untyped-def]
        await ack()
        await _ack_and_schedule(event, body)

    @app.action("opspilot_approve")
    async def on_approve(ack, body, action) -> None:  # type: ignore[no-untyped-def]
        await ack()
        event_id = action.get("value")
        user_id = (body.get("user") or {}).get("id", "unknown")
        await adapter.handle_approval_action(
            event_id=event_id,
            decision=HumanApprovalDecision.APPROVED,
            reviewer_id=user_id,
            notes="Approved via Slack button",
        )

    @app.action("opspilot_reject")
    async def on_reject(ack, body, action) -> None:  # type: ignore[no-untyped-def]
        await ack()
        event_id = action.get("value")
        user_id = (body.get("user") or {}).get("id", "unknown")
        await adapter.handle_approval_action(
            event_id=event_id,
            decision=HumanApprovalDecision.REJECTED,
            reviewer_id=user_id,
            notes="Rejected via Slack button",
        )

    @app.action("opspilot_add_context")
    async def on_add_context(ack, body, client, action) -> None:  # type: ignore[no-untyped-def]
        await ack()
        event_id = action.get("value")
        trigger_id = body.get("trigger_id")
        modal = adapter.build_context_modal(event_id)
        await client.views_open(trigger_id=trigger_id, view=modal)

    @app.view("opspilot_context_modal")
    async def on_context_modal(ack, body, view) -> None:  # type: ignore[no-untyped-def]
        await ack()
        event_id = view.get("private_metadata")
        user_id = (body.get("user") or {}).get("id", "unknown")
        values = view.get("state", {}).get("values", {})
        context_text = (
            values.get("context_block", {})
            .get("context_input", {})
            .get("value", "")
        )
        await adapter.handle_context_submission(
            event_id=event_id,
            reviewer_id=user_id,
            context_text=context_text or "",
        )

    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bolt_app, _handler
    _bolt_app = build_bolt_app()
    _handler = AsyncSlackRequestHandler(_bolt_app)
    log.info("slack.webhook_ready", configured=get_settings().slack_configured)
    yield


def create_app(*, adapter: SlackAdapter | None = None) -> FastAPI:
    """Factory used by uvicorn and tests."""
    global _bolt_app, _handler, _adapter
    if adapter is not None:
        _adapter = adapter

    api = FastAPI(title="OpsPilot Slack Webhook", version="1.0.1", lifespan=lifespan)

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/slack/events")
    async def slack_events(req: Request) -> Response:
        assert _handler is not None
        return await handle_slack_request(req, _handler)

    @api.post("/slack/interactions")
    async def slack_interactions(req: Request) -> Response:
        assert _handler is not None
        return await handle_slack_request(req, _handler)

    return api


# Module-level app for `uvicorn opspilot.integrations.slack.webhook:app`
app = create_app()
