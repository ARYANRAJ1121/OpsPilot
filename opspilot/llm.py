"""
opspilot/llm.py

Thin, defensive wrapper around the chat LLM (Groq).

Design rule that mirrors the rest of OpsPilot: the LLM only ever enriches
*narrative* fields (diagnosis prose, customer messages, rationales). It
never selects tools or makes the execute/approve decision — those stay in
deterministic Python. Every call falls back to a caller-supplied string if
the model is disabled, unauthenticated, or errors out, so the whole system
runs offline with no behavioural change to the safety path.

Guardrails screen input and output; on block we return `fallback`.
"""

from __future__ import annotations

import structlog

from opspilot.config import get_settings
from opspilot.guardrails import check_input, check_output, check_with_groq_judge

log = structlog.get_logger(__name__)

_MODEL_CACHE: dict[str, object] = {}


def llm_active() -> bool:
    """True when a usable LLM is configured."""
    return get_settings().llm_active


def clear_model_cache() -> None:
    _MODEL_CACHE.clear()


def _get_model():
    settings = get_settings()
    if not settings.llm_active:
        return None

    cache_key = f"groq:{settings.llm_model}:{settings.llm_temperature}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    try:
        from langchain_groq import ChatGroq

        model = ChatGroq(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            api_key=settings.groq_api_key,
        )
        _MODEL_CACHE[cache_key] = model
        return model
    except Exception as exc:  # pragma: no cover - depends on external pkg/creds
        log.warning("llm.init_failed", error=str(exc))
        return None


def enrich(system_prompt: str, user_prompt: str, *, fallback: str) -> str:
    """
    Ask the LLM to produce a short narrative string.

    Returns `fallback` unchanged whenever the LLM is unavailable, blocked by
    guardrails, or raises. The result is never allowed to be empty.
    """
    if not check_input(user_prompt).allowed:
        return fallback

    model = _get_model()
    if model is None:
        return fallback

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = model.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        text = (getattr(response, "content", "") or "").strip()
        if not text:
            return fallback
        if not check_output(text).allowed:
            return fallback
        if not check_with_groq_judge(text, role="output").allowed:
            return fallback
        log.info("llm.enrich_ok", chars=len(text))
        return text
    except Exception as exc:  # pragma: no cover - network/credential dependent
        log.warning("llm.enrich_failed", error=str(exc))
        return fallback
