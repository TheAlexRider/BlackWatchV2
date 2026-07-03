-- RDS session tracking + auth-failure history.
--
-- Fed by the aws_rds.py adapter (parses Postgres postgresql.log +
-- proxy log lines forwarded via CloudWatch Logs subscription filter).
-- The projection maintains active sessions here so the UI can show
-- "who's connected to prod right now" and per-user history.

CREATE TABLE IF NOT EXISTS rds_active_sessions (
    -- Composite key: one row per active connection.
    -- backend_pid comes from Postgres `[%p]` in the log_line_prefix; for
    -- RDS Proxy connections we use the clientConnection id instead.
    session_id           TEXT         PRIMARY KEY,
    db_instance          TEXT         NOT NULL,
    source_type          TEXT         NOT NULL,             -- 'postgres' | 'rds_proxy'
    db_user              TEXT,
    db_name              TEXT,
    source_ip            TEXT,
    source_port          INT,
    connected_at         TIMESTAMPTZ  NOT NULL,
    last_seen_at         TIMESTAMPTZ  NOT NULL,             -- updated on each snapshot / event
    disconnected_at      TIMESTAMPTZ,                        -- NULL = still open
    duration_seconds     INT,                                -- populated on disconnect
    extra                JSONB
);

CREATE INDEX IF NOT EXISTS rds_active_sessions_db          ON rds_active_sessions (db_instance);
CREATE INDEX IF NOT EXISTS rds_active_sessions_user        ON rds_active_sessions (db_user);
CREATE INDEX IF NOT EXISTS rds_active_sessions_connected   ON rds_active_sessions (connected_at DESC);
CREATE INDEX IF NOT EXISTS rds_active_sessions_open        ON rds_active_sessions (db_instance)
    WHERE disconnected_at IS NULL;
