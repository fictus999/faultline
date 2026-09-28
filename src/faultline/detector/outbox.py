"""Write an alert event and its deliveries in one transaction (the transactional outbox)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from faultline.detector.model import Assessment, Transition


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts is not None else None


async def record(
    conn: AsyncConnection[Any],
    service: str,
    transition: Transition,
    assessment: Assessment,
    sinks: Sequence[str],
    injected_at: float | None,
    now: float,
) -> dict[str, Any]:
    """Persist the event; the notifier delivers it later, even if it is down right now."""
    event_id = uuid.uuid4()
    severity = transition.severity.name
    payload: dict[str, Any] = {
        "event_id": str(event_id),
        "alert_id": str(transition.alert_id),
        "type": transition.type,
        "service": service,
        "rule": "error_rate",
        "severity": severity,
        "occurred_at": _iso(now),
        "opened_at": _iso(transition.opened_at),
        "injected_at": _iso(injected_at),
        "metrics": {
            "error_rate_short": round(assessment.short_rate, 4),
            "error_rate_long": round(assessment.long_rate, 4),
            "baseline": round(assessment.baseline, 4),
            "z": round(assessment.z, 1),
            "burn_short": round(assessment.burn_short, 1),
            "burn_long": round(assessment.burn_long, 1),
        },
    }
    async with conn.transaction():
        if transition.type == "CREATED":
            await conn.execute(
                "INSERT INTO alerts (alert_id, service, rule, severity, status, opened_at,"
                " injected_at) VALUES (%s, %s, 'error_rate', %s, 'FIRING', to_timestamp(%s),"
                " to_timestamp(%s))",
                (transition.alert_id, service, severity, transition.opened_at, injected_at),
            )
        elif transition.type == "ESCALATED":
            await conn.execute(
                "UPDATE alerts SET severity = %s, updated_at = now() WHERE alert_id = %s",
                (severity, transition.alert_id),
            )
        else:
            await conn.execute(
                "UPDATE alerts SET status = 'RESOLVED', resolved_at = to_timestamp(%s),"
                " updated_at = now() WHERE alert_id = %s",
                (now, transition.alert_id),
            )
        await conn.execute(
            "INSERT INTO alert_events (event_id, alert_id, type, severity, severity_rank, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (
                event_id,
                transition.alert_id,
                transition.type,
                severity,
                int(transition.severity),
                Jsonb(payload),
            ),
        )
        for sink in sinks:
            await conn.execute(
                "INSERT INTO deliveries (event_id, sink) VALUES (%s, %s)"
                " ON CONFLICT (event_id, sink) DO NOTHING",
                (event_id, sink),
            )
    return payload
