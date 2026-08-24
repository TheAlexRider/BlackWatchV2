-- Beginner-friendly, module + alert-kind notification profiles.
-- Profiles are the UI-facing source of truth and compile into the existing
-- notification_rules table for dispatch compatibility.

CREATE TABLE IF NOT EXISTS notification_profiles (
    id                    TEXT        PRIMARY KEY,
    module                TEXT        NOT NULL,
    event_kind            TEXT        NOT NULL,
    label                 TEXT        NOT NULL,
    description           TEXT        NOT NULL DEFAULT '',
    enabled               BOOLEAN     NOT NULL DEFAULT FALSE,
    severities            TEXT[]      NOT NULL DEFAULT '{}',
    channels              TEXT[]      NOT NULL DEFAULT '{}',
    throttle_seconds      INTEGER     NOT NULL DEFAULT 0,
    digest_window_seconds INTEGER     NOT NULL DEFAULT 0,
    silence_until         TIMESTAMPTZ,
    content               JSONB       NOT NULL DEFAULT '{}',
    advanced_template     TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (module, event_kind)
);

ALTER TABLE notification_rules
    ADD COLUMN IF NOT EXISTS digest_window_seconds INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_notification_profiles_module
    ON notification_profiles (module);

CREATE TABLE IF NOT EXISTS notification_profile_audit (
    id          BIGSERIAL PRIMARY KEY,
    profile_id  TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    detail      TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notification_profile_audit_profile
    ON notification_profile_audit (profile_id, created_at DESC);
