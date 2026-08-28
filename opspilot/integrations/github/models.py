"""
opspilot/integrations/github/models.py

Pydantic models for GitHub webhook payloads.
Covers issues and issue_comment events.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GitHubUser(BaseModel):
    login: str = ""
    id: int = 0


class GitHubLabel(BaseModel):
    name: str = ""
    color: str = ""


class GitHubIssue(BaseModel):
    number: int = 0
    title: str = ""
    body: str | None = None
    state: str = "open"
    labels: list[GitHubLabel] = Field(default_factory=list)
    user: GitHubUser = Field(default_factory=GitHubUser)
    html_url: str = ""

    model_config = ConfigDict(extra="allow")


class GitHubComment(BaseModel):
    id: int = 0
    body: str = ""
    user: GitHubUser = Field(default_factory=GitHubUser)
    html_url: str = ""


class GitHubRepository(BaseModel):
    full_name: str = ""
    name: str = ""
    owner: GitHubUser = Field(default_factory=GitHubUser)


class GitHubWebhookPayload(BaseModel):
    """
    Top-level GitHub webhook payload for issues / issue_comment events.

    action examples:
      - "opened", "edited", "labeled", "closed"   (issues)
      - "created", "edited"                        (issue_comment)
    """

    action: str = ""
    issue: GitHubIssue = Field(default_factory=GitHubIssue)
    comment: GitHubComment | None = None
    repository: GitHubRepository = Field(default_factory=GitHubRepository)
    sender: GitHubUser = Field(default_factory=GitHubUser)

    model_config = ConfigDict(extra="allow")
