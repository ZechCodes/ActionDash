"""GitHub webhook signature verification."""

import hashlib
import hmac
import os


def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    """Verify the GitHub webhook signature (HMAC-SHA256).

    If GITHUB_WEBHOOK_SECRET is not set, signature verification is skipped
    (development mode).
    """
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        # No secret configured — skip verification in development
        return True

    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")

    return hmac.compare_digest(expected, received)
