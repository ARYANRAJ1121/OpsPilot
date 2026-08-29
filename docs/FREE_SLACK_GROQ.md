# Free Slack + Groq + webhooks setup for OpsPilot ($0)

This guide gets a **live** path working with:

- Free Slack workspace + free Slack app
- Free Groq API key
- Optional free Jira Cloud / GitHub Issues webhooks
- Free public tunnel (Cloudflare Tunnel)
- Simulated remediations (no cloud infra bill)

## 1. Groq (free)

1. Create an account at https://console.groq.com
2. Create an API key at https://console.groq.com/keys
3. Put it in `.env`:

```env
GROQ_API_KEY=gsk_...
OPSPILOT_LLM_ENABLED=true
OPSPILOT_LLM_MODEL=openai/gpt-oss-20b
OPSPILOT_LLM_PLANNING=true
OPSPILOT_GUARDRAILS_ENABLED=true
OPSPILOT_GUARDRAILS_LLM=false
```

`OPSPILOT_GUARDRAILS_LLM=true` turns on an extra Groq PASS/FAIL judge (uses free quota).

## 2. Slack app (free)

1. Open https://api.slack.com/apps → **Create New App** → From scratch
2. **OAuth & Permissions** → Bot Token Scopes (add):
   - `app_mentions:read`
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `groups:history` (if using private channels)
   - `users:read`
   - `commands` (optional)
3. **Install to Workspace** → copy **Bot User OAuth Token** (`xoxb-...`)
4. **Basic Information** → copy **Signing Secret**
5. Invite the bot to a channel: `/invite @OpsPilot`

`.env`:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
# Optional: restrict to one channel ID (C…)
SLACK_ALLOWED_CHANNELS=
```

## 3. Run the unified ingest server

One process serves Slack, Jira, and GitHub:

```bash
pip install -e ".[dev]"
uvicorn opspilot.server:app --host 0.0.0.0 --port 8000
```

Check: http://127.0.0.1:8000/healthz → `{"status":"ok", ...}`

| Path | Purpose |
|------|---------|
| `POST /slack/events` | Slack Events API |
| `POST /slack/interactions` | Approve / Reject / Add context |
| `POST /jira/webhook` | Jira issue / comment webhooks |
| `POST /github/webhook` | GitHub Issues / issue_comment |
| `POST /tickets/webhook` | Support-ticket ingest |
| `POST /logs/webhook` | Logs / Alertmanager-style alerts |
| `GET /approvals` | Web HITL approval UI |
| `GET /api/approvals` | Pending approvals JSON |
| `POST /api/approvals/{thread_id}/decide` | Approve / reject via API |
| `GET /healthz` | Liveness + integration flags |

(Slack-only still works: `uvicorn opspilot.integrations.slack.webhook:app`)

## 4. Free public URL (Cloudflare Tunnel)

No paid ngrok required.

```bash
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the `https://….trycloudflare.com` URL.

## 5. Point Slack at your tunnel

**Event Subscriptions** → Enable → Request URL:

`https://<tunnel>/slack/events`

Subscribe to bot events:

- `message.channels` (and/or `message.groups`)
- `app_mention`

**Interactivity & Shortcuts** → Enable → Request URL:

`https://<tunnel>/slack/interactions`

Save. Slack should show **Verified**.

## 6. Optional: Jira webhook

1. Pick a shared secret and put it in `.env`:

```env
JIRA_WEBHOOK_SECRET=your-long-random-string
OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true
```

2. In Jira → **System** → **Webhooks** → create webhook:
   - URL: `https://<tunnel>/jira/webhook`
   - Events: Issue created / updated, Comment created
3. Configure your reverse proxy or automation to send one of:
   - Header `X-OpsPilot-Webhook-Secret: your-long-random-string` (easiest free setup)
   - Header `X-Hub-Signature: sha256=<hmac of body>`

Jira Cloud’s native webhook UI may not add custom headers — use an intermediate automation, or set `OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=false` only for local smoke (not for public tunnels).

## 7. Optional: GitHub Issues webhook

1. Repo → **Settings** → **Webhooks** → Add webhook
2. Payload URL: `https://<tunnel>/github/webhook`
3. Content type: `application/json`
4. Secret: same value as `GITHUB_WEBHOOK_SECRET` in `.env`
5. Events: **Issues** and **Issue comments**

```env
GITHUB_WEBHOOK_SECRET=your-github-webhook-secret
OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true
```

OpsPilot verifies `X-Hub-Signature-256`.

## 8. Smoke test in Slack

In the invited channel post:

```text
incident: api-service error rate 18%
```

or

```text
⚠️ alert api-service latency high
```

You should see:

1. Thread status (“OpsPilot accepted…”)
2. Live “updated X seconds ago” while triaging
3. Either auto-result or **Approve / Reject / Add context** buttons

## 9. Live smoke checklist

```text
[ ] opspilot doctor — groq + slack look ready
[ ] uvicorn opspilot.server:app on :8000
[ ] GET /healthz returns status ok
[ ] cloudflared tunnel up
[ ] Slack Events URL verified
[ ] Slack Interactivity URL verified
[ ] Post “incident: …” → thread ACK + triage
[ ] (optional) GitHub issue with “incident” label → 202 then triage in logs
[ ] (optional) Jira issue with High priority → 202 then triage in logs
[ ] OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true before sharing a public tunnel
```

## 10. Local smoke (no Slack UI)

```bash
opspilot doctor
opspilot smoke-slack
```

`smoke-slack` feeds a fake Events payload through `SlackAdapter` (no Slack network).

## Cost checklist

| Dependency | Cost |
|------------|------|
| OpsPilot + simulated tools | $0 |
| Groq free tier | $0 (rate limits) |
| Slack free workspace | $0 |
| Jira Cloud free / GitHub Issues | $0 (within free plans) |
| Cloudflare quick tunnel | $0 |
| Real AWS/K8s remediations | Not used |
