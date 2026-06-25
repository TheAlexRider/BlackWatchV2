-- EC2 host read-model. One row per instance: latest heartbeat + state. A
-- projection of host.* events (parallels vpn_status). `active` flips false when
-- the staleness check fires, true again on the next heartbeat. Idempotent.

CREATE TABLE IF NOT EXISTS host_status (
    instance_id TEXT        PRIMARY KEY,
    hostname    TEXT,
    account     TEXT,
    region      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL,
    active      BOOLEAN,
    extra       JSONB
);
