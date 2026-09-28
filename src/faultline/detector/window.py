"""Sliding-window error rate: a ring buffer of 1-second buckets with running sums.

One ring sized for the long window keeps two running sums: every bucket (long window)
and the newest ``short`` buckets (short window). Advancing the head subtracts the bucket
leaving each window, so each event costs O(1) amortized and memory is fixed by the window
length, not by traffic. The naive alternative rescans every event in the window per event,
O(N x W); it survives in the tests as the correctness oracle.
"""

from __future__ import annotations


class RingWindow:
    def __init__(self, long_buckets: int = 60, short_buckets: int = 10) -> None:
        if not 0 < short_buckets <= long_buckets:
            raise ValueError("need 0 < short_buckets <= long_buckets")
        self.size = long_buckets
        self.short = short_buckets
        self.totals = [0] * long_buckets
        self.errors = [0] * long_buckets
        self.head: int | None = None  # the newest second in the window
        self.long_total = self.long_errors = 0
        self.short_total = self.short_errors = 0
        self.late = 0  # events older than the long window, dropped

    def add(self, second: int, is_error: bool) -> None:
        if self.head is None:
            self.head = second
        elif second > self.head:
            self.advance(second)
        elif second <= self.head - self.size:
            self.late += 1
            return
        err = 1 if is_error else 0
        slot = second % self.size
        self.totals[slot] += 1
        self.errors[slot] += err
        self.long_total += 1
        self.long_errors += err
        if second > self.head - self.short:
            self.short_total += 1
            self.short_errors += err

    def advance(self, second: int) -> None:
        """Move the head to ``second``, expiring buckets that fall out of each window."""
        if self.head is None:
            self.head = second
            return
        steps = second - self.head
        if steps <= 0:
            return
        if steps >= self.size:  # a gap longer than the window: everything expired
            self.totals = [0] * self.size
            self.errors = [0] * self.size
            self.long_total = self.long_errors = self.short_total = self.short_errors = 0
            self.head = second
            return
        for entering in range(self.head + 1, second + 1):
            leaving_short = (entering - self.short) % self.size
            self.short_total -= self.totals[leaving_short]
            self.short_errors -= self.errors[leaving_short]
            slot = entering % self.size  # this slot still holds the second leaving the long window
            self.long_total -= self.totals[slot]
            self.long_errors -= self.errors[slot]
            self.totals[slot] = self.errors[slot] = 0
        self.head = second

    @property
    def short_rate(self) -> float:
        return self.short_errors / self.short_total if self.short_total else 0.0

    @property
    def long_rate(self) -> float:
        return self.long_errors / self.long_total if self.long_total else 0.0
