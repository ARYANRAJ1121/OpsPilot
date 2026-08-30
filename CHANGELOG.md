# Changelog

## 1.0.1 — 2026-08-30

### Packaging & ops
- MIT `LICENSE`, GitHub Actions CI, `Makefile`, `Dockerfile`
- Package version `1.0.1` exposed as `opspilot.__version__`

### Hardening
- Default `OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true`
- Approvals HTML UI enforces `OPSPILOT_APPROVAL_API_TOKEN` when set
- `opspilot doctor` warns on open webhooks / open approvals UI
- `opspilot smoke-webhooks` offline adapter smoke

### Docs
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/CONTRIBUTING.md`
- README synced to real layout and CI badge

## 1.0.0 — 2026-08-29

- Unified ingest server (Slack, Jira, GitHub, tickets, logs)
- Durable SQLite HITL + JSON approval queue + `/approvals` UI
- Groq enrichment / planning with heuristic fallback
- Simulated remediation executor with override hooks
- Free Slack + Groq go-live guide
