"""Console API: REST snapshot, live WebSocket feed, demo controls, webhook receiver."""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import psycopg
import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from faultline.common.config import (
    CHAOS_PREFIX,
    SERVICE_NAME,
    SINK_CHAOS_PREFIX,
    STATS_KEY,
    UI_CHANNEL,
    Config,
)
from faultline.common.signing import verify

log = structlog.get_logger()

RECENT_ALERTS = """
SELECT coalesce(json_agg(a ORDER BY a.opened_at DESC), '[]'::json) FROM (
  SELECT al.alert_id, al.service, al.rule, al.severity, al.status, al.opened_at,
         al.resolved_at, al.injected_at,
         (SELECT coalesce(json_agg(json_build_object(
                    'event_id', e.event_id, 'type', e.type, 'severity', e.severity,
                    'created_at', e.created_at,
                    'deliveries', (SELECT coalesce(json_agg(json_build_object(
                                      'sink', d.sink, 'status', d.status, 'attempts', d.attempts,
                                      'delivered_at', d.delivered_at, 'last_error', d.last_error)
                                      ORDER BY d.sink), '[]'::json)
                                   FROM deliveries d WHERE d.event_id = e.event_id))
                  ORDER BY e.created_at), '[]'::json)
          FROM alert_events e WHERE e.alert_id = al.alert_id) AS events
  FROM alerts al ORDER BY al.opened_at DESC LIMIT 20
) a
"""


OUTBOX_METRICS = """
SELECT
  (SELECT count(*) FROM deliveries WHERE status IN ('pending', 'retry')),
  (SELECT coalesce(extract(epoch FROM now() - min(created_at)), 0)
     FROM deliveries WHERE status IN ('pending', 'retry')),
  (SELECT count(*) FROM alerts WHERE status = 'FIRING'),
  (SELECT coalesce(sum(attempts - 1), 0) FROM deliveries WHERE attempts > 1),
  (SELECT extract(epoch FROM opened_at - injected_at) FROM alerts
     WHERE injected_at IS NOT NULL ORDER BY opened_at DESC LIMIT 1),
  (SELECT extract(epoch FROM avg(d.delivered_at - e.created_at)) FROM deliveries d
     JOIN alert_events e ON e.event_id = d.event_id
     WHERE d.delivered_at > now() - interval '1 hour'),
  (SELECT coalesce(json_agg(json_build_array(sink, status, n)), '[]'::json)
     FROM (SELECT sink, status, count(*) AS n FROM deliveries GROUP BY sink, status) s)
"""


def _metric(lines: list[str], name: str, help_text: str, samples: list[tuple[str, float]]) -> None:
    """Append one metric in the Prometheus text exposition format."""
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    lines.extend(f"{name}{labels} {value}" for labels, value in samples)


class ChaosRequest(BaseModel):
    error_rate: float = Field(ge=0.0, le=1.0)


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Faultline console API")
    redis = Redis.from_url(cfg.redis_url, decode_responses=True)

    async def recent_alerts() -> Any:
        async with await psycopg.AsyncConnection.connect(cfg.database_url) as conn:
            cur = await conn.execute(RECENT_ALERTS)
            row = await cur.fetchone()
            return row[0] if row else []

    async def snapshot() -> dict[str, Any]:
        stats = await redis.get(STATS_KEY)
        return {"stats": json.loads(stats) if stats else None, "alerts": await recent_alerts()}

    def require_demo_mode() -> None:
        if not cfg.demo_mode:
            raise HTTPException(status_code=404)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        """Faultline observing itself: detector signals from Redis, outbox health from Postgres."""
        lines: list[str] = []
        raw = await redis.get(STATS_KEY)
        empty: dict[str, Any] = {"ts": 0, "global_rate": 0, "services": []}
        stats: dict[str, Any] = json.loads(raw) if raw else empty
        svcs = stats["services"]
        _metric(
            lines,
            "faultline_detector_stats_age_seconds",
            "Seconds since the detector last evaluated (freshness)",
            [("", round(time.time() - stats["ts"], 3))],
        )
        _metric(
            lines,
            "faultline_global_error_rate",
            "Error rate across all services, short window",
            [("", stats["global_rate"])],
        )
        rates = [(f'{{service="{s["service"]}",window="short"}}', s["rate"]) for s in svcs]
        rates += [(f'{{service="{s["service"]}",window="long"}}', s["long_rate"]) for s in svcs]
        _metric(lines, "faultline_error_rate", "Error rate per service", rates)
        _metric(
            lines,
            "faultline_baseline_error_rate",
            "Learned EWMA baseline per service",
            [(f'{{service="{s["service"]}"}}', s["baseline"]) for s in svcs],
        )
        _metric(
            lines,
            "faultline_anomaly_zscore",
            "Deviation from baseline in sigmas",
            [(f'{{service="{s["service"]}"}}', s["z"]) for s in svcs],
        )
        burns = [(f'{{service="{s["service"]}",window="short"}}', s["burn_short"]) for s in svcs]
        burns += [(f'{{service="{s["service"]}",window="long"}}', s["burn_long"]) for s in svcs]
        _metric(lines, "faultline_burn_rate", "SLO error-budget burn rate", burns)
        _metric(
            lines,
            "faultline_lines_lost",
            "Log lines missing from sequence numbers",
            [(f'{{service="{s["service"]}"}}', s["lines_lost"]) for s in svcs],
        )
        async with await psycopg.AsyncConnection.connect(cfg.database_url) as conn:
            cur = await conn.execute(OUTBOX_METRICS)
            row = await cur.fetchone()
        assert row is not None  # noqa: S101 - a SELECT without FROM always returns one row
        depth, oldest, firing, retries, detect, deliver, per_sink = row
        _metric(lines, "faultline_outbox_depth", "Deliveries waiting to be sent", [("", depth)])
        _metric(
            lines,
            "faultline_outbox_oldest_age_seconds",
            "Age of the oldest waiting delivery",
            [("", round(float(oldest), 3))],
        )
        _metric(lines, "faultline_alerts_firing", "Open alerts", [("", firing)])
        _metric(lines, "faultline_delivery_retries", "Delivery retries so far", [("", retries)])
        if detect is not None:
            _metric(
                lines,
                "faultline_last_detection_latency_seconds",
                "Injected failure to alert, last incident",
                [("", round(float(detect), 3))],
            )
        if deliver is not None:
            _metric(
                lines,
                "faultline_avg_delivery_latency_seconds",
                "Event to sink acknowledgement, last hour",
                [("", round(float(deliver), 3))],
            )
        _metric(
            lines,
            "faultline_deliveries",
            "Delivery records by sink and status",
            [(f'{{sink="{sink}",status="{status}"}}', n) for sink, status, n in per_sink],
        )
        return "\n".join(lines) + "\n"

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return await snapshot()

    @app.post("/api/chaos/services/{service}")
    async def inject(service: str, body: ChaosRequest) -> dict[str, Any]:
        require_demo_mode()
        if not SERVICE_NAME.match(service):
            raise HTTPException(status_code=422, detail="invalid service name")
        value = {"error_rate": body.error_rate, "injected_at": time.time()}
        await redis.set(CHAOS_PREFIX + service, json.dumps(value))
        await redis.publish(UI_CHANNEL, json.dumps({"type": "chaos", "service": service, **value}))
        return value

    @app.delete("/api/chaos/services/{service}")
    async def recover(service: str) -> dict[str, str]:
        require_demo_mode()
        await redis.delete(CHAOS_PREFIX + service)
        await redis.publish(
            UI_CHANNEL, json.dumps({"type": "chaos", "service": service, "error_rate": None})
        )
        return {"status": "recovered"}

    @app.post("/api/chaos/sinks/{sink}")
    async def break_sink(sink: str) -> dict[str, str]:
        require_demo_mode()
        if not SERVICE_NAME.match(sink):
            raise HTTPException(status_code=422, detail="invalid sink name")
        await redis.set(SINK_CHAOS_PREFIX + sink, "1")
        return {"status": "failing"}

    @app.delete("/api/chaos/sinks/{sink}")
    async def heal_sink(sink: str) -> dict[str, str]:
        require_demo_mode()
        await redis.delete(SINK_CHAOS_PREFIX + sink)
        return {"status": "healthy"}

    @app.post("/api/demo/webhook-receiver")
    async def webhook_receiver(request: Request) -> dict[str, Any]:
        """Stands in for n8n: verifies the HMAC signature and dedupes by event_id."""
        body = await request.body()
        ok = verify(
            cfg.webhook_secret,
            request.headers.get("X-Faultline-Timestamp", ""),
            body,
            request.headers.get("X-Faultline-Signature", ""),
            time.time(),
        )
        if not ok:
            raise HTTPException(status_code=401, detail="bad signature")
        event_id = json.loads(body)["event_id"]
        first = await redis.set(f"faultline:webhook-seen:{event_id}", "1", nx=True, ex=3600)
        await redis.publish(
            UI_CHANNEL,
            json.dumps({"type": "webhook_received", "event_id": event_id, "duplicate": not first}),
        )
        return {"received": event_id, "duplicate": not first}

    @app.websocket("/ws")
    async def feed(websocket: WebSocket) -> None:
        # TODO(security): authenticate the WebSocket (token in the first message).
        await websocket.accept()
        pubsub = redis.pubsub()
        await pubsub.subscribe(UI_CHANNEL)
        try:
            await websocket.send_text(
                json.dumps({"type": "snapshot", **await snapshot()}, default=str)
            )
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    await websocket.send_text(message["data"])
        except Exception:  # client went away or the connection broke
            log.info("ws_client_disconnected")
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(UI_CHANNEL)
                await pubsub.aclose()  # type: ignore[no-untyped-call]

    frontend = Path(cfg.frontend_dir)
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
