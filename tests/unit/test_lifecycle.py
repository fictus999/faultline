import asyncio
import signal

import pytest

from faultline.common.lifecycle import run_until_stopped


def _send_sigterm_soon() -> None:
    asyncio.get_running_loop().call_later(0.05, signal.raise_signal, signal.SIGTERM)


def test_sigterm_lets_the_process_finish_cleanly() -> None:
    steps: list[str] = []

    async def process(stop: asyncio.Event) -> None:
        steps.append("started")
        await stop.wait()
        steps.append("finished")

    async def scenario() -> None:
        _send_sigterm_soon()
        await run_until_stopped(process)

    asyncio.run(scenario())
    assert steps == ["started", "finished"]


def test_a_process_that_ignores_stop_is_cancelled_after_the_timeout() -> None:
    cancelled = False

    async def stubborn(stop: asyncio.Event) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def scenario() -> None:
        _send_sigterm_soon()
        await run_until_stopped(stubborn, shutdown_timeout=0.1)

    asyncio.run(scenario())
    assert cancelled


def test_a_crash_propagates_so_the_container_restarts() -> None:
    async def broken(stop: asyncio.Event) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run_until_stopped(broken))


def test_signal_handlers_are_removed_after_shutdown() -> None:
    async def instant(stop: asyncio.Event) -> None:
        return None

    async def scenario() -> None:
        await run_until_stopped(instant)
        assert not asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)

    asyncio.run(scenario())
