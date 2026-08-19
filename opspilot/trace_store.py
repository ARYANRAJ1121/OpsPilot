"""
opspilot/trace_store.py

Durable, append-only trace persistence. Every incident run writes its
TraceEntry list to a JSON Lines file — one JSON object per line — so runs
can be replayed, audited, and fed to the eval harness later.

The store is intentionally file-based and dependency-free; a real
deployment would swap this for a database or object store behind the same
two functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import structlog

from opspilot.config import get_settings
from opspilot.schemas import TraceEntry

log = structlog.get_logger(__name__)


def _trace_path(event_id: UUID, trace_dir: Path | None) -> Path:
    base = trace_dir or get_settings().trace_dir
    base.mkdir(parents=True, exist_ok=True)
    return base / f"incident-{event_id}.jsonl"


def write_traces(
    event_id: UUID,
    traces: list[TraceEntry],
    *,
    trace_dir: Path | None = None,
) -> Path:
    """Persist all traces for one incident to a JSONL file; return its path."""
    path = _trace_path(event_id, trace_dir)
    with path.open("w", encoding="utf-8") as fh:
        for entry in traces:
            fh.write(json.dumps(entry.model_dump(mode="json")) + "\n")
    log.info("trace_store.write", event_id=str(event_id), count=len(traces), path=str(path))
    return path


def read_traces(path: Path) -> list[dict]:
    """Read a JSONL trace file back into a list of dicts."""
    with Path(path).open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
