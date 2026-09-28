"""Collector process body: tail the log file, parse and redact, publish to Redis Streams."""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from redis.asyncio import Redis

from faultline.collector.parser import parse
from faultline.collector.tailer import FileTailer
from faultline.common.config import COLLECTOR_CHECKPOINT_KEY, LOG_STREAM, Config

log = structlog.get_logger()
STREAM_MAXLEN = 200_000


async def run(stop: asyncio.Event) -> None:
    cfg = Config.from_env()
    redis = Redis.from_url(cfg.redis_url, decode_responses=True)
    saved = await redis.hgetall(COLLECTOR_CHECKPOINT_KEY)
    tailer = FileTailer(
        cfg.log_path,
        offset=int(saved.get("offset", 0)),
        inode=int(saved["inode"]) if "inode" in saved else None,
    )
    log.info("tailing", path=cfg.log_path, offset=tailer.offset)
    published = rejected = 0
    try:
        while not stop.is_set():
            lines = tailer.read_lines()
            if not lines:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 0.1)
                continue
            pipe = redis.pipeline(transaction=False)
            for line in lines:
                event = parse(line)
                if event is None:
                    rejected += 1
                    continue
                pipe.xadd(LOG_STREAM, event, maxlen=STREAM_MAXLEN, approximate=True)  # type: ignore[arg-type]
                published += 1
            # Checkpoint after publishing: a crash in between re-sends lines (at-least-once).
            pipe.hset(
                COLLECTOR_CHECKPOINT_KEY,
                mapping={"offset": tailer.offset, "inode": tailer.inode or 0},
            )
            await pipe.execute()
    finally:
        log.info("collector_totals", published=published, rejected=rejected)
        await redis.aclose()
