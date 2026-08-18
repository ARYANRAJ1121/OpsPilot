"""
opspilot/policy_engine.py

Deterministic Policy Engine — pure Python, zero LLM calls.

Classifies every tool in an approved ActionProposal into one of three
permission tiers and enforces the corresponding approval rule:

  Tier 1 read_only        → auto-approved, no human needed
  Tier 2 reversible_write → auto-approved, no human needed
  Tier 3 high_risk_write  → approved but mandatory human review

Unknown tools are treated as high_risk_write (fail-safe default).

The engine operates on the approved_proposals list from the Provenance Gate
— it never sees rejected proposals.
"""

import time
from uuid import UUID

import structlog

from opspilot.schemas import (
    ActionProposal,
    PolicyDecision,
    PolicyEngineResult,
    ProvenanceCheckResult,
    ToolPermissionTier,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool tier registry
#
# Add new tools here as the simulated (and later real) tool layer grows.
# Anything absent from this registry falls back to HIGH_RISK_WRITE — the
# engine never silently auto-approves an unknown tool.
# ---------------------------------------------------------------------------

TOOL_TIER_REGISTRY: dict[str, ToolPermissionTier] = {
    # Tier 1 — read-only: zero state change
    "fetch_logs": ToolPermissionTier.READ_ONLY,
    "read_metrics": ToolPermissionTier.READ_ONLY,
    "describe_service": ToolPermissionTier.READ_ONLY,
    "list_pods": ToolPermissionTier.READ_ONLY,
    "get_config": ToolPermissionTier.READ_ONLY,
    "search_runbook": ToolPermissionTier.READ_ONLY,
    "get_deployment_status": ToolPermissionTier.READ_ONLY,
    "query_apm": ToolPermissionTier.READ_ONLY,
    # Tier 2 — reversible write: state change that can be undone
    "restart_service": ToolPermissionTier.REVERSIBLE_WRITE,
    "toggle_feature_flag": ToolPermissionTier.REVERSIBLE_WRITE,
    "flush_cache": ToolPermissionTier.REVERSIBLE_WRITE,
    "scale_deployment": ToolPermissionTier.REVERSIBLE_WRITE,
    "rollback_deployment": ToolPermissionTier.REVERSIBLE_WRITE,
    "disable_endpoint": ToolPermissionTier.REVERSIBLE_WRITE,
    "throttle_traffic": ToolPermissionTier.REVERSIBLE_WRITE,
    # Tier 3 — high-risk write: irreversible or high blast-radius
    "run_db_migration": ToolPermissionTier.HIGH_RISK_WRITE,
    "delete_resource": ToolPermissionTier.HIGH_RISK_WRITE,
    "rotate_secret": ToolPermissionTier.HIGH_RISK_WRITE,
    "teardown_infra": ToolPermissionTier.HIGH_RISK_WRITE,
    "modify_iam_policy": ToolPermissionTier.HIGH_RISK_WRITE,
    "wipe_queue": ToolPermissionTier.HIGH_RISK_WRITE,
    "force_failover": ToolPermissionTier.HIGH_RISK_WRITE,
}

_UNKNOWN_TOOL_TIER = ToolPermissionTier.HIGH_RISK_WRITE


def run_policy_engine(
    provenance_result: ProvenanceCheckResult,
    event_id: UUID,
) -> PolicyEngineResult:
    """
    Run the Deterministic Policy Engine over the gate-approved proposals.

    Args:
        provenance_result: output of the Provenance Gate; only
            approved_proposals are evaluated here.
        event_id: incident identifier, carried through for tracing.

    Returns:
        PolicyEngineResult with per-proposal decisions and aggregate flags.
    """
    t_start = time.monotonic()
    proposals = provenance_result.approved_proposals

    log.info(
        "policy_engine.start",
        event_id=str(event_id),
        proposal_count=len(proposals),
    )

    decisions = [_decide(p) for p in proposals]

    all_approved = all(d.approved for d in decisions)
    any_requires_human = any(d.requires_human_approval for d in decisions)

    latency_ms = (time.monotonic() - t_start) * 1000

    log.info(
        "policy_engine.result",
        event_id=str(event_id),
        all_approved=all_approved,
        any_requires_human=any_requires_human,
        tier_breakdown={
            d.tool_name: d.permission_tier.value for d in decisions
        },
        latency_ms=round(latency_ms, 2),
    )

    return PolicyEngineResult(
        event_id=event_id,
        decisions=decisions,
        all_approved=all_approved,
        any_requires_human=any_requires_human,
    )


def classify_tool(tool_name: str) -> ToolPermissionTier:
    """Return the permission tier for a tool name. Unknown → HIGH_RISK_WRITE."""
    return TOOL_TIER_REGISTRY.get(tool_name, _UNKNOWN_TOOL_TIER)


def _decide(proposal: ActionProposal) -> PolicyDecision:
    """Produce a PolicyDecision for a single proposal."""
    tier = classify_tool(proposal.tool_name)
    requires_human = tier == ToolPermissionTier.HIGH_RISK_WRITE

    return PolicyDecision(
        proposal_id=proposal.proposal_id,
        tool_name=proposal.tool_name,
        permission_tier=tier,
        approved=True,           # all tiers are approved; tier drives review level
        requires_human_approval=requires_human,
        rejection_reason=None,
    )
