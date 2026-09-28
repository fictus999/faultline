# Operating Faultline

Faultline observes itself through `GET /metrics` on the API (Prometheus text format). The alert
rules in `observability/alerts.yml` fire on the conditions below; each links to its entry here.

## Service level objectives

| SLI | Metric | Objective | Why |
| --- | --- | --- | --- |
| Freshness (primary) | `faultline_detector_stats_age_seconds` | under 5 s | The detector evaluates every second. Stale output means incidents go unseen. |
| Detection latency | `faultline_last_detection_latency_seconds` | under 10 s | Injected failure to open alert. Measured 2.6 s in the local demo run. |
| Delivery latency | `faultline_outbox_oldest_age_seconds` | under 60 s | 60 s is the retry backoff cap. Anything older means a sink is failing. |
| Completeness | `faultline_lines_lost` | no increase | Sequence-number gaps mean log lines never reached the detector. |

Error-budget burn for the monitored services uses a 99.5% success SLO: CRITICAL at 14.4x burn
and HIGH at 6x, each on both the 10 s and 60 s windows (the Google SRE multiwindow thresholds).

## Detector stale

`FaultlineDetectorStale` or `FaultlineScrapeDown`.

1. `docker compose ps` shows which container is down or restarting.
2. `docker compose logs --tail=100 detector` shows the last error. Redis outages show as connection errors.
3. `docker compose restart detector`. The detector reads new stream entries only and rebuilds
   its baselines in about 10 s. During warm-up only the burn-rate rules (HIGH, CRITICAL) can
   open an alert; the z-score rule (MEDIUM) waits for the baseline.

## Outbox backlog

`FaultlineOutboxBacklog`: an alert event has waited over 60 s.

1. `curl -s 127.0.0.1:8080/api/state` shows each delivery's `last_error` and `attempts` per sink.
2. If the notifier is down, `make start-notifier`. The outbox drains CRITICAL first; nothing is lost.
3. If a sink is failing, fix the sink. Deliveries retry with full-jitter backoff, up to 60 s apart.

## Dead letters

`FaultlineDeadLetters`: a delivery used all 8 attempts. Re-drive once the sink is healthy.
Consumers dedupe by `event_id`, so a re-drive is safe.

```bash
docker compose exec postgres psql -U faultline -d faultline -c \
  "UPDATE deliveries SET status = 'retry', attempts = 0, next_attempt_at = now() WHERE status = 'dead';"
```

## Lines lost

`FaultlineLinesLost`: sequence gaps in the application logs.

1. `docker compose logs --tail=100 collector` shows parse errors, rotation and truncation.
2. The collector resumes from its checkpoint (file inode and offset in Redis) after a restart,
   so gaps usually come from lines dropped upstream of Faultline.
