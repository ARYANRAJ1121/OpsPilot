"""
Durable LangGraph checkpointer factory.

Default: SQLite file under OPSPILOT_CHECKPOINT_PATH (survives process restart).
Tests / ephemeral: OPSPILOT_CHECKPOINT_BACKEND=memory → MemorySaver.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import structlog

from opspilot.config import get_settings

log = structlog.get_logger(__name__)

_CONN: sqlite3.Connection | None = None
_CHECKPOINTER: Any | None = None


def get_checkpointer() -> Any:
    """Return a process-wide checkpointer (SQLite by default)."""
    global _CONN, _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    settings = get_settings()
    if settings.checkpoint_backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        _CHECKPOINTER = MemorySaver()
        log.info("checkpoint.backend", backend="memory")
        return _CHECKPOINTER

    from langgraph.checkpoint.sqlite import SqliteSaver

    path = Path(settings.checkpoint_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    _CONN = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(_CONN)
    saver.setup()
    _CHECKPOINTER = saver
    log.info("checkpoint.backend", backend="sqlite", path=str(path))
    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """Drop cached checkpointer (tests that change settings/backend)."""
    global _CONN, _CHECKPOINTER
    if _CONN is not None:
        try:
            _CONN.close()
        except Exception:  # pragma: no cover
            pass
    _CONN = None
    _CHECKPOINTER = None
