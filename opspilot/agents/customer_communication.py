"""
Customer Communication Agent — independent branch; never merges back.

The LLM (when configured) polishes the customer-facing message tone. The
severity and target channels remain deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from opspilot.llm import enrich
from opspilot.schemas import (
    CustomerCommunicationOutput,
    IngestionOutput,
    RouterOutput,
)

_COMMS_SYSTEM = (
    "You are a customer communications lead during an incident. Write a calm, "
    "non-technical, 1-2 sentence status update. Do not promise timelines or "
    "admit fault. Do not include internal service names or metrics."
)


def run_customer_communication(
    ingestion: IngestionOutput,
    router: RouterOutput,
) -> CustomerCommunicationOutput:
    fallback = (
        f"We are investigating a {router.severity.value} incident: "
        f"{ingestion.normalized_title}. No customer action is required yet."
    )
    message = enrich(
        _COMMS_SYSTEM,
        f"Severity: {router.severity.value}. Incident: {ingestion.normalized_title}.",
        fallback=fallback,
    )
    return CustomerCommunicationOutput(
        event_id=ingestion.event_id,
        severity=router.severity,
        message_draft=message,
        target_channels=["status-page", "support"],
        dispatched_at=datetime.now(timezone.utc),
    )
