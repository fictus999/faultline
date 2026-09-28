"""End-to-end check of the demo path against a running stack (used by CI after compose up).

normal traffic -> payments failure -> CRITICAL -> delivered to every sink -> recovery ->
RESOLVED delivered, with no alert on any other service. Standard library only.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Any

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"


def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed local URL
        BASE + path, data=data, method=method, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:  # noqa: S310
        return json.loads(res.read())


def wait_for(what: str, check: Any, timeout: float) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = check()
        except OSError:
            result = None
        if result:
            print(f"ok: {what}")
            return result
        time.sleep(1)
    sys.exit(f"FAILED: {what} (after {timeout:.0f} s)")


def payments_alert() -> dict[str, Any] | None:
    alerts = call("GET", "/api/state")["alerts"]
    return next((a for a in alerts if a["service"] == "payments"), None)


def all_delivered(alert: dict[str, Any], event_type: str) -> bool:
    events = [e for e in alert["events"] if e["type"] == event_type]
    return bool(events) and all(d["status"] == "delivered" for e in events for d in e["deliveries"])


def main() -> None:
    wait_for("api healthy", lambda: call("GET", "/healthz")["status"] == "ok", 120)
    wait_for(
        "baselines warm",
        lambda: (s := call("GET", "/api/state")["stats"]) and len(s["services"]) >= 5,
        120,
    )
    time.sleep(15)  # let the EWMA baselines settle before injecting
    call("POST", "/api/chaos/services/payments", {"error_rate": 0.35})
    alert = wait_for(
        "payments reaches CRITICAL",
        lambda: (a := payments_alert()) and a["severity"] == "CRITICAL" and a,
        60,
    )
    wait_for(
        "CRITICAL delivered to every sink",
        lambda: all_delivered(payments_alert() or {}, "ESCALATED"),
        30,
    )
    call("DELETE", "/api/chaos/services/payments")
    wait_for(
        "payments RESOLVED and delivered",
        lambda: (
            (a := payments_alert()) and a["status"] == "RESOLVED" and all_delivered(a, "RESOLVED")
        ),
        90,
    )
    others = [
        a["service"] for a in call("GET", "/api/state")["alerts"] if a["service"] != "payments"
    ]
    if others:
        sys.exit(f"FAILED: false positives on {sorted(set(others))}")
    print(f"ok: no false positives; alert {alert['alert_id']} passed the full lifecycle")


if __name__ == "__main__":
    main()
