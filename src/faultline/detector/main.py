"""Detector process body: read the stream, keep per-service windows, emit alert events."""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, cast

import psycopg
import structlog
from redis.asyncio import Redis

from faultline.common.config import (
    CHAOS_PREFIX,
    LOG_STREAM,
    SERVICE_NAME,
    STATS_KEY,
    UI_CHANNEL,
    Config,
)
from faultline.detector import outbox
from faultline.detector.model import ServiceState, assess

log = structlog.get_logger()
MAX_SERVICES = 256  # bounded per-service state: least recently seen services are evicted
PRODUCER_RESTART_GAP = 1000


class Detector:
    def __init__(self) -> None:
        self.states: OrderedDict[str, ServiceState] = OrderedDict()

    def state_for(self, service: str) -> ServiceState:
        state = self.states.get(service)
        if state is None:
            if len(self.states) >= MAX_SERVICES:
                evicted, _ = self.states.popitem(last=False)
                log.warning("service_state_evicted", evicted=evicted)
            state = self.states[service] = ServiceState()
        else:
            self.states.move_to_end(service)
        return state

    def ingest(self, fields: dict[str, str]) -> None:
        service = fields.get("service", "")
        if not SERVICE_NAME.match(service):
            return
        state = self.state_for(service)
        seq = int(fields.get("seq", 0))
        if state.last_seq and seq <= state.last_seq:
            if state.last_seq - seq < PRODUCER_RESTART_GAP:
                return  # a replayed line: already counted
        elif state.last_seq and seq > state.last_seq + 1:
            state.lines_lost += seq - state.last_seq - 1
        state.last_seq = seq
        state.window.add(int(float(fields["ts"])), fields.get("error") == "1")


async def run(stop: asyncio.Event) -> None:
    cfg = Config.from_env()
    redis = Redis.from_url(cfg.redis_url, decode_responses=True)
    conn = await psycopg.AsyncConnection.connect(cfg.database_url, autocommit=True)
    detector = Detector()
    last_id = "$"
    next_tick = time.time() + 1
    log.info("detector_ready", sinks=cfg.sinks)
    try:
        while not stop.is_set():
            batches = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await redis.xread({LOG_STREAM: last_id}, count=5000, block=200),
            )
            for _stream, entries in batches:
                for entry_id, fields in entries:
                    last_id = entry_id
                    detector.ingest(fields)
            now = time.time()
            if now >= next_tick:
                next_tick = now + 1
                await evaluate(detector, cfg, redis, conn, now)
    finally:
        await conn.close()
        await redis.aclose()


async def evaluate(
    detector: Detector, cfg: Config, redis: Redis, conn: psycopg.AsyncConnection[Any], now: float
) -> None:
    second = int(now)
    services: list[dict[str, Any]] = []
    errors = total = 0
    for service, state in detector.states.items():
        state.window.advance(second)
        a = assess(state.window, state.baseline)
        errors += state.window.short_errors
        total += state.window.short_total
        transition = state.step(a, now)
        if transition is not None:
            injected_at = None
            chaos = await redis.get(CHAOS_PREFIX + service)
            if chaos:
                injected_at = json.loads(chaos).get("injected_at")
            try:
                event = await outbox.record(
                    conn, service, transition, a, cfg.sinks, injected_at, now
                )
            except psycopg.Error:
                log.exception("outbox_write_failed", service=service, type=transition.type)
            else:
                log.info("alert_event", **{k: event[k] for k in ("type", "service", "severity")})
                await redis.publish(UI_CHANNEL, json.dumps({"type": "alert_event", "event": event}))
        services.append(
            {
                "service": service,
                "rate": round(a.short_rate, 4),
                "long_rate": round(a.long_rate, 4),
                "baseline": round(a.baseline, 4),
                "z": round(a.z, 1),
                "burn_short": round(a.burn_short, 1),
                "burn_long": round(a.burn_long, 1),
                "events": a.events_short,
                "severity": state.alert.severity.name if state.alert else None,
                "lines_lost": state.lines_lost,
            }
        )
    stats = {
        "type": "stats",
        "ts": now,
        "global_rate": round(errors / total, 4) if total else 0.0,
        "services": sorted(services, key=lambda s: s["service"]),
    }
    message = json.dumps(stats)
    await redis.set(STATS_KEY, message)
    await redis.publish(UI_CHANNEL, message)
