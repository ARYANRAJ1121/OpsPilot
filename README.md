<div align="center">

# OpsPilot

**Agentic AI incident response — from raw alert to executed remediation, safely.**

[![CI](https://github.com/ARYANRAJ1121/OpsPilot/actions/workflows/ci.yml/badge.svg)](https://github.com/ARYANRAJ1121/OpsPilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Version](https://img.shields.io/badge/version-1.0.1-0ea5e9?style=flat)](./CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat)](./LICENSE)

</div>

---

OpsPilot is a **multi-agent incident-response system** on LangGraph. It ingests Slack / Jira / GitHub / tickets / logs, investigates in parallel, then routes remediations through **deterministic Provenance + Policy + Confidence gates** before execution.

Narrative enrichment uses **Groq’s free tier** when `GROQ_API_KEY` is set. Remediations are **simulated / dry-run by default ($0)**. No LLM decides what executes.

**Status: v1.0.1 complete** for the $0 design. Real cloud remediations are opt-in via `register_tool_override`.

---

## Quickstart

```bash
git clone https://github.com/ARYANRAJ1121/OpsPilot.git
cd OpsPilot
pip install -e ".[dev]"
cp .env.example .env

pytest tests/ -q
opspilot doctor
opspilot run "ALERT: api-service error rate 18% — p99 latency 4200ms"

# Live unified server
uvicorn opspilot.server:app --host 0.0.0.0 --port 8000
# cloudflared tunnel --url http://127.0.0.1:8000
```

Free go-live: [docs/FREE_SLACK_GROQ.md](./docs/FREE_SLACK_GROQ.md) · Architecture: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) · API: [docs/API.md](./docs/API.md)

---

## Project layout

```
opspilot/
├── schemas.py              # Pydantic contracts
├── provenance_gate.py      # Deterministic provenance gate
├── policy_engine.py        # Tier 1/2/3 policy
├── confidence_router.py    # Auto vs HITL routing
├── graph.py                # LangGraph pipeline + interrupt/resume
├── checkpoint.py           # SQLite / memory checkpointer
├── approval_queue.py       # Durable pending-approval JSON
├── approvals_ui.py         # /approvals + /api/approvals
├── server.py               # Unified ingest FastAPI app
├── cli.py                  # opspilot run/eval/doctor/smoke-*
├── tools/{simulated,executor}.py
├── agents/                 # 8 specialised agents
└── integrations/           # slack, jira, github, tickets, logs, signing
tests/                      # 180+ unit/integration tests
docs/                       # Architecture, API, go-live, contributing
```

---

## Build status

| Area | Status |
|------|--------|
| Core pipeline + safety gates | Complete |
| Slack / Jira / GitHub / tickets / logs ingest | Complete |
| Durable HITL + web approvals | Complete |
| Groq enrichment / planning + guardrails | Complete |
| Simulated / dry-run remediations | Complete ($0) |
| CI + LICENSE + Docker/Makefile | Complete |
| Real paid cloud remediations | Out of scope — use `register_tool_override` |

---

## Stack

[LangGraph](https://github.com/langchain-ai/langgraph) · [Groq](https://console.groq.com) · [Pydantic v2](https://docs.pydantic.dev) · [FastAPI](https://fastapi.tiangolo.com/) · [slack-bolt](https://slack.dev/bolt-python/) · Python 3.11+
