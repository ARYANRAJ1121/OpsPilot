"""Knowledge Retrieval Agent — pull runbook evidence. No LLM."""

from __future__ import annotations

from opspilot.schemas import IngestionOutput, KnowledgeRetrievalOutput, RouterOutput
from opspilot.tools.simulated import execute_tool


def run_knowledge_retrieval(
    ingestion: IngestionOutput,
    router: RouterOutput,
) -> KnowledgeRetrievalOutput:
    query = f"{router.incident_type} {ingestion.normalized_title}"
    runbook = execute_tool("search_runbook", {"query": query})
    articles = runbook.result.get("results", [])
    titles = ", ".join(a.get("title", "untitled") for a in articles) or "none"

    return KnowledgeRetrievalOutput(
        event_id=ingestion.event_id,
        tool_outputs=[runbook],
        articles_summary=f"Retrieved {len(articles)} runbook(s): {titles}",
    )
