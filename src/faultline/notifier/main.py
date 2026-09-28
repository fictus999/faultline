"""Notifier process body: relay the outbox to every sink with retries and backoff.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED, so two notifiers never take the same
delivery. If the notifier dies mid-send the transaction rolls back and the row stays
pending: nothing is lost, and the send is retried (at-least-once to the sink).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from redis.asyncio import Redis

from faultline.common.config import SINK_CHAOS_PREFIX, UI_CHANNEL, Config
from faultline.notifier.sinks import Sink, SinkError, build_sinks

log = structlog.get_logger()
BATCH = 20
MAX_ATTEMPTS = 8
BASE_DELAY = 1.0
MAX_DELAY = 60.0
SEND_TIMEOUT = 10.0

CLAIM_DUE = """
SELECT d.id, d.event_id, d.sink, d.attempts, e.payload
FROM deliveries d JOIN alert_events e ON e.event_id = d.event_id
WHERE d.status IN ('pending', 'retry') AND d.next_attempt_at <= now()
ORDER BY e.severity_rank DESC, d.created_at
LIMIT %s
FOR UPDATE OF d SKIP LOCKED
"""


def backoff_delay(attempt: int, rng: random.Random) -> float:
    """Exponential backoff with full jitter: uniform(0, min(cap, base * 2^attempt)).

    Without jitter, every delivery that failed in the same outage retries at the same
    instants and hits the recovering sink together; jitter spreads them out.
    """
    return rng.uniform(0, min(MAX_DELAY, BASE_DELAY * 2**attempt))


async def run(stop: asyncio.Event) -> None:
    cfg = Config.from_env()
    redis = Redis.from_url(cfg.redis_url, decode_responses=True)
    conn = await psycopg.AsyncConnection.connect(
        cfg.database_url, autocommit=True, row_factory=dict_row
    )
    sinks = build_sinks(cfg)
    rng = random.Random()  # noqa: S311 - jitter, not cryptography
    log.info("notifier_ready", sinks=sorted(sinks))
    try:
        while not stop.is_set():
            handled = await deliver_batch(conn, sinks, redis, rng)
            if handled == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 0.5)
    finally:
        await conn.close()
        await redis.aclose()


async def deliver_batch(
    conn: psycopg.AsyncConnection[Any], sinks: dict[str, Sink], redis: Redis, rng: random.Random
) -> int:
    updates: list[dict[str, Any]] = []
    async with conn.transaction():
        cur = await conn.execute(CLAIM_DUE, (BATCH,))
        rows = await cur.fetchall()
        for row in rows:
            event: dict[str, Any] = row["payload"]
            sink_name: str = row["sink"]
            attempts: int = row["attempts"] + 1
            try:
                sink = sinks.get(sink_name)
                if sink is None:
                    raise SinkError(f"sink {sink_name!r} is not configured")
                if await redis.exists(SINK_CHAOS_PREFIX + sink_name):
                    raise SinkError("injected failure (demo)")
                await asyncio.wait_for(sink.send(event), SEND_TIMEOUT)
            except Exception as exc:  # any sink failure is retried, never fatal
                status = "dead" if attempts >= MAX_ATTEMPTS else "retry"
                delay = backoff_delay(attempts, rng)
                await conn.execute(
                    "UPDATE deliveries SET status = %s, attempts = %s, last_error = %s,"
                    " next_attempt_at = now() + make_interval(secs => %s) WHERE id = %s",
                    (status, attempts, str(exc)[:500], delay, row["id"]),
                )
                log.warning(
                    "delivery_failed",
                    sink=sink_name,
                    attempts=attempts,
                    status=status,
                    retry_in_s=round(delay, 2),
                    error=str(exc)[:200],
                )
                updates.append(
                    {
                        "event_id": event["event_id"],
                        "sink": sink_name,
                        "status": status,
                        "attempts": attempts,
                        "error": str(exc)[:200],
                    }
                )
            else:
                await conn.execute(
                    "UPDATE deliveries SET status = 'delivered', attempts = %s,"
                    " delivered_at = now(), last_error = NULL WHERE id = %s",
                    (attempts, row["id"]),
                )
                updates.append(
                    {
                        "event_id": event["event_id"],
                        "sink": sink_name,
                        "status": "delivered",
                        "attempts": attempts,
                    }
                )
    for update in updates:  # publish only after the commit, so the UI never runs ahead
        await redis.publish(UI_CHANNEL, json.dumps({"type": "delivery", **update}))
    return len(rows)
