-- Notification observability (Phase 2):
--   notification_log: every send attempt (success / failure / rate-limited / acked / etc.)
--   notification_acks: per-fingerprint suppression — "I'm investigating this,
--                       stop paging me about it for N hours"

CREATE TABLE IF NOT EXISTS notification_log (
    id              BIGSERIAL   PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    rule_id         TEXT,
    rule_name       TEXT,
    channel_id      TEXT,
    channel_name    TEXT,
    event_id        TEXT,
    event_action    TEXT,
    event_severity  TEXT,
    status          TEXT        NOT NULL,        -- sent | failed | rate_limited | acked | digested
    retries_used    INTEGER     NOT NULL DEFAULT 0,
    body_preview    TEXT,
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_log_ts      ON notification_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_notif_log_status  ON notification_log (status);

CREATE TABLE IF NOT EXISTS notification_acks (
    fingerprint  TEXT        PRIMARY KEY,
    ack_until    TIMESTAMPTZ NOT NULL,
    reason       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
