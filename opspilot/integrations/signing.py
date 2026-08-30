"""
Shared webhook signature verification for GitHub, Jira, and Slack.

GitHub: X-Hub-Signature-256 = sha256=<hmac_hex>
Jira:   X-Hub-Signature (sha256=...) OR X-OpsPilot-Webhook-Secret header
Slack:  X-Slack-Signature = v0=<hmac_hex> over "v0:{timestamp}:{body}"
"""

from __future__ import annotations

import hashlib
import hmac
import time


def _hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_github_signature(
    body: bytes,
    signature_header: str | None,
    secret: str | None,
    *,
    require: bool = False,
) -> bool:
    """Return True if the GitHub webhook signature is valid (or not required)."""
    if not secret:
        return not require
    if not signature_header:
        return False
    expected = "sha256=" + _hmac_sha256_hex(secret, body)
    return hmac.compare_digest(expected, signature_header.strip())


def verify_jira_signature(
    body: bytes,
    *,
    signature_header: str | None = None,
    shared_secret_header: str | None = None,
    secret: str | None = None,
    require: bool = False,
) -> bool:
    """
    Return True if the Jira webhook auth is valid (or not required).

    Accepts either:
      - X-Hub-Signature: sha256=<hmac>
      - X-OpsPilot-Webhook-Secret: <plain secret>  (easy free-tier setup)
    """
    if not secret:
        return not require
    if shared_secret_header is not None:
        return hmac.compare_digest(secret, shared_secret_header.strip())
    if signature_header:
        expected = "sha256=" + _hmac_sha256_hex(secret, body)
        return hmac.compare_digest(expected, signature_header.strip())
    return False


def verify_slack_signature(
    body: bytes,
    *,
    timestamp: str | None,
    signature_header: str | None,
    signing_secret: str | None,
    max_age_seconds: int = 60 * 5,
) -> bool:
    """Verify Slack's X-Slack-Signature (v0=...)."""
    if not signing_secret or not timestamp or not signature_header:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > max_age_seconds:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature_header.strip())
