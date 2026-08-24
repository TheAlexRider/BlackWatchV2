-- Durable investigation jobs and evidence from projection/read-model tables.
-- The worker claims queued jobs with row locks, so a process restart leaves
-- unfinished work queued instead of losing it in an HTTP request.
CREATE TABLE IF NOT EXISTS investigation_scans (
    id UUID PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','complete','failed')),
    requested_by TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result_count INT NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_investigation_scans_queue
    ON investigation_scans (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_investigation_scans_active
    ON investigation_scans (investigation_id) WHERE status IN ('queued','running');

CREATE TABLE IF NOT EXISTS investigation_projection_results (
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    module TEXT NOT NULL,
    category TEXT NOT NULL,
    observed_at TIMESTAMPTZ,
    payload JSONB NOT NULL,
    match_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (investigation_id, source_table, source_key)
);
CREATE INDEX IF NOT EXISTS idx_investigation_projection_results_case
    ON investigation_projection_results (investigation_id, observed_at DESC);
