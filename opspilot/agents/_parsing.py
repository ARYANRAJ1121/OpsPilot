"""Shared, deterministic parsing helpers for heuristic agents."""

from __future__ import annotations

import re

_SERVICE_PATTERNS = (
    re.compile(r"\b([a-z][a-z0-9-]*-service)\b", re.IGNORECASE),
    re.compile(r"\b([a-z][a-z0-9-]*-api)\b", re.IGNORECASE),
    re.compile(r"\b(api-service|payments-api|checkout-api)\b", re.IGNORECASE),
)


def infer_service_name(text: str, default: str = "api-service") -> str:
    """Extract a likely service name from alert text; fall back to a stable default."""
    for pattern in _SERVICE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).lower()
    return default
