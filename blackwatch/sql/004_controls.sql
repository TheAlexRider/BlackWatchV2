-- Dashboard-managed controls.
--   rule_overrides: per-rule enable/disable set from the UI (survives restart;
--                   applied on top of the YAML `enabled` flag at startup).
--   muted_actions:  event actions to DROP at ingest (noise control, e.g. a
--                   high-volume unscored event type). Idempotent.

CREATE TABLE IF NOT EXISTS rule_overrides (
    rule_id  TEXT PRIMARY KEY,
    enabled  BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS muted_actions (
    action      TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
