"""Incident keyword detection for Slack messages."""

from __future__ import annotations

import re

# Patterns that mark a Slack message as an OpsPilot incident candidate.
INCIDENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("alert_emoji", re.compile(r"(?:⚠️|⚠|🚨|🔥)")),
    ("alert_word", re.compile(r"\balert\b", re.IGNORECASE)),
    ("incident_prefix", re.compile(r"\bincident\s*:", re.IGNORECASE)),
    ("sev", re.compile(r"\bsev[0-3]\b", re.IGNORECASE)),
    ("p0_p1", re.compile(r"\bp[01]\b", re.IGNORECASE)),
    ("outage", re.compile(r"\boutage\b", re.IGNORECASE)),
    ("page", re.compile(r"\bpage(?:d|ing)?\b", re.IGNORECASE)),
)


def extract_incident_keywords(text: str) -> list[str]:
    """Return names of patterns that matched; empty ⇒ not an incident."""
    if not text or not text.strip():
        return []
    return [name for name, pattern in INCIDENT_PATTERNS if pattern.search(text)]


def is_incident_message(text: str) -> bool:
    return bool(extract_incident_keywords(text))


def extract_channel_tags(topic: str | None, purpose: str | None) -> list[str]:
    """Parse #tags or [env:prod] style markers from channel topic/purpose."""
    blob = f"{topic or ''} {purpose or ''}"
    tags = re.findall(r"#([a-zA-Z0-9_-]+)", blob)
    tags += re.findall(r"\[([a-zA-Z0-9_:-]+)\]", blob)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out
