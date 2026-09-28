"""Console API process body: serve the FastAPI app with uvicorn until stopped."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator

import uvicorn

from faultline.api.app import create_app
from faultline.common.config import Config


class _Server(uvicorn.Server):
    """Our lifecycle owns SIGTERM/SIGINT, so uvicorn must not install its own handlers."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def run(stop: asyncio.Event) -> None:
    cfg = Config.from_env()
    server = _Server(
        uvicorn.Config(
            create_app(cfg),
            host=cfg.api_host,
            port=cfg.api_port,
            log_config=None,
            access_log=False,
        )
    )
    serving = asyncio.create_task(server.serve())
    await asyncio.wait(
        [serving, asyncio.create_task(stop.wait())], return_when=asyncio.FIRST_COMPLETED
    )
    server.should_exit = True
    await serving
