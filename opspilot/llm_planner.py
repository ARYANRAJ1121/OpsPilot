"""
opspilot/llm_planner.py

LLM-driven tool selection and action planning via Groq.

This module is the ONLY place where Groq influences which tools run or which
actions are proposed. It returns validated Pydantic models — the agents call
execute_tool() themselves, and every proposal still passes through the
Provenance Gate → Policy Engine → Confidence Router pipeline unchanged.

Fallback: when the LLM is disabled, unavailable, or returns unparseable
output, each function returns None and the caller uses its existing
heuristic logic.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, field_validator

from opspilot.config import get_settings
from opspilot.guardrails import check_input, check_output
from opspilot.policy_engine import TOOL_TIER_REGISTRY

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal models (not cross-boundary contracts)
# ---------------------------------------------------------------------------


class ToolSelection(BaseModel):
    """A single tool the LLM wants the Investigation Agent to call."""

    tool_name: str
    parameters: dict[str, Any]
    reason: str

    @field_validator("tool_name")
    @classmethod
    def must_be_known(cls, v: str) -> str:
        if v not in TOOL_TIER_REGISTRY:
            raise ValueError(f"unknown tool: {v}")
        return v


class ActionPlan(BaseModel):
    """A single remediation the LLM proposes for the Action Planner."""

    tool_name: str
    parameters: dict[str, Any]
    evidence_ref_ids: list[str]
    rationale: str

    @field_validator("tool_name")
    @classmethod
    def must_be_known(cls, v: str) -> str:
        if v not in TOOL_TIER_REGISTRY:
            raise ValueError(f"unknown tool: {v}")
        return v

    @field_validator("evidence_ref_ids")
    @classmethod
    def must_have_refs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("evidence_ref_ids must not be empty")
        return v


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_INVESTIGATION_SYSTEM = """\
You are an SRE investigation planner. Given an alert, select 3-7 tools to \
gather evidence. Respond ONLY with a JSON array — no markdown, no explanation.

Available tools (use only these exact names):
{tool_list}

Each element: {{"tool_name": "<name>", "parameters": {{"service": "..."}}, "reason": "..."}}
"""

_ACTION_SYSTEM = """\
You are an SRE action planner. Given a diagnosis and evidence, propose 1-3 \
remediation actions. Respond ONLY with a JSON array — no markdown.

Available tools (use only these exact names):
{tool_list}

Available evidence IDs you MUST cite:
{evidence_ids}

Each element: {{"tool_name": "<name>", "parameters": {{}}, \
"evidence_ref_ids": ["<uuid>", ...], "rationale": "..."}}

Rules:
- Each action MUST cite at least one evidence_ref_id from the list above.
- Only propose tools from the available list.
- Prefer reversible actions (restart, throttle, rollback) over destructive ones.
"""


# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------


def _call_groq(system_prompt: str, user_prompt: str) -> str | None:
    """Call Groq and return raw text, or None on any failure."""
    settings = get_settings()
    if not settings.llm_planning_active:
        return None

    if not check_input(user_prompt).allowed:
        log.warning("llm_planner.input_blocked")
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_groq import ChatGroq

        model = ChatGroq(
            model=settings.llm_planning_model,
            temperature=0.1,
            api_key=settings.groq_api_key,
        )
        response = model.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        text = (getattr(response, "content", "") or "").strip()
        if not text:
            return None
        if not check_output(text).allowed:
            log.warning("llm_planner.output_blocked")
            return None
        log.info("llm_planner.call_ok", chars=len(text))
        return text
    except Exception as exc:
        log.warning("llm_planner.call_failed", error=str(exc))
        return None


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    """Extract the first JSON array from text, tolerating markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()

    # Try to find array boundaries
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_investigation(
    alert_text: str,
    severity: str,
    service_name: str,
) -> list[ToolSelection] | None:
    """
    Ask Groq which tools to run for investigation.

    Returns a validated list of ToolSelection, or None to signal the caller
    to fall back to heuristic tool selection.
    """
    tool_list = "\n".join(f"  - {name}" for name in sorted(TOOL_TIER_REGISTRY))
    system = _INVESTIGATION_SYSTEM.format(tool_list=tool_list)
    user = (
        f"Alert (severity={severity}): {alert_text}\n"
        f"Service: {service_name}\n"
        f"Select the best tools to investigate this incident."
    )

    raw = _call_groq(system, user)
    if raw is None:
        return None

    items = _extract_json_array(raw)
    if not items:
        log.warning("llm_planner.investigation_parse_failed")
        return None

    selections: list[ToolSelection] = []
    for item in items:
        try:
            selections.append(ToolSelection(**item))
        except Exception as exc:
            log.debug("llm_planner.skip_tool", error=str(exc), item=item)

    if not selections:
        log.warning("llm_planner.no_valid_tools")
        return None

    log.info(
        "llm_planner.investigation_planned",
        tools=[s.tool_name for s in selections],
    )
    return selections


def plan_actions(
    diagnosis: str,
    confidence_score: float,
    evidence_summaries: list[dict[str, str]],
    available_evidence_ids: list[str],
) -> list[ActionPlan] | None:
    """
    Ask Groq which remediation actions to propose.

    Returns a validated list of ActionPlan, or None to signal the caller
    to fall back to heuristic proposals.
    """
    tool_list = "\n".join(f"  - {name}" for name in sorted(TOOL_TIER_REGISTRY))
    evidence_ids = "\n".join(f"  - {eid}" for eid in available_evidence_ids)
    system = _ACTION_SYSTEM.format(tool_list=tool_list, evidence_ids=evidence_ids)

    evidence_text = "\n".join(
        f"  [{e.get('id', '?')}] {e.get('summary', '')}"
        for e in evidence_summaries
    )
    user = (
        f"Diagnosis (confidence={confidence_score}):\n{diagnosis}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        f"Propose 1-3 remediation actions."
    )

    raw = _call_groq(system, user)
    if raw is None:
        return None

    items = _extract_json_array(raw)
    if not items:
        log.warning("llm_planner.action_parse_failed")
        return None

    plans: list[ActionPlan] = []
    for item in items:
        try:
            plans.append(ActionPlan(**item))
        except Exception as exc:
            log.debug("llm_planner.skip_action", error=str(exc), item=item)

    if not plans:
        log.warning("llm_planner.no_valid_actions")
        return None

    log.info(
        "llm_planner.actions_planned",
        tools=[p.tool_name for p in plans],
    )
    return plans
