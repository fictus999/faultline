"""Command-line entrypoint: one package, four independently runnable processes."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from faultline.api.main import run as run_api
from faultline.collector.main import run as run_collector
from faultline.common.lifecycle import ProcessMain, run_until_stopped
from faultline.common.logs import LOG_LEVELS, configure_logging
from faultline.detector.main import run as run_detector
from faultline.notifier.main import run as run_notifier

PROCESSES: dict[str, ProcessMain] = {
    "collector": run_collector,
    "detector": run_detector,
    "notifier": run_notifier,
    "api": run_api,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faultline",
        description="Run one Faultline process until it receives SIGTERM or SIGINT.",
    )
    parser.add_argument("process", choices=list(PROCESSES), help="the process to run")
    parser.add_argument("--log-level", default="INFO", choices=LOG_LEVELS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(service=args.process, level=args.log_level)
    try:
        asyncio.run(run_until_stopped(PROCESSES[args.process]))
    except Exception:
        # Already logged as a structured process_crashed event with its traceback.
        return 1
    return 0
