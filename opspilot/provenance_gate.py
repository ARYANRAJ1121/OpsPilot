"""
opspilot/provenance_gate.py

Deterministic Provenance Gate — pure Python, zero LLM calls.

Validates that every ActionProposal from the Action Planner cites only
evidence traceable to a real ToolOutput collected during this incident's
investigation.  Raw event.content text is never acceptable evidence.

Approval rules (both must hold):
  1. evidence_refs is non-empty.
  2. Every UUID in evidence_refs resolves to a ToolOutput in the
     available_tool_outputs set passed in for this incident.

Proposals failing either condition are rejected before the
Policy Engine sees them.
"""

import time
from uuid import UUID

import structlog

from opspilot.schemas import (
    ActionPlannerOutput,
    ActionProposal,
    ProvenanceCheckResult,
    ToolOutput,
)

log = structlog.get_logger(__name__)


def check_provenance(
    planner_output: ActionPlannerOutput,
    available_tool_outputs: list[ToolOutput],
) -> ProvenanceCheckResult:
    """
    Run the Deterministic Provenance Gate.

    Args:
        planner_output: proposals emitted by the Action Planner Agent.
        available_tool_outputs: every ToolOutput collected by the
            Investigation and Knowledge Retrieval agents for this incident.
            The gate resolves evidence_refs exclusively against this set.

    Returns:
        ProvenanceCheckResult with the approved/rejected split, per-proposal
        rejection reasons, and a top-level passed flag.
    """
    t_start = time.monotonic()

    known_ids: set[UUID] = {to.tool_output_id for to in available_tool_outputs}

    log.info(
        "provenance_gate.start",
        event_id=str(planner_output.event_id),
        proposal_count=len(planner_output.proposals),
        known_tool_output_count=len(known_ids),
    )

    approved: list[ActionProposal] = []
    rejected: list[ActionProposal] = []
    rejection_reasons: dict[str, str] = {}

    for proposal in planner_output.proposals:
        reason = _reject_reason(proposal, known_ids)
        if reason is None:
            approved.append(proposal)
        else:
            rejected.append(proposal)
            rejection_reasons[str(proposal.proposal_id)] = reason

    # passed only when at least one proposal survived — the Policy Engine
    # needs something to act on; an empty approved list is a hard stop.
    passed = len(approved) > 0

    latency_ms = (time.monotonic() - t_start) * 1000

    log.info(
        "provenance_gate.result",
        event_id=str(planner_output.event_id),
        passed=passed,
        approved_count=len(approved),
        rejected_count=len(rejected),
        rejection_reasons=rejection_reasons,
        latency_ms=round(latency_ms, 2),
    )

    return ProvenanceCheckResult(
        passed=passed,
        approved_proposals=approved,
        rejected_proposals=rejected,
        rejection_reasons=rejection_reasons,
    )


def _reject_reason(
    proposal: ActionProposal,
    known_ids: set[UUID],
) -> str | None:
    """
    Return a human-readable rejection reason, or None if the proposal passes.

    Kept as a private helper so the core validation logic is unit-testable
    independently of logging and I/O plumbing.
    """
    if not proposal.evidence_refs:
        return (
            "proposal carries no evidence_refs — "
            "raw event content is not valid evidence"
        )

    unresolved = [uid for uid in proposal.evidence_refs if uid not in known_ids]
    if unresolved:
        return (
            f"unresolvable evidence_refs: {[str(u) for u in unresolved]} — "
            "every reference must map to a ToolOutput collected for this incident"
        )

    return None
