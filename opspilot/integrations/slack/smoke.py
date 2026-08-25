"""Local Slack adapter smoke test — no Slack network required."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from opspilot.config import get_settings
from opspilot.integrations.slack.adapter import SlackAdapter
from opspilot.integrations.slack.rate_limit import AsyncRateLimiter
from opspilot.schemas import IncidentEvent


async def run_smoke() -> dict[str, Any]:
    done = asyncio.Event()
    seen: list[IncidentEvent] = []

    async def triager(event: IncidentEvent) -> dict[str, Any]:
        seen.append(event)
        done.set()
        return {
            "routing": MagicMock(
                routing_decision=MagicMock(value="auto_execute"),
                confidence_score=0.91,
            ),
            "execution": MagicMock(summary="smoke: restart_service simulated"),
        }

    def _resp(payload: dict[str, Any]) -> MagicMock:
        m = MagicMock()
        m.data = payload
        return m

    client = MagicMock()
    client.chat_postMessage = AsyncMock(return_value=_resp({"ts": "99.1", "ok": True}))
    client.chat_update = AsyncMock(return_value=_resp({"ok": True}))
    client.conversations_info = AsyncMock(
        return_value=_resp(
            {
                "channel": {
                    "purpose": {"value": "free-tier alerts [env:dev]"},
                    "topic": {"value": "#incidents"},
                }
            }
        )
    )
    client.users_info = AsyncMock(return_value=_resp({"user": {"is_admin": False}}))
    client.conversations_replies = AsyncMock(return_value=_resp({"messages": []}))
    client.conversations_history = AsyncMock(return_value=_resp({"messages": []}))

    settings = replace(get_settings(), slack_allowed_channels=())
    adapter = SlackAdapter(
        client=client,
        settings=settings,
        triager=triager,
        rate_limiter=AsyncRateLimiter(max_calls=100, period_seconds=60),
    )
    result = await adapter.handle_event(
        {
            "type": "message",
            "channel": "C_SMOKE",
            "user": "U_SMOKE",
            "ts": "1.234",
            "text": "incident: api-service error rate 18%",
        },
        team_id="T_SMOKE",
    )
    await asyncio.wait_for(done.wait(), timeout=5.0)
    return {
        "accept": result,
        "triaged": bool(seen),
        "content_preview": (seen[0].content[:160] if seen else None),
        "metadata": (seen[0].raw_metadata if seen else None),
    }


def main() -> int:
    out = asyncio.run(run_smoke())
    print("smoke-slack:", "PASS" if out.get("triaged") else "FAIL")
    print("  accept:", out.get("accept"))
    print("  preview:", out.get("content_preview"))
    return 0 if out.get("triaged") else 1


if __name__ == "__main__":
    raise SystemExit(main())
