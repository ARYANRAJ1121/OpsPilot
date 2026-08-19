"""Unit tests for the Deterministic Confidence & Risk Router."""

from uuid import uuid4

from opspilot.confidence_router import (
    CONFIDENCE_AUTO_EXECUTE_THRESHOLD,
    run_confidence_router,
)
from opspilot.schemas import (
    ActionProposal,
    PolicyDecision,
    PolicyEngineResult,
    ProvenanceCheckResult,
    RoutingDecision,
    ToolPermissionTier,
)


def _proposal() -> ActionProposal:
    return ActionProposal(
        tool_name="restart_service",
        parameters={},
        evidence_refs=[uuid4()],
        rationale="test",
    )


def _provenance(passed: bool, proposals: list[ActionProposal] | None = None) -> ProvenanceCheckResult:
    approved = proposals if passed else []
    return ProvenanceCheckResult(
        passed=passed,
        approved_proposals=approved or ([_proposal()] if passed else []),
        rejected_proposals=[],
        rejection_reasons={},
    )


def _policy(*, requires_human: bool) -> PolicyEngineResult:
    proposal = _proposal()
    return PolicyEngineResult(
        event_id=uuid4(),
        decisions=[
            PolicyDecision(
                proposal_id=proposal.proposal_id,
                tool_name=proposal.tool_name,
                permission_tier=(
                    ToolPermissionTier.HIGH_RISK_WRITE
                    if requires_human
                    else ToolPermissionTier.REVERSIBLE_WRITE
                ),
                approved=True,
                requires_human_approval=requires_human,
            )
        ],
        all_approved=True,
        any_requires_human=requires_human,
    )


class TestConfidenceRouter:
    def test_auto_execute_when_safe_and_confident(self) -> None:
        result = run_confidence_router(
            event_id=uuid4(),
            confidence_score=0.9,
            provenance_result=_provenance(True),
            policy_result=_policy(requires_human=False),
        )
        assert result.routing_decision is RoutingDecision.AUTO_EXECUTE

    def test_human_when_tier_three(self) -> None:
        result = run_confidence_router(
            event_id=uuid4(),
            confidence_score=0.99,
            provenance_result=_provenance(True),
            policy_result=_policy(requires_human=True),
        )
        assert result.routing_decision is RoutingDecision.REQUIRE_HUMAN_APPROVAL

    def test_human_when_low_confidence(self) -> None:
        result = run_confidence_router(
            event_id=uuid4(),
            confidence_score=CONFIDENCE_AUTO_EXECUTE_THRESHOLD - 0.01,
            provenance_result=_provenance(True),
            policy_result=_policy(requires_human=False),
        )
        assert result.routing_decision is RoutingDecision.REQUIRE_HUMAN_APPROVAL

    def test_escalate_when_provenance_fails(self) -> None:
        result = run_confidence_router(
            event_id=uuid4(),
            confidence_score=0.99,
            provenance_result=_provenance(False),
            policy_result=_policy(requires_human=False),
        )
        assert result.routing_decision is RoutingDecision.ESCALATE
