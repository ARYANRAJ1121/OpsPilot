# Contributing

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
```

## Checks before a PR

```bash
make lint
make test
opspilot doctor
opspilot smoke-slack
opspilot smoke-webhooks
```

## Rules

- Keep remediations free by default (`simulated` / `dry_run`).
- Do not commit `.env` or secrets.
- Prefer deterministic gates over LLM decisions for execution.
- Add/adjust tests under `tests/` for behavior changes.

## Docs

- Architecture: [ARCHITECTURE.md](./ARCHITECTURE.md)
- HTTP API: [API.md](./API.md)
- Free go-live: [FREE_SLACK_GROQ.md](./FREE_SLACK_GROQ.md)
