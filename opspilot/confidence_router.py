"""
opspilot/confidence_router.py

Deterministic Confidence & Risk Router — pure Python, zero LLM calls.

Reached only after Provenance Gate + Policy Engine. Decides whether
approved proposals may auto-execute, need a human, or must escalate.
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog

from opspilot.schemas import (
    ConfidenceRiskRouterOutput,
    PolicyEngineResult,
    ProvenanceCheckResult,
    RoutingDecision,
)

log = structlog.get_logger(__name__)

CONFIDENCE_AUTO_EXECUTE_THRESHOLD = 0.7


def run_confidence_router(
    event_id: UUID,
    confidence_score: float,
    provenance_result: ProvenanceCheckResult,
    policy_result: PolicyEngineResult,
) -> ConfidenceRiskRouterOutput:
    t_start = time.monotonic()
    decision = _decide(confidence_score, provenance_result, policy_result)

    log.info(
        "confidence_router.result",
        event_id=str(event_id),
        routing_decision=decision.value,
        confidence_score=confidence_score,
        provenance_passed=provenance_result.passed,
        any_requires_human=policy_result.any_requires_human,
        latency_ms=round((time.monotonic() - t_start) * 1000, 2),
    )

    return ConfidenceRiskRouterOutput(
        event_id=event_id,
        confidence_score=confidence_score,
        routing_decision=decision,
        approved_proposals=provenance_result.approved_proposals,
        policy_result=policy_result,
    )


def _decide(
    confidence_score: float,
    provenance_result: ProvenanceCheckResult,
    policy_result: PolicyEngineResult,
) -> RoutingDecision:
    if not provenance_result.passed:
        return RoutingDecision.ESCALATE
    if policy_result.any_requires_human:
        return RoutingDecision.REQUIRE_HUMAN_APPROVAL
    if confidence_score < CONFIDENCE_AUTO_EXECUTE_THRESHOLD:
        return RoutingDecision.REQUIRE_HUMAN_APPROVAL
    return RoutingDecision.AUTO_EXECUTE
