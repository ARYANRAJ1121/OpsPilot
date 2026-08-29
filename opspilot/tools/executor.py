"""
Remediation tool executor.

$0 / free mode uses simulated (or dry-run) implementations only.
Real cloud remediations are intentionally out of scope; plug them in via
``register_tool_override`` when you are ready to leave free tier.
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from opspilot.config import get_settings
from opspilot.schemas import ToolOutput
from opspilot.tools import simulated

log = structlog.get_logger(__name__)

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]

_OVERRIDES: dict[str, ToolFn] = {}


def register_tool_override(tool_name: str, fn: ToolFn) -> None:
    """Register a real (or custom) tool implementation by name."""
    _OVERRIDES[tool_name] = fn
    log.info("executor.override_registered", tool_name=tool_name)


def clear_tool_overrides() -> None:
    _OVERRIDES.clear()


def execute_tool(tool_name: str, parameters: dict[str, Any]) -> ToolOutput:
    """
    Execute a tool under the configured remediation mode.

    Modes:
      simulated — fake deterministic results (default, $0)
      dry_run   — same as simulated, result marked dry_run=True
    """
    settings = get_settings()
    mode = settings.remediation_mode

    if tool_name in _OVERRIDES:
        log.info("tool.execute", tool_name=tool_name, mode="override", parameters=parameters)
        result = _OVERRIDES[tool_name](parameters)
        return ToolOutput(tool_name=tool_name, parameters=parameters, result=result)

    if tool_name not in simulated.SIMULATED_TOOLS:
        raise KeyError(
            f"Unknown tool '{tool_name}'. "
            f"Available: {sorted(simulated.SIMULATED_TOOLS)} "
            f"(or register_tool_override)"
        )

    log.info("tool.execute", tool_name=tool_name, mode=mode, parameters=parameters)
    result = dict(simulated.SIMULATED_TOOLS[tool_name](parameters))
    if mode == "dry_run":
        result = {**result, "dry_run": True, "would_execute": True}
    log.info("tool.result", tool_name=tool_name, mode=mode)
    return ToolOutput(tool_name=tool_name, parameters=parameters, result=result)
