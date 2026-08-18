<div align="center">

# 🚨 OpsPilot

### Multi-Agent Agentic AI Incident-Response System

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/built%20with-LangGraph-blueviolet)](https://github.com/langchain-ai/langgraph)
[![Pydantic v2](https://img.shields.io/badge/schema-Pydantic%20v2-e92063)](https://docs.pydantic.dev/)
[![Tests](https://img.shields.io/badge/tests-11%20passing-brightgreen)](./tests/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](./LICENSE)

*From raw alert to executed remediation — autonomously, safely, with a human in the loop exactly where it matters.*

</div>

---

## What Is OpsPilot?

OpsPilot is a production-oriented **multi-agent incident-response system** built on LangGraph. It ingests signals from Slack, support tickets, log pipelines, and GitHub Issues, investigates them in parallel using specialised agents, then either auto-executes safe remediations or routes high-risk actions to a human reviewer — all with full trace observability.

**The hard engineering constraint that makes it trustworthy:** no LLM agent can approve or execute a tool action. That decision belongs exclusively to two deterministic, pure-Python gates that sit between the planner and the executor.

---

## Core Design Principles

| Principle | Implementation |
|---|---|
| **Provenance before action** | Every proposed action must cite tool-output evidence IDs. Proposals citing raw event text are rejected at the Provenance Gate — not at review time. |
| **Policy owns permissions** | The deterministic Policy Engine classifies every tool into a risk tier and enforces approval rules. No LLM can bypass or override this. |
| **Parallel, non-blocking comms** | The Customer Communication Agent forks at the Router and fires stakeholder updates while investigation is still running — it never waits on evidence collection. |
| **Full trace observability** | Every agent boundary emits a structured `TraceEntry`. The full decision chain is reconstructable and fed into an offline LLM evaluation pipeline. |
| **Minimal surface area** | No speculative abstraction. Every file and every function earns its place. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Slack · Support Tickets · Logs · GitHub Issues  │
└────────────────────────┬────────────────────────────────┘
                         │
                 ┌───────▼────────┐
                 │ Ingestion Agent │   normalise & deduplicate
                 └───────┬────────┘
                         │
              ┌──────────▼───────────┐
              │ Router & Severity    │   classify · route · triage
              └──┬──────────┬────┬──┘
                 │          │    │
        ┌────────▼──┐  ┌────▼──┐ └──────────────────────┐
        │Investig-  │  │Know-  │              ┌──────────▼──────────┐
        │ation      │  │ledge  │              │Customer Comm Agent  │
        │Agent      │  │Retrie-│              │                     │
        └────┬──────┘  │val    │              │ Sends stakeholder   │
             │         │Agent  │              │ updates using only  │
             │         └───┬───┘              │ severity/triage     │
             └──────┬──────┘                  │ data, in parallel   │
                    │                         └──────────┬──────────┘
        ┌───────────▼────────────┐                       │
        │ Evidence & Diagnosis   │                 Trace Store ◄──┘
        │ Agent                  │           ("Communication logged")
        └───────────┬────────────┘
                    │
           ┌────────▼─────────┐
           │ Action Planner   │   proposes actions w/ tool_output_id citations
           └────────┬─────────┘
                    │
        ╔═══════════▼══════════╗
        ║  PROVENANCE GATE     ║  ◄── Pure Python · Zero LLM
        ║                      ║
        ║  ✓ evidence_refs     ║
        ║    must resolve to   ║
        ║    real ToolOutputs  ║
        ║  ✗ raw event.content ║
        ║    rejected outright ║
        ╚═══════════╤══════════╝
                    │
        ╔═══════════▼══════════╗
        ║  POLICY ENGINE       ║  ◄── Pure Python · Zero LLM
        ║                      ║
        ║  Tier 1 read-only    ║──► auto-approve
        ║  Tier 2 rev.-write   ║──► auto / light review
        ║  Tier 3 high-risk    ║──► mandatory human
        ╚═══════════╤══════════╝
                    │
           ┌────────▼──────────┐
           │ Confidence &      │   routing only after BOTH gates pass
           │ Risk Router       │
           └──────┬───────┬────┘
                  │       │
        ┌─────────▼─┐   ┌─▼──────────────────┐
        │ Execution │   │ Human Approval Loop │
        │ Agent     │   │                     │
        └─────┬─────┘   └──┬──────────────┬──┘
              │       Approved          Rejected
              │            │                │
    ┌─────────▼────┐  ┌────▼───────┐  ┌───▼──────────┐
    │Slack · Jira  │  │ Execution  │  │ Revise /     │
    │Incident Tool │  │ Agent      │  │ Escalate     │
    └─────────┬────┘  └─────┬──────┘  └───────┬──────┘
              │             │                  │
              └──────┬──────┘           Human Escalation
                     │
               ┌─────▼──────┐
               │ Trace Store │
               └─────┬──────┘
                     │
           ┌─────────▼──────────┐
           │ LLM Eval Pipeline  │   offline quality & safety scoring
           └────────────────────┘
```

---

## Policy Engine — Permission Tiers

| Tier | Classification | Examples | Approval |
|------|---------------|----------|----------|
| **1** | `read_only` | Fetch logs, read metrics, describe resources | ✅ Auto-approved |
| **2** | `reversible_write` | Restart service, toggle feature flag, flush cache | ✅ Auto / light review |
| **3** | `high_risk_write` | DB migration, infra teardown, secret rotation | 🔒 Mandatory human approval |

---

## Project Structure

```
OpsPilot/
├── opspilot/
│   ├── schemas.py                  # Canonical Pydantic v2 models — every data boundary
│   ├── provenance_gate.py          # Deterministic Provenance Gate (pure Python)
│   ├── policy_engine.py            # Deterministic Policy Engine  (pure Python)  [M3]
│   ├── tools/
│   │   └── simulated.py            # Simulated tool registry                      [M4]
│   ├── agents/
│   │   ├── ingestion.py            # Ingestion Agent                              [M5+]
│   │   ├── router.py               # Router & Severity Agent
│   │   ├── investigation.py        # Investigation Agent
│   │   ├── knowledge_retrieval.py  # Knowledge Retrieval Agent
│   │   ├── customer_communication.py
│   │   ├── evidence_diagnosis.py   # Evidence & Diagnosis Agent
│   │   ├── action_planner.py       # Action Planner Agent
│   │   └── execution.py            # Execution Agent
│   └── graph.py                    # LangGraph graph definition                   [M5]
└── tests/
    ├── test_provenance_gate.py      # 11 tests — all passing
    └── test_policy_engine.py                                                      [M3]
```

---

## Build Progress

| # | Module | File(s) | Status |
|---|--------|---------|--------|
| 1 | Schemas | `opspilot/schemas.py` | ✅ Complete |
| 2 | Provenance Gate | `opspilot/provenance_gate.py` + tests | ✅ Complete · 11/11 passing |
| 3 | Policy Engine | `opspilot/policy_engine.py` + tests | 🔲 In progress |
| 4 | Simulated Tools | `opspilot/tools/simulated.py` | 🔲 Pending |
| 5 | LangGraph Skeleton | `opspilot/graph.py` | 🔲 Pending |
| 6 | Agents | `opspilot/agents/` | 🔲 Pending |
| 7 | Eval Harness | `opspilot/eval/` | 🔲 Pending |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/ARYANRAJ1121/OpsPilot.git
cd OpsPilot

# 2. Install (Python 3.11+)
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env          # add your LLM API keys

# 4. Run tests
py -3.11 -m pytest tests/ -v
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM integration | [LangChain](https://github.com/langchain-ai/langchain) |
| Data contracts | [Pydantic v2](https://docs.pydantic.dev/) |
| Structured logging | [structlog](https://www.structlog.org/) |
| Testing | [pytest](https://pytest.org/) + pytest-asyncio |
| Linting / formatting | [ruff](https://github.com/astral-sh/ruff) |
| Type checking | [mypy](https://mypy-lang.org/) (strict mode) |

---

## Contributing

This project is being built incrementally — one confirmed module at a time. See the build progress table above for what's next. Each module ships with:
- Full type hints and Pydantic I/O contracts
- Structured logging at every agent boundary
- Unit tests before the module is marked complete

---

<div align="center">
Built with LangGraph · Pydantic v2 · Python 3.11
</div>
