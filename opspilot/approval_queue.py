"""
Durable pending-approval queue (JSON file).

Survives process restart alongside the SQLite LangGraph checkpointer so
web / Slack / CLI can resume HITL after a restart.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from opspilot.config import get_settings

log = structlog.get_logger(__name__)
_LOCK = threading.Lock()


@dataclass
class PendingApproval:
    thread_id: str
    event_id: str
    request_id: str
    context_summary: str
    proposals: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str | None = None
    channel_id: str | None = None
    thread_ts: str | None = None
    status_ts: str | None = None
    user_id: str | None = None
    extra_context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _queue_path() -> Path:
    settings = get_settings()
    path = Path(settings.approval_queue_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> dict[str, PendingApproval]:
    path = _queue_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("approval_queue.corrupt", path=str(path))
        return {}
    out: dict[str, PendingApproval] = {}
    for key, item in (raw or {}).items():
        try:
            out[key] = PendingApproval(**item)
        except TypeError:
            continue
    return out


def _save(items: dict[str, PendingApproval]) -> None:
    path = _queue_path()
    payload = {k: v.to_dict() for k, v in items.items()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def upsert_pending(entry: PendingApproval) -> None:
    with _LOCK:
        items = _load()
        items[entry.thread_id] = entry
        _save(items)
    log.info(
        "approval_queue.upsert",
        thread_id=entry.thread_id,
        event_id=entry.event_id,
    )


def update_metadata(
    thread_id: str,
    *,
    channel_id: str | None = None,
    thread_ts: str | None = None,
    status_ts: str | None = None,
    user_id: str | None = None,
    extra_context: str | None = None,
) -> PendingApproval | None:
    with _LOCK:
        items = _load()
        entry = items.get(thread_id)
        if entry is None:
            return None
        if channel_id is not None:
            entry.channel_id = channel_id
        if thread_ts is not None:
            entry.thread_ts = thread_ts
        if status_ts is not None:
            entry.status_ts = status_ts
        if user_id is not None:
            entry.user_id = user_id
        if extra_context is not None:
            entry.extra_context = extra_context
        items[thread_id] = entry
        _save(items)
        return entry


def list_pending() -> list[PendingApproval]:
    with _LOCK:
        items = _load()
    return sorted(items.values(), key=lambda e: e.created_at, reverse=True)


def get_by_thread(thread_id: str) -> PendingApproval | None:
    with _LOCK:
        return _load().get(thread_id)


def get_by_event_id(event_id: str) -> PendingApproval | None:
    with _LOCK:
        for entry in _load().values():
            if entry.event_id == event_id or entry.request_id == event_id:
                return entry
    return None


def remove_by_thread(thread_id: str) -> None:
    with _LOCK:
        items = _load()
        if thread_id in items:
            del items[thread_id]
            _save(items)
            log.info("approval_queue.remove", thread_id=thread_id)


def clear_queue() -> None:
    """Test helper — wipe the durable queue file."""
    with _LOCK:
        path = _queue_path()
        if path.exists():
            path.unlink()
