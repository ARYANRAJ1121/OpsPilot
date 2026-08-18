# OpsPilot

**Agentic AI Incident-Response System** — a multi-agent pipeline that ingests alerts from Slack, support tickets, logs, and GitHub Issues, investigates them autonomously, and either executes safe remediations automatically or routes high-risk actions for human approval.

---

## Architecture

```
Slack / Support Ticket / Logs / GitHub Issues
              │
        Ingestion Agent
              │
      Router & Severity Agent
         │        │        │
    Invest-   Knowledge  Customer Comm    ← 3 parallel branches
    igation   Retrieval   Agent ──────────────────► Trace Store
     Agent     Agent
         │        │
    Evidence & Diagnosis Agent
              │
        Action Planner Agent
              │
   ┌──────────────────────────┐
   │  Deterministic           │  ← pure Python, zero LLM
   │  Provenance Gate         │
   └──────────────────────────┘
              │
   ┌──────────────────────────┐
   │  Deterministic           │  ← pure Python, zero LLM
   │  Policy Engine           │
   └──────────────────────────┘
              │
     Confidence & Risk Router
       │                 │
  Safe + high        Risky / uncertain
  confidence              │
       │            Human Approval
  Execution             │       │
   Agent           Approved  Rejected
       │               │         │
  Slack/Jira/     Execution  Revise or
  Incident Tool    Agent     Escalate
              │                  │
           Trace Store    Human Escalation
              │
    LLM Evaluation Pipeline
```

### Key constraints

| Component | Rule |
|---|---|
| Provenance Gate | Pure Python — no model call. Rejects any `ActionProposal` whose `evidence_refs` cannot be resolved to real `ToolOutput` records. Raw `event.content` is never valid evidence. |
| Policy Engine | Pure Python — no model call. Classifies every tool into one of three tiers and enforces the approval policy for each. |
| Confidence/Risk Router | Only reached **after** both gates pass — never before. |
| Customer Comm Agent | Forks directly from the Router. Runs in parallel with Investigation/Knowledge Retrieval. Never merges back into the main pipeline. |

### Policy Engine tiers

| Tier | Tools | Approval |
|---|---|---|
| Tier 1 — `read_only` | Log reads, metric fetches, config reads | Auto-approved |
| Tier 2 — `reversible_write` | Service restarts, flag changes, cache flushes | Auto / light review |
| Tier 3 — `high_risk_write` | DB migrations, infra teardown, secret rotations | Mandatory human approval |

---

## Project Structure

```
OpsPilot/
├── opspilot/
│   ├── __init__.py
│   ├── schemas.py            # All Pydantic models (agent I/O, tools, gates, traces)
│   ├── provenance_gate.py    # Deterministic Provenance Gate
│   ├── policy_engine.py      # Deterministic Policy Engine           [Module 3]
│   ├── tools/
│   │   └── simulated.py      # Simulated tool registry               [Module 4]
│   ├── agents/
│   │   ├── ingestion.py                                               [Module 5+]
│   │   ├── router.py
│   │   ├── investigation.py
│   │   ├── knowledge_retrieval.py
│   │   ├── customer_communication.py
│   │   ├── evidence_diagnosis.py
│   │   ├── action_planner.py
│   │   └── execution.py
│   └── graph.py              # LangGraph wiring                       [Module 5]
└── tests/
    ├── test_provenance_gate.py
    └── test_policy_engine.py                                          [Module 3]
```

---

## Build Status

| Module | Status |
|---|---|
| Schemas (`opspilot/schemas.py`) | ✅ Complete |
| Provenance Gate (`opspilot/provenance_gate.py`) | ✅ Complete — 11 tests passing |
| Policy Engine | 🔲 Next |
| Simulated Tools | 🔲 Pending |
| LangGraph Skeleton | 🔲 Pending |
| Agents | 🔲 Pending |
| Eval Harness | 🔲 Pending |

---

## Getting Started

**Prerequisites:** Python 3.11+

```bash
# Clone
git clone https://github.com/ARYANRAJ1121/OpsPilot.git
cd OpsPilot

# Install (with dev dependencies)
pip install -e ".[dev]"

# Run tests
py -3.11 -m pytest tests/ -v
```

Copy `.env.example` to `.env` and fill in your API keys before running any agent that calls an LLM.

---

## Design Principles

- **Deterministic safety gates first.** No LLM can approve or execute a tool action — that decision belongs to the Policy Engine alone.
- **Provenance over instruction.** An agent can only cite evidence it gathered via tools. Proposals citing raw event text are rejected at the gate, not at review time.
- **Structured logging everywhere.** Every agent boundary emits a `TraceEntry` to the Trace Store, making the full decision chain reconstructable and evaluable offline.
- **Minimal codebase.** No speculative scaffolding. Every file earns its place.
