"""Typed models for Slack → OpsPilot handoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class SlackTraceMeta:
    """Audit fields logged for every Slack-originated incident."""

    event_id: UUID
    user_id: str
    channel_id: str
    thread_ts: str
    message_ts: str
    team_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "message_ts": self.message_ts,
            "team_id": self.team_id,
        }


@dataclass
class SlackIncidentContext:
    """Enriched Slack context routed into OpsPilot triage."""

    event_id: UUID = field(default_factory=uuid4)
    channel_id: str = ""
    user_id: str = ""
    message_ts: str = ""
    thread_ts: str = ""
    team_id: str | None = None
    text: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    channel_purpose: str = ""
    user_role: str = "member"
    thread_history: list[dict[str, Any]] = field(default_factory=list)
    related_messages: list[dict[str, Any]] = field(default_factory=list)
    channel_tags: list[str] = field(default_factory=list)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted: bool = False

    @property
    def trace(self) -> SlackTraceMeta:
        return SlackTraceMeta(
            event_id=self.event_id,
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_ts=self.thread_ts or self.message_ts,
            message_ts=self.message_ts,
            team_id=self.team_id,
        )

    def triage_content(self) -> str:
        """Flatten enriched context into the alert body OpsPilot ingests."""
        parts = [self.text.strip()]
        if self.matched_keywords:
            parts.append(f"keywords={','.join(self.matched_keywords)}")
        if self.channel_purpose:
            parts.append(f"channel_purpose={self.channel_purpose}")
        if self.user_role:
            parts.append(f"user_role={self.user_role}")
        if self.channel_tags:
            parts.append(f"channel_tags={','.join(self.channel_tags)}")
        if self.thread_history:
            recent = " | ".join(
                f"{m.get('user', '?')}: {(m.get('text') or '')[:80]}"
                for m in self.thread_history[-5:]
            )
            parts.append(f"thread_history={recent}")
        if self.related_messages:
            related = " | ".join(
                f"{m.get('user', '?')}: {(m.get('text') or '')[:80]}"
                for m in self.related_messages[:5]
            )
            parts.append(f"related={related}")
        return "\n".join(p for p in parts if p)
