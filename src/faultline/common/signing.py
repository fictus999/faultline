"""HMAC-SHA256 signatures for outgoing webhooks, with replay protection on receipt."""

from __future__ import annotations

import hashlib
import hmac

MAX_SKEW_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + digest.hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, now: float) -> bool:
    """Constant-time check of the signature, rejecting stale timestamps (replays)."""
    try:
        age = abs(now - int(timestamp))
    except ValueError:
        return False
    if age > MAX_SKEW_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)
