# Architecture

OpsPilot is a LangGraph multi-agent incident-response pipeline with deterministic safety gates.

```mermaid
flowchart TD
  sources["Slack / Jira / GitHub / Tickets / Logs"] --> ingestServer["Unified FastAPI"]
  ingestServer --> lgPipeline["LangGraph pipeline"]
  lgPipeline --> ingest["Ingestion"]
  ingest --> severityRouter["Router"]
  severityRouter --> invest["Investigation"]
  severityRouter --> knowledge["Knowledge"]
  severityRouter --> customer["Customer Comm"]
  invest --> diagnosis["Evidence + Diagnosis"]
  knowledge --> diagnosis
  diagnosis --> planner["Action Planner"]
  planner --> provenance["Provenance Gate"]
  provenance --> policy["Policy Engine"]
  policy --> confidence["Confidence Router"]
  confidence -->|auto| execNode["Execution"]
  confidence -->|HITL| interrupt["Interrupt"]
  interrupt --> queue["Approval queue JSON"]
  interrupt --> ckpt["SQLite checkpointer"]
  queue --> webUI["Approvals web UI"]
  queue --> slackBtn["Slack buttons"]
  webUI --> resumeNode["Resume"]
  slackBtn --> resumeNode
  resumeNode --> execNode
  execNode --> tools["Simulated / dry-run tools"]
  lgPipeline --> traces["JSONL trace store"]
```

## Safety model

1. **Provenance Gate** — proposals must cite real tool outputs (never raw alert text).
2. **Policy Engine** — tiers 1/2/3; tier-3 always needs a human.
3. **Confidence Router** — score vs `OPSPILOT_CONFIDENCE_THRESHOLD`.
4. **HITL** — LangGraph interrupt + durable SQLite checkpoint + JSON approval queue.

## $0 remediations

Default `OPSPILOT_REMEDIATION_MODE=simulated` (or `dry_run`). Real cloud actions are intentionally out of scope; register overrides via `register_tool_override`.

## Process entrypoints

| Entry | Purpose |
|-------|---------|
| `opspilot run` | CLI one-shot incident |
| `opspilot eval` | Offline eval harness |
| `opspilot doctor` | Config health |
| `uvicorn opspilot.server:app` | Live ingest + `/approvals` |
