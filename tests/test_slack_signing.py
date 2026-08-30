"""Unit tests for Slack signature + url_verification helper."""

from __future__ import annotations

import hashlib
import hmac
import time

from opspilot.integrations.signing import verify_slack_signature


def test_verify_slack_signature_ok() -> None:
    secret = "testsigningsecret0123456789abcdef"
    body = b'{"type":"url_verification","challenge":"abc"}'
    ts = str(int(time.time()))
    base = f"v0:{ts}:{body.decode()}"
    sig = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    assert verify_slack_signature(
        body,
        timestamp=ts,
        signature_header=sig,
        signing_secret=secret,
    )


def test_verify_slack_signature_bad() -> None:
    assert not verify_slack_signature(
        b"{}",
        timestamp=str(int(time.time())),
        signature_header="v0=deadbeef",
        signing_secret="secret",
    )
