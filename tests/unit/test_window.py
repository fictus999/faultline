import random

import pytest

from faultline.detector.window import RingWindow


def naive_rates(
    events: list[tuple[int, bool]], head: int, short: int, size: int
) -> tuple[float, float]:
    """The O(N x W) oracle: rescan every event for each window."""

    def rate(width: int) -> float:
        inside = [err for sec, err in events if head - width < sec <= head]
        return sum(inside) / len(inside) if inside else 0.0

    return rate(short), rate(size)


@pytest.mark.parametrize("seed", range(25))
def test_ring_matches_the_naive_rescan(seed: int) -> None:
    rng = random.Random(seed)
    window = RingWindow(long_buckets=60, short_buckets=10)
    events: list[tuple[int, bool]] = []
    second = 1_000
    for _ in range(3_000):
        second += rng.choice([0, 0, 0, 1, 1, 2, 5, 70])  # bursts, gaps, long silences
        late = rng.random() < 0.05
        sec = second - rng.randint(0, 80) if late else second
        is_error = rng.random() < 0.2
        window.add(sec, is_error)
        if window.head is not None and sec > window.head - window.size:
            events.append((sec, is_error))
        short, long_ = naive_rates(events, window.head or 0, 10, 60)
        assert window.short_rate == pytest.approx(short)
        assert window.long_rate == pytest.approx(long_)


def test_advancing_past_the_window_clears_it() -> None:
    window = RingWindow(long_buckets=60, short_buckets=10)
    for sec in range(100, 110):
        window.add(sec, True)
    window.advance(500)
    assert window.long_total == window.short_total == 0


def test_events_older_than_the_window_are_counted_as_late() -> None:
    window = RingWindow(long_buckets=60, short_buckets=10)
    window.add(1_000, False)
    window.add(900, True)
    assert window.late == 1
    assert window.long_errors == 0
