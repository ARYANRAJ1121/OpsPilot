"""Unit tests for SlackAdapter — no network, no real Slack."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from opspilot.config import Settings, reset_settings_cache
from opspilot.integrations.slack.adapter import SlackAdapter, clear_pending_approvals
from opspilot.integrations.slack.parsing import extract_incident_keywords, is_incident_message
from opspilot.integrations.slack.rate_limit import AsyncRateLimiter, RateLimitError
from opspilot.schemas import IncidentEvent


def _settings(**overrides: Any) -> Settings:
    base = dict(
        groq_api_key=None,
        llm_model="openai/gpt-oss-20b",
        llm_temperature=0.1,
        llm_enabled=False,
        confidence_auto_execute_threshold=0.7,
        trace_dir=__import__("pathlib").Path("trace_store"),
        slack_bot_token="xoxb-test",
        slack_signing_secret="secret",
        slack_app_token=None,
        slack_allowed_channels=("C_ALLOWED",),
        slack_status_poll_seconds=0.05,
        slack_ack_timeout_seconds=3.0,
        slack_max_incidents_per_minute=30,
        guardrails_enabled=True,
        guardrails_llm=False,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clean():
    clear_pending_approvals()
    reset_settings_cache()
    yield
    clear_pending_approvals()
    reset_settings_cache()


class TestParsing:
    def test_detects_alert_emoji_and_incident_prefix(self) -> None:
        text = "⚠️ alert: api-service error rate 18%"
        assert is_incident_message(text)
        keys = extract_incident_keywords(text)
        assert "alert_emoji" in keys
        assert "alert_word" in keys

    def test_ignores_casual_chat(self) -> None:
        assert not is_incident_message("lunch at 1?")


class TestChannelMismatch:
    @pytest.mark.asyncio
    async def test_skips_disallowed_channel(self) -> None:
        adapter = SlackAdapter(settings=_settings(), client=None, triager=AsyncMock())
        result = await adapter.handle_event(
            {
                "type": "message",
                "channel": "C_OTHER",
                "user": "U1",
                "ts": "1.0",
                "text": "incident: api down",
            }
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "channel_mismatch"
        assert adapter._triager.await_count == 0  # type: ignore[attr-defined]


class TestDeletedMessages:
    @pytest.mark.asyncio
    async def test_skips_message_deleted_subtype(self) -> None:
        adapter = SlackAdapter(settings=_settings(slack_allowed_channels=()), client=None)
        result = await adapter.handle_event(
            {
                "type": "message",
                "subtype": "message_deleted",
                "channel": "C1",
                "deleted_ts": "1.0",
                "ts": "2.0",
            }
        )
        assert result["reason"] == "deleted_message"

    @pytest.mark.asyncio
    async def test_skips_tombstone_change(self) -> None:
        adapter = SlackAdapter(settings=_settings(slack_allowed_channels=()), client=None)
        result = await adapter.handle_event(
            {
                "type": "message",
                "subtype": "message_changed",
                "channel": "C1",
                "ts": "2.0",
                "message": {"subtype": "tombstone", "text": ""},
            }
        )
        assert result["reason"] == "deleted_message"


class TestRateLimitBackoff:
    @pytest.mark.asyncio
    async def test_try_acquire_exhaustion_raises(self) -> None:
        limiter = AsyncRateLimiter(max_calls=2, period_seconds=60.0)
        assert await limiter.try_acquire()
        assert await limiter.try_acquire()
        assert not await limiter.try_acquire()

        adapter = SlackAdapter(
            settings=_settings(slack_allowed_channels=(), slack_max_incidents_per_minute=2),
            client=None,
            rate_limiter=limiter,
            triager=AsyncMock(),
        )
        with pytest.raises(RateLimitError) as ei:
            await adapter.handle_event(
                {
                    "type": "message",
                    "channel": "C1",
                    "user": "U1",
                    "ts": "1.0",
                    "text": "incident: db down",
                }
            )
        assert ei.value.retry_after >= 0

    def test_note_slack_rate_limit_exponential(self) -> None:
        limiter = AsyncRateLimiter(max_calls=10, period_seconds=60.0)
        d1 = limiter.note_slack_rate_limit(None)
        assert d1 == 1.0
        # Simulate remaining backoff by setting again quickly
        d2 = limiter.note_slack_rate_limit(None)
        assert d2 >= d1
        d3 = limiter.note_slack_rate_limit(5.0)
        assert d3 == 5.0


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_accepts_incident_and_schedules_triage(self) -> None:
        done = asyncio.Event()
        captured: list[IncidentEvent] = []

        async def triager(event: IncidentEvent) -> dict[str, Any]:
            captured.append(event)
            done.set()
            return {
                "routing": MagicMock(
                    routing_decision=MagicMock(value="auto_execute"),
                    confidence_score=0.9,
                ),
                "execution": MagicMock(summary="restarted"),
            }

        def _resp(payload: dict[str, Any]) -> MagicMock:
            m = MagicMock()
            m.data = payload
            return m

        client = MagicMock()
        client.chat_postMessage = AsyncMock(return_value=_resp({"ts": "9.9", "ok": True}))
        client.chat_update = AsyncMock(return_value=_resp({"ok": True}))
        client.conversations_info = AsyncMock(
            return_value=_resp(
                {
                    "channel": {
                        "purpose": {"value": "prod alerts [env:prod]"},
                        "topic": {"value": "#incidents"},
                    }
                }
            )
        )
        client.users_info = AsyncMock(return_value=_resp({"user": {"is_admin": True}}))
        client.conversations_replies = AsyncMock(
            return_value=_resp(
                {"messages": [{"user": "U1", "text": "incident: start", "ts": "1.0"}]}
            )
        )
        client.conversations_history = AsyncMock(
            return_value=_resp(
                {"messages": [{"user": "U2", "text": "alert noise", "ts": "0.9"}]}
            )
        )

        adapter = SlackAdapter(
            settings=_settings(slack_allowed_channels=()),
            client=client,
            triager=triager,
            rate_limiter=AsyncRateLimiter(max_calls=100, period_seconds=60),
        )
        result = await adapter.handle_event(
            {
                "type": "message",
                "channel": "C1",
                "user": "U1",
                "ts": "1.0",
                "text": "incident: api-service error rate 18%",
            },
            team_id="T1",
        )
        assert result["status"] == "accepted"
        await asyncio.wait_for(done.wait(), timeout=2.0)
        assert captured
        assert captured[0].source.value == "slack"
        meta = captured[0].raw_metadata
        assert meta["channel_id"] == "C1"
        assert meta["user_id"] == "U1"
        assert meta["user_role"] == "admin"
        assert "env:prod" in meta.get("channel_tags", []) or "incidents" in meta.get(
            "channel_tags", []
        )


class TestApprovalModal:
    def test_build_context_modal(self) -> None:
        adapter = SlackAdapter(settings=_settings(), client=None)
        modal = adapter.build_context_modal("evt-123")
        assert modal["callback_id"] == "opspilot_context_modal"
        assert modal["private_metadata"] == "evt-123"
