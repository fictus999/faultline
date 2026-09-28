import asyncio

import pytest

from faultline.cli import PROCESSES, build_parser, main


def test_runs_exactly_the_four_product_processes() -> None:
    # The service boundaries are a deliberate decision. Adding a fifth process should
    # fail here until that decision is revisited.
    assert list(PROCESSES) == ["collector", "detector", "notifier", "api"]


def test_rejects_an_unknown_process(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["loadgen"])
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_a_crashing_process_exits_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(stop: asyncio.Event) -> None:
        raise RuntimeError("boom")

    monkeypatch.setitem(PROCESSES, "detector", broken)
    assert main(["detector"]) == 1
