-- Faultline schema. Applied by Postgres on first start (docker-entrypoint-initdb.d).

CREATE TABLE alerts (
    alert_id    uuid PRIMARY KEY,
    service     text NOT NULL,
    rule        text NOT NULL,
    severity    text NOT NULL,
    status      text NOT NULL CHECK (status IN ('FIRING', 'RESOLVED')),
    opened_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    injected_at timestamptz,  -- demo only: when the failure was injected, for detection latency
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- At most one open alert per service and rule.
CREATE UNIQUE INDEX one_firing_alert_per_service_rule ON alerts (service, rule)
    WHERE status = 'FIRING';

-- One alert emits several events (CREATED, ESCALATED, RESOLVED).
CREATE TABLE alert_events (
    event_id      uuid PRIMARY KEY,
    alert_id      uuid NOT NULL REFERENCES alerts (alert_id),
    type          text NOT NULL CHECK (type IN ('CREATED', 'ESCALATED', 'RESOLVED')),
    severity      text NOT NULL,
    severity_rank int NOT NULL,
    payload       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alert_events_by_alert ON alert_events (alert_id, created_at);

-- The outbox. Rows are written in the same transaction as the event, so an event can
-- never exist without its deliveries. Every event is delivered independently to every
-- sink: the guarantee is one delivery record per (event_id, sink), not per alert.
CREATE TABLE deliveries (
    id              bigserial PRIMARY KEY,
    event_id        uuid NOT NULL REFERENCES alert_events (event_id),
    sink            text NOT NULL,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'retry', 'delivered', 'dead')),
    attempts        int NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    delivered_at    timestamptz,
    CONSTRAINT one_delivery_per_event_per_sink UNIQUE (event_id, sink)
);
CREATE INDEX deliveries_due ON deliveries (next_attempt_at) WHERE status IN ('pending', 'retry');
