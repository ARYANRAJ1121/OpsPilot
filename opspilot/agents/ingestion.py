"""Ingestion Agent — normalize a raw IncidentEvent. No LLM."""

from __future__ import annotations

from opspilot.schemas import IncidentEvent, IngestionOutput


def run_ingestion(event: IncidentEvent) -> IngestionOutput:
    body = event.content.strip()
    first_line = body.splitlines()[0] if body else "Untitled incident"
    title = first_line.removeprefix("ALERT:").strip() or first_line
    if len(title) > 120:
        title = title[:117] + "..."

    return IngestionOutput(
        event_id=event.event_id,
        source=event.source,
        normalized_title=title,
        normalized_body=body,
        received_at=event.received_at,
        raw_metadata=event.raw_metadata,
    )
