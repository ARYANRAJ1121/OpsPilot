"""
tests/test_llm_planner.py

Unit tests for the LLM planning module. All tests mock Groq —
no real API calls, no network, no credentials needed.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from opspilot.llm_planner import (
    ActionPlan,
    ToolSelection,
    _extract_json_array,
    plan_actions,
    plan_investigation,
)


# ---------------------------------------------------------------------------
# _extract_json_array
# ---------------------------------------------------------------------------


class TestExtractJsonArray:
    def test_plain_array(self) -> None:
        raw = '[{"tool_name": "fetch_logs"}]'
        result = _extract_json_array(raw)
        assert result == [{"tool_name": "fetch_logs"}]

    def test_markdown_fenced(self) -> None:
        raw = '```json\n[{"tool_name": "fetch_logs"}]\n```'
        result = _extract_json_array(raw)
        assert result == [{"tool_name": "fetch_logs"}]

    def test_text_before_array(self) -> None:
        raw = 'Here are the tools:\n[{"tool_name": "fetch_logs"}]'
        result = _extract_json_array(raw)
        assert result == [{"tool_name": "fetch_logs"}]

    def test_invalid_json_returns_none(self) -> None:
        assert _extract_json_array("not json at all") is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_json_array("") is None

    def test_object_not_array_returns_none(self) -> None:
        assert _extract_json_array('{"key": "value"}') is None


# ---------------------------------------------------------------------------
# ToolSelection validation
# ---------------------------------------------------------------------------


class TestToolSelectionModel:
    def test_valid_tool(self) -> None:
        sel = ToolSelection(
            tool_name="fetch_logs",
            parameters={"service": "api"},
            reason="check logs",
        )
        assert sel.tool_name == "fetch_logs"

    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown tool"):
            ToolSelection(
                tool_name="nonexistent_tool_xyz",
                parameters={},
                reason="test",
            )


# ---------------------------------------------------------------------------
# ActionPlan validation
# ---------------------------------------------------------------------------


class TestActionPlanModel:
    def test_valid_plan(self) -> None:
        plan = ActionPlan(
            tool_name="restart_service",
            parameters={"service": "api"},
            evidence_ref_ids=["some-uuid"],
            rationale="restart crashed pods",
        )
        assert plan.tool_name == "restart_service"

    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown tool"):
            ActionPlan(
                tool_name="nonexistent_xyz",
                parameters={},
                evidence_ref_ids=["uuid1"],
                rationale="test",
            )

    def test_empty_evidence_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            ActionPlan(
                tool_name="restart_service",
                parameters={},
                evidence_ref_ids=[],
                rationale="test",
            )


# ---------------------------------------------------------------------------
# plan_investigation (mocked LLM)
# ---------------------------------------------------------------------------


def _mock_settings(planning_active: bool = False):
    """Return a mock Settings with llm_planning_active controlled."""
    s = MagicMock()
    s.llm_planning_active = planning_active
    s.llm_active = planning_active
    s.llm_planning = planning_active
    s.groq_api_key = "fake-key" if planning_active else None
    s.llm_planning_model = "llama-3.3-70b-versatile"
    s.guardrails_enabled = False
    return s


class TestPlanInvestigation:
    def test_returns_none_when_llm_disabled(self) -> None:
        with patch("opspilot.llm_planner.get_settings", return_value=_mock_settings(False)):
            result = plan_investigation("alert", "high", "api-service")
        assert result is None

    @patch("opspilot.llm_planner._call_groq")
    def test_valid_response_returns_selections(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps([
            {"tool_name": "fetch_logs", "parameters": {"service": "api"}, "reason": "check logs"},
            {"tool_name": "read_metrics", "parameters": {"service": "api"}, "reason": "check metrics"},
        ])
        result = plan_investigation("alert", "high", "api-service")
        assert result is not None
        assert len(result) == 2
        assert result[0].tool_name == "fetch_logs"
        assert result[1].tool_name == "read_metrics"

    @patch("opspilot.llm_planner._call_groq")
    def test_unknown_tools_are_stripped(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps([
            {"tool_name": "fetch_logs", "parameters": {}, "reason": "ok"},
            {"tool_name": "FAKE_TOOL", "parameters": {}, "reason": "bad"},
        ])
        result = plan_investigation("alert", "high", "api-service")
        assert result is not None
        assert len(result) == 1
        assert result[0].tool_name == "fetch_logs"

    @patch("opspilot.llm_planner._call_groq")
    def test_all_invalid_returns_none(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps([
            {"tool_name": "FAKE1", "parameters": {}, "reason": "bad"},
        ])
        result = plan_investigation("alert", "high", "api-service")
        assert result is None

    @patch("opspilot.llm_planner._call_groq")
    def test_unparseable_json_returns_none(self, mock_call: MagicMock) -> None:
        mock_call.return_value = "Sure! Here are my recommendations..."
        result = plan_investigation("alert", "high", "api-service")
        assert result is None

    @patch("opspilot.llm_planner._call_groq")
    def test_none_response_returns_none(self, mock_call: MagicMock) -> None:
        mock_call.return_value = None
        result = plan_investigation("alert", "high", "api-service")
        assert result is None


# ---------------------------------------------------------------------------
# plan_actions (mocked LLM)
# ---------------------------------------------------------------------------


class TestPlanActions:
    def test_returns_none_when_llm_disabled(self) -> None:
        with patch("opspilot.llm_planner.get_settings", return_value=_mock_settings(False)):
            result = plan_actions("diag", 0.8, [], [])
        assert result is None

    @patch("opspilot.llm_planner._call_groq")
    def test_valid_response_returns_plans(self, mock_call: MagicMock) -> None:
        eid = "aaaaaaaa-1111-2222-3333-444444444444"
        mock_call.return_value = json.dumps([
            {
                "tool_name": "restart_service",
                "parameters": {"service": "api"},
                "evidence_ref_ids": [eid],
                "rationale": "restart crashed pods",
            },
        ])
        result = plan_actions("diag", 0.8, [], [eid])
        assert result is not None
        assert len(result) == 1
        assert result[0].tool_name == "restart_service"
        assert result[0].evidence_ref_ids == [eid]

    @patch("opspilot.llm_planner._call_groq")
    def test_empty_evidence_stripped(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps([
            {
                "tool_name": "restart_service",
                "parameters": {},
                "evidence_ref_ids": [],
                "rationale": "no evidence",
            },
        ])
        result = plan_actions("diag", 0.8, [], [])
        assert result is None  # all plans invalid → None

    @patch("opspilot.llm_planner._call_groq")
    def test_markdown_fenced_response(self, mock_call: MagicMock) -> None:
        eid = "bbbbbbbb-1111-2222-3333-444444444444"
        mock_call.return_value = (
            "```json\n"
            + json.dumps([
                {
                    "tool_name": "throttle_traffic",
                    "parameters": {"rate_pct": 50},
                    "evidence_ref_ids": [eid],
                    "rationale": "reduce load",
                },
            ])
            + "\n```"
        )
        result = plan_actions("diag", 0.8, [], [eid])
        assert result is not None
        assert result[0].tool_name == "throttle_traffic"
