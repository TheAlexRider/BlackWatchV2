-- Notification Channels (Phase 2). DB-backed, UI-managed. Replaces the YAML
-- `channels:` list (seeded once on first boot if empty).
--   message_template = Jinja2 template; NULL falls back to per-type default
--   retries / retry_backoff_seconds: per-channel retry policy (worker)
--   rate_limit_per_min: 0 = unlimited; otherwise max sends per minute
--   dedup_window_seconds: per-(rule, channel, fingerprint) throttle
--   digest_window_seconds: 0 = off; otherwise buffer messages and flush as one
--
-- Secrets are NEVER stored in `config`. Sensitive values are referenced by env
-- var name (e.g. `password_env: SMTP_PASS`, `routing_key_env: PD_KEY`); the
-- worker reads them from the process environment at send time.

CREATE TABLE IF NOT EXISTS notification_channels (
    id                    TEXT        PRIMARY KEY,
    name                  TEXT        NOT NULL UNIQUE,
    type                  TEXT        NOT NULL,
    enabled               BOOLEAN     NOT NULL DEFAULT true,
    config                JSONB       NOT NULL DEFAULT '{}',
    message_template      TEXT,
    retries               INTEGER     NOT NULL DEFAULT 3,
    retry_backoff_seconds INTEGER     NOT NULL DEFAULT 5,
    rate_limit_per_min    INTEGER     NOT NULL DEFAULT 0,
    dedup_window_seconds  INTEGER     NOT NULL DEFAULT 300,
    digest_window_seconds INTEGER     NOT NULL DEFAULT 0,
    last_status           TEXT,
    last_error            TEXT,
    last_sent_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
