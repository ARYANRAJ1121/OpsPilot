"""
OpsPilot CLI — run incidents end-to-end from the terminal.

Examples:
    opspilot run "ALERT: api-service error rate 18%"
    opspilot run --source logs --file alert.txt
    opspilot eval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from opspilot.eval_harness import run_eval_suite
from opspilot.graph import resume_incident, run_incident
from opspilot.schemas import HumanApprovalDecision, IncidentEvent, IncidentSource


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opspilot",
        description="OpsPilot — provenance-aware multi-agent incident response",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run one incident through the full pipeline")
    run_p.add_argument("alert", nargs="?", help="Alert text (or use --file)")
    run_p.add_argument("--file", "-f", type=Path, help="Read alert content from a text file")
    run_p.add_argument(
        "--source",
        choices=[s.value for s in IncidentSource],
        default=IncidentSource.SLACK.value,
        help="Incident source channel (default: slack)",
    )
    run_p.add_argument(
        "--approve",
        action="store_true",
        help="Auto-approve if the pipeline pauses for human review",
    )
    run_p.add_argument(
        "--reject",
        action="store_true",
        help="Auto-reject if the pipeline pauses for human review",
    )
    run_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print final state summary as JSON",
    )
    run_p.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write traces to disk",
    )

    eval_p = sub.add_parser("eval", help="Run the offline evaluation harness")
    eval_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print eval report as JSON",
    )

    sub.add_parser("doctor", help="Check free Slack + Groq configuration")
    sub.add_parser(
        "smoke-slack",
        help="Local SlackAdapter smoke test (no Slack network)",
    )
    sub.add_parser(
        "smoke-webhooks",
        help="Offline Jira/GitHub/tickets/logs adapter smoke (mocked graph)",
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "eval":
        return _cmd_eval(args)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "smoke-slack":
        return _cmd_smoke_slack()
    if args.command == "smoke-webhooks":
        return _cmd_smoke_webhooks()
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    content = _resolve_alert(args)
    if not content:
        print("error: provide alert text or --file", file=sys.stderr)
        return 2

    event = IncidentEvent(source=IncidentSource(args.source), content=content)
    print(f"> Running incident {event.event_id}")
    print(f"  source={event.source.value}")
    print(f"  alert={content[:120]}{'...' if len(content) > 120 else ''}")
    print()

    state = run_incident(event, persist=not args.no_persist)
    state = _maybe_handle_approval(state, args)

    _print_summary(state)
    if args.as_json:
        print(json.dumps(_jsonable_summary(state), indent=2, default=str))
    return 0 if _succeeded(state) else 1


def _cmd_eval(args: argparse.Namespace) -> int:
    report = run_eval_suite()
    if args.as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Eval: {report['passed']}/{report['total']} scenarios passed")
        for row in report["results"]:
            mark = "PASS" if row["ok"] else "FAIL"
            print(f"  [{mark}] {row['name']}: {row['detail']}")
    return 0 if report["failed"] == 0 else 1


def _cmd_doctor() -> int:
    from opspilot import __version__
    from opspilot.config import get_settings

    s = get_settings()
    problems: list[str] = []
    print(f"OpsPilot doctor v{__version__} (free Slack + Groq + webhooks)")
    print(f"  groq_key_set:        {bool(s.groq_api_key)}")
    print(f"  llm_enabled:         {s.llm_enabled}")
    print(f"  llm_active:          {s.llm_active}")
    print(f"  llm_model:           {s.llm_model}")
    print(f"  llm_planning:        {s.llm_planning}")
    print(f"  llm_planning_active: {s.llm_planning_active}")
    print(f"  guardrails_enabled:  {s.guardrails_enabled}")
    print(f"  guardrails_llm:      {s.guardrails_llm}")
    print(f"  slack_bot_token_set: {bool(s.slack_bot_token)}")
    print(f"  slack_signing_set:   {bool(s.slack_signing_secret)}")
    print(f"  slack_configured:    {s.slack_configured}")
    print(f"  allowed_channels:    {s.slack_allowed_channels or '(all)'}")
    print(f"  jira_secret_set:     {bool(s.jira_webhook_secret)}")
    print(f"  github_secret_set:   {bool(s.github_webhook_secret)}")
    print(f"  tickets_secret_set:  {bool(s.tickets_webhook_secret)}")
    print(f"  logs_secret_set:     {bool(s.logs_webhook_secret)}")
    print(f"  require_signatures:  {s.webhook_require_signatures}")
    print(f"  approval_token_set:  {bool(s.approval_api_token)}")
    print(f"  checkpoint_backend:  {s.checkpoint_backend}")
    print(f"  checkpoint_path:     {s.checkpoint_path}")
    print(f"  approval_queue:      {s.approval_queue_path}")
    print(f"  remediation_mode:    {s.remediation_mode}")
    print(f"  trace_dir:           {s.trace_dir}")
    print()
    if not s.llm_active:
        print("  tip: set GROQ_API_KEY for free narrative enrichment")
    if not s.slack_configured:
        print("  tip: set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET for live Slack")
    else:
        print("  Slack env looks ready")
    if not s.webhook_require_signatures:
        print("  warn: OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=false")
        print("        OK for local-only; enable before public tunnels")
    if s.webhook_require_signatures:
        missing = [
            name
            for name, val in (
                ("JIRA_WEBHOOK_SECRET", s.jira_webhook_secret),
                ("GITHUB_WEBHOOK_SECRET", s.github_webhook_secret),
                ("TICKETS_WEBHOOK_SECRET", s.tickets_webhook_secret),
                ("LOGS_WEBHOOK_SECRET", s.logs_webhook_secret),
            )
            if not val
        ]
        if missing:
            print(f"  tip: missing webhook secrets while require_signatures=true: {', '.join(missing)}")
            print("       set secrets, or set OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=false for local unsigned smoke")
            # Not a hard failure — unused integrations may omit secrets.
    if not s.approval_api_token:
        print("  warn: OPSPILOT_APPROVAL_API_TOKEN unset — /approvals is open")
        print("        set a token before exposing the server on a public URL")
    if s.remediation_mode not in {"simulated", "dry_run"}:
        problems.append(f"unknown remediation_mode={s.remediation_mode!r}")
    if s.checkpoint_backend not in {"sqlite", "memory"}:
        problems.append(f"unknown checkpoint_backend={s.checkpoint_backend!r}")
    print("  unified server: uvicorn opspilot.server:app --host 0.0.0.0 --port 8000")
    print("  approvals UI:   http://127.0.0.1:8000/approvals")
    print("  guide: docs/FREE_SLACK_GROQ.md")
    for p in problems:
        print(f"  error: {p}")
    return 1 if problems else 0


def _cmd_smoke_slack() -> int:
    from opspilot.integrations.slack.smoke import main as smoke_main

    return smoke_main()


def _cmd_smoke_webhooks() -> int:
    from opspilot.smoke_webhooks import main as smoke_main

    return smoke_main()


def _resolve_alert(args: argparse.Namespace) -> str:
    if args.file is not None:
        return Path(args.file).read_text(encoding="utf-8").strip()
    return (args.alert or "").strip()


def _maybe_handle_approval(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if "__interrupt__" not in state:
        return state

    interrupt = state["__interrupt__"][0]
    payload = interrupt.value if hasattr(interrupt, "value") else interrupt
    proposals = payload.get("proposals") or []
    context = payload.get("context_summary") or ""
    request = payload.get("request") or {}
    request_id = request.get("request_id")

    print("PAUSE: Human approval required")
    print(f"  context: {context[:200]}{'...' if len(context) > 200 else ''}")
    for i, p in enumerate(proposals, 1):
        print(f"  [{i}] {p.get('tool_name')} {p.get('parameters')}")
        print(f"      rationale: {(p.get('rationale') or '')[:160]}")
    print()

    if args.approve and args.reject:
        print("error: use only one of --approve / --reject", file=sys.stderr)
        sys.exit(2)

    if args.approve:
        decision = HumanApprovalDecision.APPROVED
        reviewer = "cli-auto-approve"
        notes = "Auto-approved via --approve"
    elif args.reject:
        decision = HumanApprovalDecision.REJECTED
        reviewer = "cli-auto-reject"
        notes = "Auto-rejected via --reject"
    elif sys.stdin.isatty():
        choice = input("Approve proposals? [y/N]: ").strip().lower()
        if choice in {"y", "yes"}:
            decision = HumanApprovalDecision.APPROVED
            notes = "Approved via interactive CLI"
        else:
            decision = HumanApprovalDecision.REJECTED
            notes = "Rejected via interactive CLI"
        reviewer = "cli-operator"
    else:
        print("error: non-interactive stdin; pass --approve or --reject", file=sys.stderr)
        sys.exit(2)

    print(f"-> Resuming with decision={decision.value}")
    return resume_incident(
        state["thread_id"],
        {
            "request_id": request_id,
            "decision": decision.value,
            "reviewer_id": reviewer,
            "notes": notes,
        },
        persist=not args.no_persist,
    )


def _print_summary(state: dict[str, Any]) -> None:
    routing = state.get("routing")
    print("-- Result --")
    if routing is not None:
        print(f"  routing: {routing.routing_decision.value}")
        print(f"  confidence: {routing.confidence_score}")
    if state.get("execution") is not None:
        ex = state["execution"]
        print(f"  execution: success={ex.success} -- {ex.summary}")
    if state.get("escalation") is not None:
        print(f"  escalation: {state['escalation'].reason}")
    if state.get("customer_comm") is not None:
        print(f"  customer_comm: {state['customer_comm'].message_draft[:120]}")
    if state.get("trace_path"):
        print(f"  traces: {state['trace_path']}")
    print()


def _jsonable_summary(state: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"thread_id": state.get("thread_id")}
    for key in (
        "routing",
        "execution",
        "escalation",
        "provenance",
        "policy",
        "diagnosis",
        "customer_comm",
    ):
        val = state.get(key)
        if val is not None and hasattr(val, "model_dump"):
            out[key] = val.model_dump(mode="json")
    if state.get("trace_path"):
        out["trace_path"] = state["trace_path"]
    return out


def _succeeded(state: dict[str, Any]) -> bool:
    if state.get("execution") is not None:
        return bool(state["execution"].success)
    return state.get("escalation") is not None and "__interrupt__" not in state


if __name__ == "__main__":
    raise SystemExit(main())
