"""OpsPilot integration adapters — Slack, Jira, GitHub Issues."""

from opspilot.integrations.slack.adapter import SlackAdapter
from opspilot.integrations.jira.adapter import handle_jira_webhook
from opspilot.integrations.github.adapter import handle_github_webhook

__all__ = ["SlackAdapter", "handle_jira_webhook", "handle_github_webhook"]
