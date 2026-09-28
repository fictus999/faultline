"""Baseline, severity and the per-service alert state machine.

Detection asks "is this unusual?" (z-score against an EWMA baseline). Severity asks "how
much does it hurt?" (SLO burn rate on a short and a long window, the Google SRE Workbook's
multiwindow method, time-compressed for the demo: 10 s and 60 s instead of 5 min and 1 h).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import IntEnum

from faultline.detector.window import RingWindow

SLO = 0.995
ERROR_BUDGET = 1 - SLO
CRITICAL_BURN = 14.4
HIGH_BURN = 6.0
MEDIUM_Z = 3.0
MEDIUM_MIN_BURN = 2.0  # "unusual" alone isn't enough: also at least 1% errors
SIGMA_MIN = 0.01  # variance floor: a quiet service's first error must not be z = infinity
MIN_EVENTS = 20  # don't score windows with too little traffic
WARMUP_SAMPLES = 10
OPEN_AFTER_TICKS = 2  # anomalous this many seconds in a row before an alert opens
RESOLVE_AFTER_TICKS = 5  # quiet this many seconds in a row before it resolves


class Severity(IntEnum):
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Ewma:
    """Exponentially weighted mean and variance, updated in O(1) per sample."""

    alpha: float = 0.1
    mean: float = 0.0
    var: float = 0.0
    samples: int = 0

    def update(self, x: float) -> None:
        if self.samples == 0:
            self.mean = x
        else:
            diff = x - self.mean
            incr = self.alpha * diff
            self.mean += incr
            self.var = (1 - self.alpha) * (self.var + diff * incr)
        self.samples += 1

    @property
    def sigma(self) -> float:
        return max(math.sqrt(self.var), SIGMA_MIN)


@dataclass(frozen=True)
class Assessment:
    short_rate: float
    long_rate: float
    baseline: float
    z: float
    burn_short: float
    burn_long: float
    events_short: int
    severity: Severity | None


def assess(window: RingWindow, baseline: Ewma) -> Assessment:
    short, long_ = window.short_rate, window.long_rate
    warm = baseline.samples >= WARMUP_SAMPLES
    z = (short - baseline.mean) / baseline.sigma if warm else 0.0
    burn_short, burn_long = short / ERROR_BUDGET, long_ / ERROR_BUDGET
    severity: Severity | None = None
    if window.short_total >= MIN_EVENTS:
        if burn_short >= CRITICAL_BURN and burn_long >= CRITICAL_BURN:
            severity = Severity.CRITICAL
        elif burn_short >= HIGH_BURN and burn_long >= HIGH_BURN:
            severity = Severity.HIGH
        elif z >= MEDIUM_Z and burn_short >= MEDIUM_MIN_BURN:
            severity = Severity.MEDIUM
    return Assessment(
        short, long_, baseline.mean, z, burn_short, burn_long, window.short_total, severity
    )


@dataclass
class OpenAlert:
    alert_id: uuid.UUID
    severity: Severity
    opened_at: float


@dataclass(frozen=True)
class Transition:
    type: str  # CREATED | ESCALATED | RESOLVED
    alert_id: uuid.UUID
    severity: Severity
    opened_at: float


@dataclass
class ServiceState:
    window: RingWindow = field(default_factory=RingWindow)
    baseline: Ewma = field(default_factory=Ewma)
    alert: OpenAlert | None = None
    anomalous_ticks: int = 0
    quiet_ticks: int = 0
    last_seq: int = 0
    lines_lost: int = 0

    def step(self, a: Assessment, now: float) -> Transition | None:
        """Advance the alert state machine by one evaluation tick."""
        if self.alert is None:
            if a.severity is None:
                self.anomalous_ticks = 0
                if a.events_short >= MIN_EVENTS:
                    self.baseline.update(a.short_rate)  # learn only from normal traffic
                return None
            self.anomalous_ticks += 1
            if self.anomalous_ticks < OPEN_AFTER_TICKS:
                return None
            self.anomalous_ticks = self.quiet_ticks = 0
            self.alert = OpenAlert(uuid.uuid4(), a.severity, now)
            return Transition("CREATED", self.alert.alert_id, a.severity, now)

        alert = self.alert  # open: the baseline is frozen so it can't learn the outage
        if a.severity is not None and a.severity > alert.severity:
            alert.severity = a.severity
            self.quiet_ticks = 0
            return Transition("ESCALATED", alert.alert_id, a.severity, alert.opened_at)
        quiet = a.z < 2 and a.burn_short < 1
        self.quiet_ticks = self.quiet_ticks + 1 if quiet else 0
        if self.quiet_ticks < RESOLVE_AFTER_TICKS:
            return None
        self.alert = None
        self.quiet_ticks = 0
        return Transition("RESOLVED", alert.alert_id, alert.severity, alert.opened_at)
