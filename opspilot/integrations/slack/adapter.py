"""
Production Slack adapter for OpsPilot.

Listens conceptually for message / app_mention events (Slack Event API),
parses incident keywords, enriches context, routes into OpsPilot triage,
posts live thread status, and handles human-approval Block Kit actions.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import structlog

from opspilot.config import Settings, get_settings
from opspilot.graph import resume_incident, run_incident
from opspilot.approval_queue import update_metadata as update_approval_metadata
from opspilot.approval_queue import get_by_event_id as get_durable_pending
from opspilot.approval_queue import remove_by_thread as remove_durable_pending
from opspilot.integrations.slack.models import SlackIncidentContext
from opspilot.integrations.slack.parsing import (
    extract_channel_tags,
    extract_incident_keywords,
    is_incident_message,
)
from opspilot.integrations.slack.rate_limit import AsyncRateLimiter, RateLimitError
from opspilot.schemas import (
    HumanApprovalDecision,
    IncidentEvent,
    IncidentSource,
)

log = structlog.get_logger(__name__)

# In-flight Slack incident → OpsPilot LangGraph thread_id
_PENDING_APPROVALS: dict[str, dict[str, Any]] = {}


Triager = Callable[[IncidentEvent], Awaitable[dict[str, Any]]]


class SlackAdapter:
    """
    Async Slack ↔ OpsPilot bridge.

    Designed for slack-bolt AsyncApp: ACK within ~3s, then process in a
    background task. Never blocks the event loop on OpsPilot graph work.
    """

    DELETED_SUBTYPES = frozenset({"message_deleted", "message_changed"})

    def __init__(
        self,
        *,
        client: Any | None = None,
        settings: Settings | None = None,
        triager: Triager | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self._triager = triager or self._default_triager
        self.rate_limiter = rate_limiter or AsyncRateLimiter(
            max_calls=self.settings.slack_max_incidents_per_minute,
            period_seconds=60.0,
        )
        self._clock = clock or time.monotonic
        self._status_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Event intake
    # ------------------------------------------------------------------

    async def handle_event(self, event: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        """
        Entry point for Slack Events API payloads (message / app_mention).

        Returns a small status dict. Raises nothing for expected skips
        (channel mismatch, deleted, non-incident). Raises RateLimitError
        when intake is saturated (caller should ACK and optionally warn).
        """
        if self._is_deleted_or_tombstone(event):
            log.info("slack.skip_deleted", channel=event.get("channel"), ts=event.get("ts"))
            return {"status": "skipped", "reason": "deleted_message"}

        channel_id = str(event.get("channel") or "")
        if not self.is_channel_allowed(channel_id):
            log.info("slack.skip_channel_mismatch", channel_id=channel_id)
            return {"status": "skipped", "reason": "channel_mismatch"}

        text = (event.get("text") or "").strip()
        # app_mention strips bot mention later; still check keywords on raw text
        if event.get("type") == "app_mention" and not is_incident_message(text):
            # Mentions without incident keywords still triage (explicit ping).
            keywords = ["app_mention"]
        else:
            keywords = extract_incident_keywords(text)
            if not keywords and event.get("type") != "app_mention":
                return {"status": "skipped", "reason": "not_incident"}

        if not await self.rate_limiter.try_acquire():
            retry = self.rate_limiter.seconds_until_available()
            log.warning("slack.rate_limited", retry_after=retry, channel_id=channel_id)
            raise RateLimitError(retry_after=retry)

        ctx = await self.enrich_context(event, team_id=team_id, matched_keywords=keywords)
        self._log_trace(ctx)
        incident = self.to_incident_event(ctx)

        # Fire-and-forget triage — caller already ACK'd Slack.
        asyncio.create_task(self._process_incident(ctx, incident), name=f"opspilot-{ctx.event_id}")
        return {
            "status": "accepted",
            "event_id": str(ctx.event_id),
            "channel_id": ctx.channel_id,
            "thread_ts": ctx.thread_ts or ctx.message_ts,
        }

    def is_channel_allowed(self, channel_id: str) -> bool:
        allowed = self.settings.slack_allowed_channels
        if not allowed:
            return True  # unrestricted when unset
        return channel_id in allowed

    def _is_deleted_or_tombstone(self, event: dict[str, Any]) -> bool:
        subtype = event.get("subtype")
        if subtype in {"message_deleted", "tombstone"}:
            return True
        if subtype == "message_changed":
            # Treat pure deletes / empty replacements as deleted.
            msg = event.get("message") or {}
            if msg.get("subtype") == "tombstone" or not (msg.get("text") or "").strip():
                return True
        # Explicit deleted_ts on some payloads
        if event.get("deleted_ts") and not event.get("text"):
            return True
        return False

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    async def enrich_context(
        self,
        event: dict[str, Any],
        *,
        team_id: str | None,
        matched_keywords: list[str],
    ) -> SlackIncidentContext:
        channel_id = str(event.get("channel") or "")
        user_id = str(event.get("user") or "")
        message_ts = str(event.get("ts") or "")
        thread_ts = str(event.get("thread_ts") or message_ts)
        text = (event.get("text") or "").strip()

        channel_purpose = ""
        channel_topic = ""
        user_role = "member"
        thread_history: list[dict[str, Any]] = []
        related: list[dict[str, Any]] = []

        if self.client is not None:
            channel_purpose, channel_topic = await self._fetch_channel_meta(channel_id)
            user_role = await self._fetch_user_role(user_id)
            thread_history = await self._fetch_thread_history(channel_id, thread_ts)
            related = await self._fetch_related_messages(channel_id, limit=10)

        tags = extract_channel_tags(channel_topic, channel_purpose)
        return SlackIncidentContext(
            event_id=uuid4(),
            channel_id=channel_id,
            user_id=user_id,
            message_ts=message_ts,
            thread_ts=thread_ts,
            team_id=team_id,
            text=text,
            matched_keywords=matched_keywords,
            channel_purpose=channel_purpose,
            user_role=user_role,
            thread_history=thread_history,
            related_messages=related,
            channel_tags=tags,
        )

    async def _fetch_channel_meta(self, channel_id: str) -> tuple[str, str]:
        try:
            resp = await self._slack_api("conversations_info", channel=channel_id)
            ch = (resp or {}).get("channel") or {}
            purpose = ((ch.get("purpose") or {}).get("value")) or ""
            topic = ((ch.get("topic") or {}).get("value")) or ""
            return purpose, topic
        except Exception as exc:  # pragma: no cover - network
            log.warning("slack.channel_meta_failed", error=str(exc), channel_id=channel_id)
            return "", ""

    async def _fetch_user_role(self, user_id: str) -> str:
        if not user_id:
            return "unknown"
        try:
            resp = await self._slack_api("users_info", user=user_id)
            user = (resp or {}).get("user") or {}
            if user.get("is_admin") or user.get("is_owner"):
                return "admin"
            if user.get("is_restricted") or user.get("is_ultra_restricted"):
                return "guest"
            return "member"
        except Exception as exc:  # pragma: no cover
            log.warning("slack.user_info_failed", error=str(exc), user_id=user_id)
            return "member"

    async def _fetch_thread_history(self, channel_id: str, thread_ts: str) -> list[dict[str, Any]]:
        try:
            resp = await self._slack_api(
                "conversations_replies",
                channel=channel_id,
                ts=thread_ts,
                limit=20,
            )
            messages = (resp or {}).get("messages") or []
            return [
                {"user": m.get("user"), "text": m.get("text"), "ts": m.get("ts")}
                for m in messages
                if m.get("text")
            ]
        except Exception as exc:  # pragma: no cover
            log.warning("slack.thread_history_failed", error=str(exc))
            return []

    async def _fetch_related_messages(self, channel_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        try:
            resp = await self._slack_api(
                "conversations_history",
                channel=channel_id,
                limit=limit,
            )
            messages = (resp or {}).get("messages") or []
            out: list[dict[str, Any]] = []
            for m in messages:
                text = m.get("text") or ""
                if is_incident_message(text) or True:
                    # Always keep last N channel messages for context.
                    out.append({"user": m.get("user"), "text": text, "ts": m.get("ts")})
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:  # pragma: no cover
            log.warning("slack.related_failed", error=str(exc))
            return []

    async def _slack_api(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Call AsyncWebClient with rate-limit awareness."""
        assert self.client is not None
        fn = getattr(self.client, method)
        try:
            resp = await fn(**kwargs)
            data = resp.data if hasattr(resp, "data") else dict(resp)
            return data
        except Exception as exc:
            # slack_sdk.errors.SlackApiError carries response
            response = getattr(exc, "response", None)
            if response is not None and getattr(response, "status_code", None) == 429:
                headers = getattr(response, "headers", {}) or {}
                retry_after = float(headers.get("Retry-After", 1))
                delay = self.rate_limiter.note_slack_rate_limit(retry_after)
                log.warning("slack.api_429", method=method, retry_after=delay)
                await asyncio.sleep(delay)
                resp = await fn(**kwargs)
                return resp.data if hasattr(resp, "data") else dict(resp)
            raise

    # ------------------------------------------------------------------
    # Routing → OpsPilot
    # ------------------------------------------------------------------

    def to_incident_event(self, ctx: SlackIncidentContext) -> IncidentEvent:
        return IncidentEvent(
            event_id=ctx.event_id,
            source=IncidentSource.SLACK,
            content=ctx.triage_content(),
            raw_metadata={
                **ctx.trace.as_dict(),
                "matched_keywords": ctx.matched_keywords,
                "channel_tags": ctx.channel_tags,
                "user_role": ctx.user_role,
                "channel_purpose": ctx.channel_purpose,
            },
        )

    async def _default_triager(self, event: IncidentEvent) -> dict[str, Any]:
        # Graph invoke is sync — run in a worker thread so we stay async.
        return await asyncio.to_thread(run_incident, event, persist=True)

    async def _process_incident(self, ctx: SlackIncidentContext, incident: IncidentEvent) -> None:
        status_ts = await self.post_status(
            ctx.channel_id,
            ctx.thread_ts or ctx.message_ts,
            "OpsPilot accepted incident — starting triage…",
        )
        poller: asyncio.Task[None] | None = None
        if status_ts:
            poller = asyncio.create_task(
                self._status_poll_loop(
                    ctx.channel_id,
                    status_ts,
                    started_at=self._clock(),
                    label="triaging",
                )
            )
            self._status_tasks[str(ctx.event_id)] = poller

        try:
            state = await self._triager(incident)
        except Exception as exc:
            log.exception("slack.triage_failed", event_id=str(ctx.event_id), error=str(exc))
            if poller:
                poller.cancel()
            await self.post_status(
                ctx.channel_id,
                ctx.thread_ts or ctx.message_ts,
                f"OpsPilot triage failed: {exc}",
                update_ts=status_ts,
            )
            return
        finally:
            if poller and not poller.done():
                poller.cancel()
                self._status_tasks.pop(str(ctx.event_id), None)

        await self._handle_triage_result(ctx, state, status_ts=status_ts)

    async def _handle_triage_result(
        self,
        ctx: SlackIncidentContext,
        state: dict[str, Any],
        *,
        status_ts: str | None,
    ) -> None:
        if "__interrupt__" in state:
            thread_id = state.get("thread_id")
            _PENDING_APPROVALS[str(ctx.event_id)] = {
                "graph_thread_id": thread_id,
                "channel_id": ctx.channel_id,
                "thread_ts": ctx.thread_ts or ctx.message_ts,
                "status_ts": status_ts,
                "user_id": ctx.user_id,
            }
            if thread_id:
                update_approval_metadata(
                    str(thread_id),
                    channel_id=ctx.channel_id,
                    thread_ts=ctx.thread_ts or ctx.message_ts,
                    status_ts=status_ts,
                    user_id=ctx.user_id,
                )
            await self.post_approval_prompt(ctx, state, status_ts=status_ts)
            return

        summary = self._format_final_summary(state)
        await self.post_status(
            ctx.channel_id,
            ctx.thread_ts or ctx.message_ts,
            summary,
            update_ts=status_ts,
        )

    def _format_final_summary(self, state: dict[str, Any]) -> str:
        routing = state.get("routing")
        bits = ["OpsPilot finished."]
        if routing is not None:
            bits.append(f"routing=`{routing.routing_decision.value}`")
            bits.append(f"confidence=`{routing.confidence_score}`")
        if state.get("execution") is not None:
            bits.append(f"execution: {state['execution'].summary}")
        if state.get("escalation") is not None:
            bits.append(f"escalation: {state['escalation'].reason}")
        return " ".join(bits)

    # ------------------------------------------------------------------
    # Live status updates
    # ------------------------------------------------------------------

    async def post_status(
        self,
        channel_id: str,
        thread_ts: str,
        text: str,
        *,
        update_ts: str | None = None,
    ) -> str | None:
        if self.client is None:
            return None
        try:
            if update_ts:
                await self._slack_api(
                    "chat_update",
                    channel=channel_id,
                    ts=update_ts,
                    text=text,
                )
                return update_ts
            resp = await self._slack_api(
                "chat_postMessage",
                channel=channel_id,
                thread_ts=thread_ts,
                text=text,
            )
            return str((resp or {}).get("ts") or "") or None
        except Exception as exc:  # pragma: no cover
            log.warning("slack.status_failed", error=str(exc))
            return None

    async def _status_poll_loop(
        self,
        channel_id: str,
        status_ts: str,
        *,
        started_at: float,
        label: str,
        interval: float | None = None,
    ) -> None:
        interval = interval if interval is not None else self.settings.slack_status_poll_seconds
        try:
            while True:
                await asyncio.sleep(interval)
                elapsed = int(self._clock() - started_at)
                text = f"OpsPilot {label}… _(updated {elapsed} seconds ago)_"
                await self.post_status(channel_id, status_ts, text, update_ts=status_ts)
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Human approval UI
    # ------------------------------------------------------------------

    async def post_approval_prompt(
        self,
        ctx: SlackIncidentContext,
        state: dict[str, Any],
        *,
        status_ts: str | None,
    ) -> None:
        interrupt = state.get("__interrupt__") or []
        payload = interrupt[0].value if interrupt and hasattr(interrupt[0], "value") else {}
        context = (payload.get("context_summary") if isinstance(payload, dict) else None) or ""
        proposals = (payload.get("proposals") if isinstance(payload, dict) else None) or []
        proposal_lines = "\n".join(
            f"• `{p.get('tool_name')}` {p.get('parameters')}" for p in proposals
        ) or "_(no proposals)_"

        text = (
            f"*OpsPilot needs approval*\n"
            f"{context[:400]}\n\n"
            f"*Proposals:*\n{proposal_lines}"
        )
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "block_id": f"opspilot_approval_{ctx.event_id}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "opspilot_approve",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "value": str(ctx.event_id),
                    },
                    {
                        "type": "button",
                        "action_id": "opspilot_reject",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": str(ctx.event_id),
                    },
                    {
                        "type": "button",
                        "action_id": "opspilot_add_context",
                        "text": {"type": "plain_text", "text": "Add context"},
                        "value": str(ctx.event_id),
                    },
                ],
            },
        ]
        if self.client is None:
            return
        try:
            await self._slack_api(
                "chat_postMessage",
                channel=ctx.channel_id,
                thread_ts=ctx.thread_ts or ctx.message_ts,
                text="OpsPilot needs approval",
                blocks=blocks,
            )
            if status_ts:
                await self.post_status(
                    ctx.channel_id,
                    ctx.thread_ts or ctx.message_ts,
                    "OpsPilot waiting for human approval…",
                    update_ts=status_ts,
                )
        except Exception as exc:  # pragma: no cover
            log.warning("slack.approval_prompt_failed", error=str(exc))

    def build_context_modal(self, event_id: str) -> dict[str, Any]:
        """Block Kit modal for 'Add context'."""
        return {
            "type": "modal",
            "callback_id": "opspilot_context_modal",
            "private_metadata": event_id,
            "title": {"type": "plain_text", "text": "Add context"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "context_block",
                    "label": {"type": "plain_text", "text": "Additional context"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "context_input",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Anything reviewers should know…",
                        },
                    },
                }
            ],
        }

    async def handle_approval_action(
        self,
        *,
        event_id: str,
        decision: HumanApprovalDecision,
        reviewer_id: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        pending = _PENDING_APPROVALS.get(event_id)
        if not pending:
            durable = get_durable_pending(event_id)
            if durable is None:
                return {"status": "error", "reason": "unknown_or_expired_event"}
            graph_thread_id = durable.thread_id
            channel_id = durable.channel_id
            thread_ts = durable.thread_ts
            status_ts = durable.status_ts
        else:
            graph_thread_id = pending["graph_thread_id"]
            channel_id = pending["channel_id"]
            thread_ts = pending["thread_ts"]
            status_ts = pending.get("status_ts")

        state = await asyncio.to_thread(
            resume_incident,
            graph_thread_id,
            {
                "request_id": event_id,
                "decision": decision.value,
                "reviewer_id": reviewer_id,
                "notes": notes,
            },
            persist=True,
        )
        _PENDING_APPROVALS.pop(event_id, None)
        remove_durable_pending(str(graph_thread_id))
        summary = self._format_final_summary(state)
        if channel_id and thread_ts:
            await self.post_status(
                channel_id,
                thread_ts,
                f"Reviewer <@{reviewer_id}> chose *{decision.value}*.\n{summary}",
                update_ts=status_ts,
            )
        return {"status": "ok", "event_id": event_id, "decision": decision.value}

    async def handle_context_submission(
        self,
        *,
        event_id: str,
        reviewer_id: str,
        context_text: str,
    ) -> dict[str, Any]:
        pending = _PENDING_APPROVALS.get(event_id)
        if not pending:
            return {"status": "error", "reason": "unknown_or_expired_event"}
        # Context is recorded as a thread note; approval still required.
        await self.post_status(
            pending["channel_id"],
            pending["thread_ts"],
            f"*Added context* by <@{reviewer_id}>:\n>{context_text[:500]}",
        )
        pending["extra_context"] = context_text
        return {"status": "ok", "event_id": event_id}

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _log_trace(self, ctx: SlackIncidentContext) -> None:
        log.info(
            "slack.incident_accepted",
            **ctx.trace.as_dict(),
            keywords=ctx.matched_keywords,
            user_role=ctx.user_role,
        )


def get_pending_approval(event_id: str | UUID) -> dict[str, Any] | None:
    return _PENDING_APPROVALS.get(str(event_id))


def clear_pending_approvals() -> None:
    _PENDING_APPROVALS.clear()
