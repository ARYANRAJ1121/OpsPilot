"""
opspilot/schemas.py

Canonical Pydantic v2 models for every data boundary in OpsPilot:
agent I/O, tool layer, deterministic gate outputs, routing, human
approval, execution, and trace records.

No logic lives here — pure data contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentSource(str, Enum):
    SLACK = "slack"
    SUPPORT_TICKET = "support_ticket"
    LOGS = "logs"
    GITHUB_ISSUES = "github_issues"


class ToolPermissionTier(str, Enum):
    """
    Policy Engine classification for every registered tool.

    READ_ONLY        — Tier 1: zero state change, auto-approved.
    REVERSIBLE_WRITE — Tier 2: state change that can be undone, auto-approved
                       or light-review depending on confidence.
    HIGH_RISK_WRITE  — Tier 3: irreversible or high-blast-radius action,
                       mandatory human approval regardless of confidence.
    """

    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    HIGH_RISK_WRITE = "high_risk_write"


class RoutingDecision(str, Enum):
    AUTO_EXECUTE = "auto_execute"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"
    ESCALATE = "escalate"


class HumanApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Tool layer
# ---------------------------------------------------------------------------


class ToolOutput(BaseModel):
    """Immutable record produced by one tool execution."""

    tool_output_id: UUID = Field(default_factory=uuid4)
    tool_name: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Evidence(BaseModel):
    """
    A single piece of evidence an agent asserts.

    MUST reference a ToolOutput via tool_output_id.  The Provenance Gate
    rejects any ActionProposal whose evidence_refs cannot be resolved to
    real ToolOutput records collected during this incident's investigation.
    Raw event.content text is never a valid source for evidence.
    """

    tool_output_id: UUID
    summary: str  # agent-authored interpretation of that tool output only


# ---------------------------------------------------------------------------
# Ingestion Agent
# ---------------------------------------------------------------------------


class IncidentEvent(BaseModel):
    """Raw, unprocessed signal from an external source."""

    event_id: UUID = Field(default_factory=uuid4)
    source: IncidentSource
    content: str
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionOutput(BaseModel):
    event_id: UUID
    source: IncidentSource
    normalized_title: str
    normalized_body: str
    received_at: datetime
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router & Severity Agent (step 2 — forks into 3a, 3b, 3c)
# ---------------------------------------------------------------------------


class RouterOutput(BaseModel):
    event_id: UUID
    severity: Severity
    incident_type: str
    routing_notes: str


# ---------------------------------------------------------------------------
# Investigation Agent (branch 3a)
# ---------------------------------------------------------------------------


class InvestigationOutput(BaseModel):
    event_id: UUID
    tool_outputs: list[ToolOutput]
    findings_summary: str


# ---------------------------------------------------------------------------
# Knowledge Retrieval Agent (branch 3b)
# ---------------------------------------------------------------------------


class KnowledgeRetrievalOutput(BaseModel):
    event_id: UUID
    tool_outputs: list[ToolOutput]
    articles_summary: str


# ---------------------------------------------------------------------------
# Customer Communication Agent (branch 3c)
#
# Forks directly from RouterOutput — independent branch that NEVER merges
# back into the main pipeline.  It consumes severity/triage data only and
# terminates by writing a TraceEntry directly to the Trace Store.
# ---------------------------------------------------------------------------


class CustomerCommunicationOutput(BaseModel):
    event_id: UUID
    severity: Severity           # sourced from RouterOutput, not investigation
    message_draft: str
    target_channels: list[str]
    dispatched_at: datetime | None = None


# ---------------------------------------------------------------------------
# Evidence & Diagnosis Agent (step 4 — consumes 3a + 3b only, NOT 3c)
# ---------------------------------------------------------------------------


class EvidenceAndDiagnosisOutput(BaseModel):
    event_id: UUID
    evidence: list[Evidence]           # every item must cite a real tool_output_id
    diagnosis: str
    confidence_score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Action Planner Agent (step 5)
# ---------------------------------------------------------------------------


class ActionProposal(BaseModel):
    """
    A single proposed remediation action.

    evidence_refs must contain at least one UUID mapping to a ToolOutput
    the Provenance Gate can verify in scope.  Proposals citing only raw
    event content — i.e. with an empty or unresolvable evidence_refs — are
    rejected by the gate before reaching the Policy Engine.
    """

    proposal_id: UUID = Field(default_factory=uuid4)
    tool_name: str
    parameters: dict[str, Any]
    evidence_refs: list[UUID]    # tool_output_ids — validated by Provenance Gate
    rationale: str


class ActionPlannerOutput(BaseModel):
    event_id: UUID
    proposals: list[ActionProposal]


# ---------------------------------------------------------------------------
# Deterministic Provenance Gate (pure Python — no LLM)
# ---------------------------------------------------------------------------


class ProvenanceCheckResult(BaseModel):
    """
    Output of the Deterministic Provenance Gate.

    approved_proposals have all evidence_refs resolved to known ToolOutputs.
    rejected_proposals are dropped before the Policy Engine sees them.
    rejection_reasons keys are str(proposal_id) for JSON-serialisation safety.
    """

    passed: bool                              # True iff approved_proposals is non-empty
    approved_proposals: list[ActionProposal]
    rejected_proposals: list[ActionProposal]
    rejection_reasons: dict[str, str]         # str(proposal_id) -> human-readable reason


# ---------------------------------------------------------------------------
# Deterministic Policy Engine (pure Python — no LLM)
# ---------------------------------------------------------------------------


class PolicyDecision(BaseModel):
    """Per-proposal decision from the Policy Engine."""

    proposal_id: UUID
    tool_name: str
    permission_tier: ToolPermissionTier
    approved: bool
    requires_human_approval: bool
    rejection_reason: str | None = None


class PolicyEngineResult(BaseModel):
    """Aggregated result across all proposals submitted to the Policy Engine."""

    event_id: UUID
    decisions: list[PolicyDecision]
    all_approved: bool          # True only when every decision is approved
    any_requires_human: bool    # True when any Tier 3 tool is in the set


# ---------------------------------------------------------------------------
# Confidence & Risk Router (step 8 — only reached after both gates pass)
# ---------------------------------------------------------------------------


class ConfidenceRiskRouterOutput(BaseModel):
    event_id: UUID
    confidence_score: float = Field(ge=0.0, le=1.0)
    routing_decision: RoutingDecision
    approved_proposals: list[ActionProposal]
    policy_result: PolicyEngineResult


# ---------------------------------------------------------------------------
# Human Approval loop
# ---------------------------------------------------------------------------


class HumanApprovalRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    proposals: list[ActionProposal]
    policy_result: PolicyEngineResult
    context_summary: str


class HumanApprovalResponse(BaseModel):
    request_id: UUID
    decision: HumanApprovalDecision
    reviewer_id: str
    notes: str | None = None
    reviewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


class EscalationRecord(BaseModel):
    event_id: UUID
    reason: str
    human_response: HumanApprovalResponse | None = None
    escalated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Execution Agent
# ---------------------------------------------------------------------------


class ExecutionResult(BaseModel):
    event_id: UUID
    executed_tool_outputs: list[ToolOutput]
    success: bool
    summary: str
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Trace Store
# ---------------------------------------------------------------------------


class TraceEntry(BaseModel):
    """
    Structured log record written by every agent, gate, and router.

    input_snapshot / output_snapshot hold the serialised Pydantic model
    (via .model_dump()).  extra carries agent-specific metadata
    (e.g. LLM token counts, retry attempts).
    """

    trace_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    agent_name: str
    input_snapshot: dict[str, Any]
    output_snapshot: dict[str, Any]
    latency_ms: float
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    extra: dict[str, Any] = Field(default_factory=dict)
