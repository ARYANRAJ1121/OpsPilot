"""
opspilot/integrations/jira/models.py

Pydantic models for Jira webhook payloads.
Covers issue_created, issue_updated, and comment_created events.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JiraUser(BaseModel):
    account_id: str = ""
    display_name: str = ""
    email_address: str = ""


class JiraProject(BaseModel):
    key: str = ""
    name: str = ""


class JiraPriority(BaseModel):
    name: str = "Medium"
    id: str = ""


class JiraIssueType(BaseModel):
    name: str = ""
    subtask: bool = False


class JiraStatus(BaseModel):
    name: str = ""
    category_key: str = ""


class JiraFields(BaseModel):
    summary: str = ""
    description: str | None = None
    priority: JiraPriority = Field(default_factory=JiraPriority)
    issuetype: JiraIssueType = Field(default_factory=JiraIssueType)
    status: JiraStatus = Field(default_factory=JiraStatus)
    project: JiraProject = Field(default_factory=JiraProject)
    reporter: JiraUser | None = None
    assignee: JiraUser | None = None
    labels: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class JiraIssue(BaseModel):
    id: str = ""
    key: str = ""
    fields: JiraFields = Field(default_factory=JiraFields)
    self_url: str = Field("", alias="self")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class JiraComment(BaseModel):
    id: str = ""
    body: str = ""
    author: JiraUser = Field(default_factory=JiraUser)


class JiraWebhookPayload(BaseModel):
    """
    Top-level Jira webhook payload.

    webhookEvent examples:
      - jira:issue_created
      - jira:issue_updated
      - comment_created
    """

    webhook_event: str = Field("", alias="webhookEvent")
    issue: JiraIssue = Field(default_factory=JiraIssue)
    comment: JiraComment | None = None
    user: JiraUser = Field(default_factory=JiraUser)
    timestamp: int | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")
