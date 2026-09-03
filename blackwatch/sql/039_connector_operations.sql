-- Connector execution operations and scheduler observability.
-- Additive only: never remove connector configuration, evidence, or history.

ALTER TABLE connectors
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE connectors
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
ALTER TABLE connectors
    ADD COLUMN IF NOT EXISTS scheduler_reason TEXT;

CREATE TABLE IF NOT EXISTS connector_operations (
    operation_id          TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL,
    connector_id          TEXT,
    parent_operation_id   TEXT,
    status                TEXT NOT NULL,
    correlation_id        TEXT NOT NULL,
    requested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_attempt_at       TIMESTAMPTZ,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt               INTEGER NOT NULL DEFAULT 0,
    duration_ms           INTEGER,
    outcome               JSONB NOT NULL DEFAULT '{}',
    error_category        TEXT,
    error_message         TEXT,
    created_by            TEXT
);

CREATE INDEX IF NOT EXISTS idx_connector_operations_connector_time
    ON connector_operations (connector_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_connector_operations_parent_time
    ON connector_operations (parent_operation_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_connector_operations_active
    ON connector_operations (connector_id, status)
    WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS connector_scheduler_state (
    id                  TEXT PRIMARY KEY,
    heartbeat_at        TIMESTAMPTZ,
    last_tick_at        TIMESTAMPTZ,
    next_tick_at        TIMESTAMPTZ,
    last_error          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO connector_scheduler_state (id)
VALUES ('default')
ON CONFLICT (id) DO NOTHING;
