"""
tests/test_policy_engine.py

Unit tests for the Deterministic Policy Engine.
All tests are pure — no LLM, no network, no filesystem.
"""

from uuid import uuid4

from opspilot.policy_engine import (
    TOOL_TIER_REGISTRY,
    classify_tool,
    run_policy_engine,
)
from opspilot.schemas import (
    ActionProposal,
    PolicyEngineResult,
    ProvenanceCheckResult,
    ToolPermissionTier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_proposal(tool_name: str) -> ActionProposal:
    return ActionProposal(
        tool_name=tool_name,
        parameters={},
        evidence_refs=[uuid4()],
        rationale="test",
    )


def make_provenance_result(proposals: list[ActionProposal]) -> ProvenanceCheckResult:
    return ProvenanceCheckResult(
        passed=bool(proposals),
        approved_proposals=proposals,
        rejected_proposals=[],
        rejection_reasons={},
    )


# ---------------------------------------------------------------------------
# classify_tool
# ---------------------------------------------------------------------------


class TestClassifyTool:
    def test_read_only_tools(self) -> None:
        for tool in ["fetch_logs", "read_metrics", "describe_service",
                     "list_pods", "get_config", "search_runbook",
                     "get_deployment_status", "query_apm"]:
            assert classify_tool(tool) == ToolPermissionTier.READ_ONLY, tool

    def test_reversible_write_tools(self) -> None:
        for tool in ["restart_service", "toggle_feature_flag", "flush_cache",
                     "scale_deployment", "rollback_deployment",
                     "disable_endpoint", "throttle_traffic"]:
            assert classify_tool(tool) == ToolPermissionTier.REVERSIBLE_WRITE, tool

    def test_high_risk_write_tools(self) -> None:
        for tool in ["run_db_migration", "delete_resource", "rotate_secret",
                     "teardown_infra", "modify_iam_policy",
                     "wipe_queue", "force_failover"]:
            assert classify_tool(tool) == ToolPermissionTier.HIGH_RISK_WRITE, tool

    def test_unknown_tool_defaults_to_high_risk(self) -> None:
        assert classify_tool("some_unknown_tool_xyz") == ToolPermissionTier.HIGH_RISK_WRITE

    def test_empty_string_defaults_to_high_risk(self) -> None:
        assert classify_tool("") == ToolPermissionTier.HIGH_RISK_WRITE


# ---------------------------------------------------------------------------
# run_policy_engine
# ---------------------------------------------------------------------------


class TestRunPolicyEngine:
    def _run(self, *tool_names: str) -> PolicyEngineResult:
        proposals = [make_proposal(t) for t in tool_names]
        provenance = make_provenance_result(proposals)
        return run_policy_engine(provenance, event_id=uuid4())

    def test_read_only_auto_approved_no_human(self) -> None:
        result = self._run("fetch_logs")
        assert result.all_approved is True
        assert result.any_requires_human is False
        d = result.decisions[0]
        assert d.permission_tier == ToolPermissionTier.READ_ONLY
        assert d.approved is True
        assert d.requires_human_approval is False
        assert d.rejection_reason is None

    def test_reversible_write_auto_approved_no_human(self) -> None:
        result = self._run("restart_service")
        assert result.all_approved is True
        assert result.any_requires_human is False
        assert result.decisions[0].permission_tier == ToolPermissionTier.REVERSIBLE_WRITE

    def test_high_risk_requires_human(self) -> None:
        result = self._run("rotate_secret")
        assert result.all_approved is True       # approved — but needs human
        assert result.any_requires_human is True
        d = result.decisions[0]
        assert d.permission_tier == ToolPermissionTier.HIGH_RISK_WRITE
        assert d.requires_human_approval is True

    def test_unknown_tool_requires_human(self) -> None:
        result = self._run("mystery_tool")
        assert result.any_requires_human is True
        assert result.decisions[0].permission_tier == ToolPermissionTier.HIGH_RISK_WRITE

    def test_mixed_tiers_any_requires_human_is_true(self) -> None:
        result = self._run("fetch_logs", "restart_service", "rotate_secret")
        assert result.all_approved is True
        assert result.any_requires_human is True
        assert len(result.decisions) == 3

    def test_all_read_only_no_human_required(self) -> None:
        result = self._run("fetch_logs", "read_metrics", "get_config")
        assert result.all_approved is True
        assert result.any_requires_human is False

    def test_empty_proposals_returns_clean_result(self) -> None:
        provenance = make_provenance_result([])
        result = run_policy_engine(provenance, event_id=uuid4())
        assert result.decisions == []
        assert result.all_approved is True   # vacuously true
        assert result.any_requires_human is False

    def test_decision_proposal_ids_match(self) -> None:
        proposals = [make_proposal("fetch_logs"), make_proposal("rotate_secret")]
        provenance = make_provenance_result(proposals)
        result = run_policy_engine(provenance, event_id=uuid4())
        result_ids = {d.proposal_id for d in result.decisions}
        proposal_ids = {p.proposal_id for p in proposals}
        assert result_ids == proposal_ids

    def test_registry_covers_all_declared_tiers(self) -> None:
        tiers_present = {tier for tier in TOOL_TIER_REGISTRY.values()}
        assert ToolPermissionTier.READ_ONLY in tiers_present
        assert ToolPermissionTier.REVERSIBLE_WRITE in tiers_present
        assert ToolPermissionTier.HIGH_RISK_WRITE in tiers_present
