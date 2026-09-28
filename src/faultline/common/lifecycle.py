"""Process lifecycle: run until SIGTERM or SIGINT, then shut down cleanly.

Docker stops a container with SIGTERM and kills it after a grace period. Handling the
signal explicitly lets a process finish its current unit of work, and later flush its
state, instead of dying mid-write.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

ProcessMain = Callable[[asyncio.Event], Coroutine[Any, Any, None]]
"""A process body: runs until the given event is set, then returns promptly."""

STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)

log = structlog.get_logger()


async def run_until_stopped(process_main: ProcessMain, *, shutdown_timeout: float = 10.0) -> None:
    """Run ``process_main`` until it returns or a stop signal arrives.

    ``process_main`` receives an event that is set on SIGTERM or SIGINT and must return
    promptly once it is set. If it is still running ``shutdown_timeout`` seconds after
    the signal, it is cancelled. An exception raised by ``process_main`` is logged and
    re-raised, so the process exits non-zero and the container's restart policy acts.
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in STOP_SIGNALS:
        loop.add_signal_handler(sig, _request_stop, stop, sig)
    log.info("process_started")
    body = asyncio.create_task(process_main(stop), name="process_main")
    stop_requested = asyncio.create_task(stop.wait(), name="stop_requested")
    try:
        await asyncio.wait([body, stop_requested], return_when=asyncio.FIRST_COMPLETED)
        if not body.done():
            try:
                async with asyncio.timeout(shutdown_timeout):
                    await asyncio.wait([body])  # waits without raising the body's error
            except TimeoutError:
                log.warning("shutdown_timeout", timeout_s=shutdown_timeout)
                body.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await body
        if not body.cancelled() and (error := body.exception()) is not None:
            log.error("process_crashed", exc_info=error)
            raise error
    finally:
        stop_requested.cancel()
        for sig in STOP_SIGNALS:
            loop.remove_signal_handler(sig)
    log.info("process_stopped")


def _request_stop(stop: asyncio.Event, sig: signal.Signals) -> None:
    if not stop.is_set():
        log.info("stop_requested", signal=sig.name)
    stop.set()
