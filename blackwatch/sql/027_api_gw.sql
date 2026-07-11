-- API Gateway Phase 1 tables.
--
-- api_sources — every real client IP that has ever hit the API Gateway.
-- Same shape as rds_proxy_sources; fed by api.request events (projection-
-- only) so we don't bloat the events table. First-seen IPs fire
-- api.source.new for the operator dashboard.

CREATE TABLE IF NOT EXISTS api_sources (
    source_ip     TEXT PRIMARY KEY,
    api_name      TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_count BIGINT NOT NULL DEFAULT 0,
    -- Rollups for the dashboard, avoids scanning events every render.
    error_4xx_count BIGINT NOT NULL DEFAULT 0,
    error_5xx_count BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_sources_last_seen
    ON api_sources (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_sources_api_name
    ON api_sources (api_name);
