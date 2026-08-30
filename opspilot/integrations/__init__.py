"""OpsPilot integration adapters."""

from opspilot.integrations.github.adapter import handle_github_webhook
from opspilot.integrations.jira.adapter import handle_jira_webhook
from opspilot.integrations.logs.adapter import handle_logs_webhook
from opspilot.integrations.slack.adapter import SlackAdapter
from opspilot.integrations.tickets.adapter import handle_ticket_webhook

__all__ = [
    "SlackAdapter",
    "handle_jira_webhook",
    "handle_github_webhook",
    "handle_ticket_webhook",
    "handle_logs_webhook",
]
