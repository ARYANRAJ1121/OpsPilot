"""CLI wrapper for local Slack smoke (no Slack network)."""

from opspilot.integrations.slack.smoke import main

if __name__ == "__main__":
    raise SystemExit(main())
