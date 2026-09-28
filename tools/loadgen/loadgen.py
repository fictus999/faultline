"""Seeded log generator: the demo and test harness, not a product service.

Writes realistic log lines for five services. A failure is injected by setting
``faultline:chaos:<service>`` in Redis (the console's chaos buttons do this), which
overrides that service's error rate until the key is deleted.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import UTC, datetime
from pathlib import Path

import redis

# service: (lines per second, normal error rate)
SERVICES = {
    "payments": (20, 0.003),
    "auth": (40, 0.002),
    "search": (60, 0.004),
    "checkout": (30, 0.003),
    "inventory": (30, 0.002),
}
ERRORS = {
    "payments": "db pool exhausted: timeout acquiring connection",
    "auth": "token validation failed: upstream timeout",
    "search": "index shard unavailable",
    "checkout": "payment authorization declined by gateway",
    "inventory": "stock reservation conflict",
}
TICK = 0.1


def main() -> None:
    rng = random.Random(int(os.environ.get("FAULTLINE_SEED", "42")))  # noqa: S311
    r = redis.Redis.from_url(
        os.environ.get("FAULTLINE_REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    path = Path(os.environ.get("FAULTLINE_LOG_PATH", "var/log/app.log"))
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = dict.fromkeys(SERVICES, 0)
    carry = dict.fromkeys(SERVICES, 0.0)
    overrides: dict[str, float] = {}
    next_refresh = 0.0
    with path.open("a", encoding="utf-8") as out:
        while True:
            now = time.time()
            if now >= next_refresh:
                overrides = read_overrides(r)
                next_refresh = now + 0.5
            for service, (rate, base_error) in SERVICES.items():
                carry[service] += rate * TICK
                count = int(carry[service])
                carry[service] -= count
                error_rate = overrides.get(service, base_error)
                for _ in range(count):
                    seq[service] += 1
                    ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    if rng.random() < error_rate:
                        latency = rng.randint(800, 3000)
                        out.write(
                            f"{ts} level=ERROR service={service} seq={seq[service]}"
                            f' latency_ms={latency} msg="{ERRORS[service]}"\n'
                        )
                    else:
                        latency = rng.randint(5, 120)
                        out.write(
                            f"{ts} level=INFO service={service} seq={seq[service]}"
                            f' latency_ms={latency} msg="GET /{service} 200"\n'
                        )
            out.flush()
            time.sleep(TICK)


def read_overrides(r: redis.Redis) -> dict[str, float]:
    names = list(SERVICES)
    try:
        values = r.mget([f"faultline:chaos:{name}" for name in names])
    except redis.RedisError:
        return {}
    return {
        name: float(json.loads(value)["error_rate"])
        for name, value in zip(names, values, strict=True)
        if value
    }


if __name__ == "__main__":
    main()
