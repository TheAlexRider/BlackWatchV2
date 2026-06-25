-- Connectors: telemetry sources BlackWatch actively pulls from on a schedule
-- (configured from the UI). `verified` flips true after a successful test/run
-- and is what unlocks Run-now / scheduling. Secrets are NOT stored here — the
-- config holds a key *path* to a mounted file, never the key itself. Idempotent.

CREATE TABLE IF NOT EXISTS connectors (
    id          TEXT PRIMARY KEY,
    name        TEXT        NOT NULL,
    type        TEXT        NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT false,
    verified    BOOLEAN     NOT NULL DEFAULT false,
    config      JSONB       NOT NULL DEFAULT '{}',
    last_run_at TIMESTAMPTZ,
    last_status TEXT,
    last_error  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
