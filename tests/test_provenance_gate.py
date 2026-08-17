"""
tests/test_provenance_gate.py

Unit tests for the Deterministic Provenance Gate.
All tests are pure — no LLM, no network, no filesystem.
"""

from uuid import uuid4

import pytest

from opspilot.provenance_gate import _reject_reason, check_provenance
from opspilot.schemas import (
    ActionProposal,
    ActionPlannerOutput,
    ToolOutput,
)


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def make_tool_output(**kwargs) -> ToolOutput:
    return ToolOutput(
        tool_name=kwargs.get("tool_name", "read_logs"),
        parameters=kwargs.get("parameters", {}),
        result=kwargs.get("result", {"status": "ok"}),
    )


def make_proposal(evidence_refs: list, **kwargs) -> ActionProposal:
    return ActionProposal(
        tool_name=kwargs.get("tool_name", "restart_service"),
        parameters=kwargs.get("parameters", {}),
        evidence_refs=evidence_refs,
        rationale=kwargs.get("rationale", "evidence supports restart"),
    )


# ---------------------------------------------------------------------------
# _reject_reason unit tests (pure logic, no I/O)
# ---------------------------------------------------------------------------


class TestRejectReason:
    def test_passes_with_valid_refs(self) -> None:
        to = make_tool_output()
        proposal = make_proposal(evidence_refs=[to.tool_output_id])
        assert _reject_reason(proposal, {to.tool_output_id}) is None

    def test_rejects_empty_evidence_refs(self) -> None:
        proposal = make_proposal(evidence_refs=[])
        reason = _reject_reason(proposal, {uuid4()})
        assert reason is not None
        assert "no evidence_refs" in reason

    def test_rejects_unknown_ref(self) -> None:
        unknown = uuid4()
        proposal = make_proposal(evidence_refs=[unknown])
        reason = _reject_reason(proposal, set())
        assert reason is not None
        assert str(unknown) in reason

    def test_rejects_partial_unknown_refs(self) -> None:
        known = uuid4()
        unknown = uuid4()
        proposal = make_proposal(evidence_refs=[known, unknown])
        reason = _reject_reason(proposal, {known})
        assert reason is not None
        assert str(unknown) in reason
        assert str(known) not in reason

    def test_passes_multiple_valid_refs(self) -> None:
        ids = [uuid4() for _ in range(3)]
        proposal = make_proposal(evidence_refs=ids)
        assert _reject_reason(proposal, set(ids)) is None


# ---------------------------------------------------------------------------
# check_provenance integration tests
# ---------------------------------------------------------------------------


class TestCheckProvenance:
    def _planner_output(self, proposals: list[ActionProposal], event_id=None):
        return ActionPlannerOutput(
            event_id=event_id or uuid4(),
            proposals=proposals,
        )

    def test_all_approved(self) -> None:
        to = make_tool_output()
        proposal = make_proposal(evidence_refs=[to.tool_output_id])
        result = check_provenance(
            self._planner_output([proposal]),
            available_tool_outputs=[to],
        )
        assert result.passed is True
        assert len(result.approved_proposals) == 1
        assert len(result.rejected_proposals) == 0
        assert result.rejection_reasons == {}

    def test_all_rejected_empty_refs(self) -> None:
        proposal = make_proposal(evidence_refs=[])
        result = check_provenance(
            self._planner_output([proposal]),
            available_tool_outputs=[make_tool_output()],
        )
        assert result.passed is False
        assert len(result.approved_proposals) == 0
        assert len(result.rejected_proposals) == 1
        assert str(proposal.proposal_id) in result.rejection_reasons

    def test_all_rejected_unknown_refs(self) -> None:
        proposal = make_proposal(evidence_refs=[uuid4()])
        result = check_provenance(
            self._planner_output([proposal]),
            available_tool_outputs=[],
        )
        assert result.passed is False
        assert len(result.rejected_proposals) == 1

    def test_mixed_approved_and_rejected(self) -> None:
        to = make_tool_output()
        good = make_proposal(evidence_refs=[to.tool_output_id])
        bad = make_proposal(evidence_refs=[uuid4()])
        result = check_provenance(
            self._planner_output([good, bad]),
            available_tool_outputs=[to],
        )
        assert result.passed is True
        assert len(result.approved_proposals) == 1
        assert len(result.rejected_proposals) == 1
        assert result.approved_proposals[0].proposal_id == good.proposal_id
        assert str(bad.proposal_id) in result.rejection_reasons

    def test_empty_proposals_list(self) -> None:
        result = check_provenance(
            self._planner_output([]),
            available_tool_outputs=[make_tool_output()],
        )
        assert result.passed is False
        assert result.approved_proposals == []
        assert result.rejected_proposals == []

    def test_rejection_reason_keys_are_strings(self) -> None:
        proposal = make_proposal(evidence_refs=[uuid4()])
        result = check_provenance(
            self._planner_output([proposal]),
            available_tool_outputs=[],
        )
        for key in result.rejection_reasons:
            assert isinstance(key, str), "rejection_reasons keys must be str, not UUID"
