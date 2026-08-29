"""Tests for webhook HMAC / shared-secret verification."""

from __future__ import annotations

import hashlib
import hmac

from opspilot.integrations.signing import verify_github_signature, verify_jira_signature


def _sha256_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestGitHubSignature:
    def test_valid(self) -> None:
        body = b'{"action":"opened"}'
        secret = "gh-secret"
        assert verify_github_signature(body, _sha256_sig(secret, body), secret)

    def test_invalid(self) -> None:
        body = b'{"action":"opened"}'
        assert not verify_github_signature(
            body, "sha256=deadbeef", "gh-secret", require=True
        )

    def test_skip_when_no_secret(self) -> None:
        assert verify_github_signature(b"{}", None, None, require=False)

    def test_require_without_secret_fails(self) -> None:
        assert not verify_github_signature(b"{}", None, None, require=True)


class TestJiraSignature:
    def test_hmac_header(self) -> None:
        body = b'{"webhookEvent":"jira:issue_created"}'
        secret = "jira-secret"
        assert verify_jira_signature(
            body,
            signature_header=_sha256_sig(secret, body),
            secret=secret,
        )

    def test_shared_secret_header(self) -> None:
        assert verify_jira_signature(
            b"{}",
            shared_secret_header="plain-secret",
            secret="plain-secret",
        )

    def test_wrong_shared_secret(self) -> None:
        assert not verify_jira_signature(
            b"{}",
            shared_secret_header="wrong",
            secret="plain-secret",
            require=True,
        )
