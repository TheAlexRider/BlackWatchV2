-- BlackWatch core storage. One table holds every normalized event.
-- Hot/queryable fields are promoted to columns; the full envelope and the
-- verbatim raw payload are stored as JSONB. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS events (
    event_id           UUID PRIMARY KEY,
    schema_version     INTEGER     NOT NULL,
    event_time         TIMESTAMPTZ NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    dedup_fingerprint  TEXT        NOT NULL,

    module             TEXT        NOT NULL,
    vendor             TEXT,
    account            TEXT,
    region             TEXT,
    transport          TEXT        NOT NULL,

    category           TEXT        NOT NULL,
    action             TEXT        NOT NULL,
    outcome            TEXT        NOT NULL,

    actor_principal    TEXT,
    actor_type         TEXT,
    actor_is_root      BOOLEAN,
    actor_source_ip    TEXT,

    target_id          TEXT,
    target_type        TEXT,

    severity           TEXT,
    tags               TEXT[]      NOT NULL DEFAULT '{}',

    envelope           JSONB       NOT NULL,
    raw                JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_event_time      ON events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_module          ON events (module);
CREATE INDEX IF NOT EXISTS idx_events_action          ON events (action);
CREATE INDEX IF NOT EXISTS idx_events_category        ON events (category);
CREATE INDEX IF NOT EXISTS idx_events_severity        ON events (severity);
CREATE INDEX IF NOT EXISTS idx_events_dedup           ON events (dedup_fingerprint);
CREATE INDEX IF NOT EXISTS idx_events_actor_principal ON events (actor_principal);
CREATE INDEX IF NOT EXISTS idx_events_envelope_gin    ON events USING GIN (envelope jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_events_tags_gin        ON events USING GIN (tags);
