# Faultline

Real-time log anomaly detection that finds the failing service, not just the failing average.

> **Status: working vertical slice.** Logs flow through Redis Streams to a sliding-window detector; alert events go through a Postgres outbox to every sink and live to the console.

## Run the demo

Requires Docker Desktop.

```bash
cp .env.example .env     # set FAULTLINE_WEBHOOK_SECRET; add AWS settings for SNS/CloudWatch
make up                  # console at http://127.0.0.1:8080; wait ~20 s for baselines to warm up
make inject              # payments starts failing: MEDIUM -> HIGH -> CRITICAL within ~15 s
make kill-notifier       # alert events now queue in the Postgres outbox
make recover             # payments recovers; the RESOLVED event queues too
make start-notifier      # the outbox drains, CRITICAL first
make reset               # wipe everything and start clean
```

Self-observability: `curl 127.0.0.1:8080/metrics` (Prometheus format: detector freshness, outbox
depth and age, burn rates, detection and delivery latency). Optional dashboards:
`docker compose --profile observability up -d`, then Prometheus at http://127.0.0.1:9090 and
Grafana at http://127.0.0.1:3000.

n8n (downstream human workflow only): `make n8n` imports `integrations/n8n/faultline-intake.json`,
which verifies the HMAC signature, rejects replays older than 300 s, dedupes by `event_id` and
routes CRITICAL to paging and RESOLVED to incident close. Executions are visible at
http://127.0.0.1:5678.

SLOs, self-alerts and runbook: [docs/runbook.md](docs/runbook.md). Security controls and known gaps:
[SECURITY.md](SECURITY.md).

Delivery guarantee: zero loss inside the outbox, exactly one delivery record per `(event_id, sink)`
(`UNIQUE (event_id, sink)` in `db/schema.sql`), and a stable `event_id` on every message.
Exactly-once physical delivery to external sinks is not claimed: SNS and CloudWatch are
at-least-once, and consumers dedupe by `event_id`.

## Processes

Faultline runs as four processes built from one Python package, each with its own entrypoint.

| Process | Owns |
| --- | --- |
| `collector` | Tailing application logs, parsing and redacting lines, publishing events |
| `detector` | Per-service sliding windows, baselines, severity and alert state |
| `notifier` | Delivering alert events from the outbox to CloudWatch, SNS and n8n |
| `api` | The REST and WebSocket API behind the operations console |

## Development

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 itself if it is missing.

```bash
uv sync                          # create .venv and install dependencies
uv run faultline detector        # run one process; Ctrl-C stops it cleanly
uv run pytest                    # tests
uv run ruff check .              # lint
uv run ruff format --check .     # formatting
uv run mypy                      # strict type checks
```
