import json

import pytest
import structlog

from faultline.common.logs import configure_logging


def test_every_line_is_json_with_the_shared_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(service="detector")
    structlog.get_logger().info("window_advanced", buckets=3)

    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert record["service"] == "detector"
    assert record["event"] == "window_advanced"
    assert record["level"] == "info"
    assert record["ts"].endswith("Z")
    assert record["buckets"] == 3


def test_lines_below_the_configured_level_are_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(service="detector", level="WARNING")
    structlog.get_logger().info("noise")
    assert capsys.readouterr().out == ""


def test_rejects_an_unknown_level() -> None:
    with pytest.raises(ValueError, match="unknown log level"):
        configure_logging(service="detector", level="LOUD")
