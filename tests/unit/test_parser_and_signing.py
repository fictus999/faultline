import random

from faultline.collector.parser import MAX_LINE, parse
from faultline.common.signing import sign, verify
from faultline.notifier.main import MAX_DELAY, backoff_delay

LINE = '2026-09-28T09:00:00.123Z level=ERROR service=payments seq=42 msg="db pool exhausted"'


def test_parses_a_valid_line() -> None:
    event = parse(LINE)
    assert event is not None
    assert event["service"] == "payments"
    assert event["error"] == "1"
    assert event["seq"] == "42"


def test_redacts_secrets_before_they_leave_the_collector() -> None:
    event = parse(LINE + " key=AKIAABCDEFGHIJKLMNOP user=ops@example.com Bearer abcdefgh12345")
    assert event is not None
    assert "AKIA" not in event["msg"]
    assert "ops@example.com" not in event["msg"]
    assert "abcdefgh12345" not in event["msg"]


def test_control_characters_cannot_forge_a_second_line() -> None:
    event = parse(LINE + "\r2026-09-28T09:00:01Z level=INFO service=auth seq=1 \x1b[2J")
    assert event is not None
    assert "\r" not in event["msg"]
    assert "\x1b" not in event["msg"]


def test_rejects_malformed_and_caps_long_lines() -> None:
    assert parse("not a log line") is None
    assert parse("2026-09-28T09:00:00Z level=ERROR service=BAD seq=1") is None
    event = parse(LINE + "x" * (MAX_LINE * 2))
    assert event is not None
    assert len(event["msg"]) < MAX_LINE


def test_signature_round_trip_and_replay_rejection() -> None:
    body = b'{"event_id":"e1"}'
    signature = sign("secret", "1000", body)
    assert verify("secret", "1000", body, signature, now=1010)
    assert not verify("secret", "1000", body + b" ", signature, now=1010)  # tampered
    assert not verify("wrong", "1000", body, signature, now=1010)  # wrong key
    assert not verify("secret", "1000", body, signature, now=5000)  # stale replay


def test_backoff_is_jittered_and_capped() -> None:
    rng = random.Random(7)
    delays = [backoff_delay(attempt, rng) for attempt in range(1, 12)]
    assert all(0 <= d <= MAX_DELAY for d in delays)
    assert len(set(delays)) == len(delays)
