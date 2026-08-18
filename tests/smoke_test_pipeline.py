from uuid import uuid4
from opspilot.schemas import (
    IncidentEvent, IncidentSource, IngestionOutput, RouterOutput,
    Severity, ActionProposal, ActionPlannerOutput,
)
from opspilot.tools.simulated import execute_tool
from opspilot.provenance_gate import check_provenance
from opspilot.policy_engine import run_policy_engine, classify_tool

print("=" * 60)
print("OPSPILOT END-TO-END PIPELINE SMOKE TEST")
print("=" * 60)

# Step 1: Raw alert
event = IncidentEvent(
    source=IncidentSource.SLACK,
    content="ALERT: api-service error rate 18% — p99 latency 4200ms"
)
print(f"\n[1] Incident received   event_id={event.event_id}")

# Step 2: Ingestion
ingestion = IngestionOutput(
    event_id=event.event_id,
    source=event.source,
    normalized_title="API service degraded — high error rate",
    normalized_body=event.content,
    received_at=event.received_at
)
print(f"[2] Ingestion done      title=\"{ingestion.normalized_title}\"")

# Step 3: Router
router = RouterOutput(
    event_id=event.event_id,
    severity=Severity.HIGH,
    incident_type="service_degradation",
    routing_notes="Error rate exceeds 15% threshold"
)
print(f"[3] Router done         severity={router.severity.value}")

# Step 4: Investigation tools
to1 = execute_tool("fetch_logs",   {"service": "api-service"})
to2 = execute_tool("read_metrics", {"service": "api-service"})
to3 = execute_tool("list_pods",    {"namespace": "production"})
tool_outputs = [to1, to2, to3]
print(f"[4] Investigation done  tool_outputs={len(tool_outputs)}")
print(f"    fetch_logs errors_last_5m : {to1.result['total_errors_last_5m']}")
print(f"    read_metrics error_rate   : {to2.result['error_rate_pct']}%")
crash_count = sum(1 for p in to3.result["pods"] if p["status"] == "CrashLoopBackOff")
print(f"    list_pods crash_pods      : {crash_count}")

# Step 5: Action proposals
proposal_safe = ActionProposal(
    tool_name="restart_service",
    parameters={"service": "api-service", "target": "crashed-pods"},
    evidence_refs=[to2.tool_output_id, to3.tool_output_id],
    rationale="Metrics show 18% error rate; pod list confirms CrashLoopBackOff"
)
proposal_risky = ActionProposal(
    tool_name="run_db_migration",
    parameters={"migration_id": "M042"},
    evidence_refs=[to1.tool_output_id],
    rationale="Logs suggest schema mismatch"
)
proposal_bad = ActionProposal(
    tool_name="restart_service",
    parameters={"service": "api-service"},
    evidence_refs=[uuid4()],  # fake UUID — provenance gate must reject this
    rationale="Cited a non-existent tool output"
)
planner_out = ActionPlannerOutput(
    event_id=event.event_id,
    proposals=[proposal_safe, proposal_risky, proposal_bad]
)
print(f"[5] Action Planner done proposals={len(planner_out.proposals)}")

# Step 6: Provenance Gate
prov = check_provenance(planner_out, available_tool_outputs=tool_outputs)
print(f"\n[6] Provenance Gate")
print(f"    passed   : {prov.passed}")
print(f"    approved : {len(prov.approved_proposals)} proposals")
print(f"    rejected : {len(prov.rejected_proposals)} proposals")
for pid, reason in prov.rejection_reasons.items():
    print(f"    reason   : {reason[:90]}")

# Step 7: Policy Engine
policy = run_policy_engine(prov, event_id=event.event_id)
print(f"\n[7] Policy Engine")
for d in policy.decisions:
    tier = classify_tool(d.tool_name)
    human = "NEEDS HUMAN APPROVAL" if d.requires_human_approval else "auto-approved"
    print(f"    {d.tool_name:<25} tier={tier.value:<22} {human}")
print(f"    any_requires_human : {policy.any_requires_human}")

# Assertions
assert prov.passed
assert len(prov.approved_proposals) == 2
assert len(prov.rejected_proposals) == 1
assert policy.any_requires_human is True
safe_decision = next(d for d in policy.decisions if d.tool_name == "restart_service")
assert safe_decision.requires_human_approval is False

print("\n" + "=" * 60)
print("ALL ASSERTIONS PASSED — pipeline integrity confirmed")
print("=" * 60)
