"""Parse one log line into an event, stripping control characters and redacting secrets.

Log lines are untrusted input: anything that can make an app log can write here. Lines
are capped, control characters (CR, ANSI escapes) are removed so one physical line can't
forge a second entry, and secrets are redacted before the event leaves the collector.
All patterns are anchored and linear, so a hostile line can't trigger ReDoS.
"""

from __future__ import annotations

import re
from datetime import datetime

MAX_LINE = 8192
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_LINE = re.compile(
    r"^(?P<ts>\S{1,40}) level=(?P<level>[A-Z]{3,8}) service=(?P<service>[a-z][a-z0-9_-]{0,31})"
    r" seq=(?P<seq>\d{1,18})(?: (?P<rest>.*))?$"
)
_REDACTIONS = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws_access_key]"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,512}"), "Bearer [REDACTED:token]"),
    (
        re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8}"),
        "[REDACTED:email]",
    ),
)
ERROR_LEVELS = frozenset({"ERROR", "FATAL"})


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def parse(line: str) -> dict[str, str] | None:
    """Return stream fields for a valid line, or None if it doesn't match the format."""
    clean = _CONTROL.sub("", line[:MAX_LINE])
    match = _LINE.match(clean)
    if match is None:
        return None
    try:
        ts = datetime.fromisoformat(match["ts"].replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    level = match["level"]
    return {
        "ts": f"{ts:.3f}",
        "service": match["service"],
        "level": level,
        "seq": match["seq"],
        "error": "1" if level in ERROR_LEVELS else "0",
        "msg": redact(match["rest"] or ""),
    }
