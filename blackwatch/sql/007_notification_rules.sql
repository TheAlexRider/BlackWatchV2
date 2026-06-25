-- Notification Rules (Phase 1). DB-backed, UI-managed; replaces the YAML
-- `routes:` list (which is seeded into this table once on first boot if empty).
-- `match` is a Condition tree (same model as detection rules), so the full
-- operator vocabulary (equals/in/contains/regex/cidr/exists/startswith/endswith,
-- with all/any/not nesting) is available.

CREATE TABLE IF NOT EXISTS notification_rules (
    id               TEXT        PRIMARY KEY,
    name             TEXT        NOT NULL,
    enabled          BOOLEAN     NOT NULL DEFAULT true,
    match            JSONB       NOT NULL DEFAULT '{}',
    channels         TEXT[]      NOT NULL DEFAULT '{}',
    throttle_seconds INTEGER     NOT NULL DEFAULT 0,  -- 0 = use channel's dedup_window_seconds
    silence_until    TIMESTAMPTZ,                     -- managed by the Silence button
    priority         INTEGER     NOT NULL DEFAULT 100,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
