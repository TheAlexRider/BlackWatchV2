-- File Integrity Monitoring (FIM) read-models.
--
-- The agent maintains its own per-host SQLite baseline for fast local diffing
-- and emits per-file change events (host.fim.*) when it sees drift. These
-- tables are the *server-side* canonical view that the UI reads from:
--
--   fim_baselines   one row per (instance_id, path) = current known-good state
--   fim_history     append-only log of every change observation (compliance evidence)
--   fim_coverage    summary per instance (how many paths, when last scanned)
--
-- All idempotent; existing migrations are untouched.

CREATE TABLE IF NOT EXISTS fim_baselines (
    instance_id     TEXT        NOT NULL,
    path            TEXT        NOT NULL,
    sha256          TEXT        NOT NULL,
    size            BIGINT      NOT NULL,
    perm            SMALLINT    NOT NULL,
    owner_uid       INT         NOT NULL,
    owner_gid       INT         NOT NULL,
    mtime           TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL,
    established_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (instance_id, path)
);

-- Append-only change log. Joins back to events.event_id for full context.
CREATE TABLE IF NOT EXISTS fim_history (
    id              BIGSERIAL   PRIMARY KEY,
    instance_id     TEXT        NOT NULL,
    path            TEXT        NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL,
    change_type     TEXT        NOT NULL,
    sha256_before   TEXT,
    sha256_after    TEXT,
    size_before     BIGINT,
    size_after      BIGINT,
    perm_before     SMALLINT,
    perm_after      SMALLINT,
    owner_before    TEXT,
    owner_after     TEXT,
    event_id        UUID
);
CREATE INDEX IF NOT EXISTS fim_history_instance_changed_at
    ON fim_history (instance_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS fim_history_path
    ON fim_history (instance_id, path, changed_at DESC);

-- One row per host. Lets the UI show "324 files monitored, last scan 3h ago"
-- without recomputing from fim_baselines on every page load.
CREATE TABLE IF NOT EXISTS fim_coverage (
    instance_id          TEXT        PRIMARY KEY,
    paths_configured     INT         NOT NULL DEFAULT 0,
    files_tracked        INT         NOT NULL DEFAULT 0,
    last_full_scan_at    TIMESTAMPTZ,
    last_scan_duration_ms INT,
    scan_errors          INT         NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL
);
