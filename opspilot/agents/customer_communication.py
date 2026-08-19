"""Customer Communication Agent — independent branch; never merges back."""

from __future__ import annotations

from opspilot.schemas import (
    CustomerCommunicationOutput,
    IngestionOutput,
    RouterOutput,
)


def run_customer_communication(
    ingestion: IngestionOutput,
    router: RouterOutput,
) -> CustomerCommunicationOutput:
    message = (
        f"We are investigating a {router.severity.value} incident: "
        f"{ingestion.normalized_title}. No customer action is required yet."
    )
    return CustomerCommunicationOutput(
        event_id=ingestion.event_id,
        severity=router.severity,
        message_draft=message,
        target_channels=["status-page", "support"],
        dispatched_at=None,
    )
