# Free Slack + Groq setup for OpsPilot ($0)

This guide gets a **live** path working with:

- Free Slack workspace + free Slack app
- Free Groq API key
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

## 3. Run the webhook locally

```bash
pip install -e ".[dev]"
uvicorn opspilot.integrations.slack.webhook:app --host 0.0.0.0 --port 8000
```

Check: http://127.0.0.1:8000/healthz → `{"status":"ok"}`

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

## 6. Smoke test in Slack

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

## 7. Local smoke (no Slack UI)

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
| Cloudflare quick tunnel | $0 |
| Real AWS/K8s remediations | Not used |
