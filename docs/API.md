# API reference

Serve OpenAPI interactively at `http://127.0.0.1:8000/docs` when the unified server is running.

## Core routes

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/healthz` | none | Liveness + integration flags |
| GET | `/approvals` | optional token | HTML HITL queue |
| GET | `/api/approvals` | optional token | JSON pending list |
| POST | `/api/approvals/{thread_id}/decide` | optional token | `{ "decision": "approved\|rejected", "reviewer_id": "..." }` |
| POST | `/slack/events` | Slack signing secret | Bolt Events API |
| POST | `/slack/interactions` | Slack signing secret | Approve / Reject buttons |
| POST | `/jira/webhook` | shared secret / HMAC | Issue / comment ingest |
| POST | `/github/webhook` | `X-Hub-Signature-256` | Issues / comments |
| POST | `/tickets/webhook` | shared secret / HMAC | Support tickets |
| POST | `/logs/webhook` | shared secret / HMAC | Logs / Alertmanager |

## Auth headers

When `OPSPILOT_APPROVAL_API_TOKEN` is set:

- `Authorization: Bearer <token>` or `X-OpsPilot-Token: <token>`
- Browser: `/approvals?token=<token>` (stored in `localStorage`)

When `OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true` (default):

- Jira / tickets / logs: `X-OpsPilot-Webhook-Secret: <secret>` or `X-Hub-Signature: sha256=...`
- GitHub: `X-Hub-Signature-256: sha256=...`
