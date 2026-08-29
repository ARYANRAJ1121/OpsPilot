"""Execution Agent — run gate-approved proposals through the tool registry."""

from __future__ import annotations

from uuid import UUID

from opspilot.schemas import ActionProposal, ExecutionResult
from opspilot.tools.executor import execute_tool


def run_execution(event_id: UUID, proposals: list[ActionProposal]) -> ExecutionResult:
    executed = []
    failures: list[str] = []

    for proposal in proposals:
        try:
            executed.append(execute_tool(proposal.tool_name, proposal.parameters))
        except KeyError as exc:
            failures.append(str(exc))

    names = ", ".join(t.tool_name for t in executed) or "none"
    success = not failures
    summary = f"Executed {len(executed)} tool(s): {names}"
    if failures:
        summary += f". Failures: {'; '.join(failures)}"

    return ExecutionResult(
        event_id=event_id,
        executed_tool_outputs=executed,
        success=success,
        summary=summary,
    )
