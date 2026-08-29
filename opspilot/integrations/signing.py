"""
Shared webhook signature verification for GitHub and Jira.

GitHub: X-Hub-Signature-256 = sha256=<hmac_hex>
Jira:   X-Hub-Signature (sha256=...) OR X-OpsPilot-Webhook-Secret header
        matching JIRA_WEBHOOK_SECRET (simple shared-secret mode for free setups).

When the corresponding secret is unset, verification is skipped (dev/local).
When OPSPILOT_WEBHOOK_REQUIRE_SIGNATURES=true, missing secrets cause 401.
"""

from __future__ import annotations

import hashlib
import hmac


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
