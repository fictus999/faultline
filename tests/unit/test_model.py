from faultline.detector.model import (
    RESOLVE_AFTER_TICKS,
    Assessment,
    ServiceState,
    Severity,
)


def assessment(severity: Severity | None, *, z: float = 0.0, burn: float = 0.0) -> Assessment:
    return Assessment(0.0, 0.0, 0.003, z, burn, burn, 200, severity)


def test_alert_opens_escalates_and_resolves() -> None:
    state = ServiceState()
    types = []
    ticks = [Severity.MEDIUM, Severity.MEDIUM, Severity.HIGH, Severity.HIGH, Severity.CRITICAL]
    for i, sev in enumerate(ticks):
        t = state.step(assessment(sev, z=10, burn=20), now=float(i))
        if t:
            types.append((t.type, t.severity))
    for i in range(RESOLVE_AFTER_TICKS):
        t = state.step(assessment(None), now=100.0 + i)
        if t:
            types.append((t.type, t.severity))
    assert types == [
        ("CREATED", Severity.MEDIUM),
        ("ESCALATED", Severity.HIGH),
        ("ESCALATED", Severity.CRITICAL),
        ("RESOLVED", Severity.CRITICAL),
    ]


def test_a_one_tick_blip_does_not_open_an_alert() -> None:
    state = ServiceState()
    assert state.step(assessment(Severity.MEDIUM, z=5, burn=3), now=0) is None
    assert state.step(assessment(None), now=1) is None
    assert state.alert is None


def test_baseline_freezes_while_an_alert_is_open() -> None:
    state = ServiceState()
    state.step(assessment(Severity.HIGH, z=10, burn=8), now=0)
    state.step(assessment(Severity.HIGH, z=10, burn=8), now=1)
    samples = state.baseline.samples
    state.step(assessment(Severity.HIGH, z=10, burn=8), now=2)
    assert state.alert is not None
    assert state.baseline.samples == samples
