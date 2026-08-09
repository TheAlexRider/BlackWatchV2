-- RBAC + append-only self-audit.
--
-- Two roles today: 'admin' (full mutation power) and 'viewer' (reads only).
-- New users default to 'viewer' so accidentally-added accounts can't
-- escalate. On first application of this migration the oldest existing
-- account is promoted to admin so the operator isn't locked into
-- viewer-only.
--
-- audit is append-only: no UPDATE or DELETE routes reference it. It stores
-- one row per non-GET request the FastAPI app receives so we can later
-- prove who changed what and when (HITRUST 0910.09aa / 0912.09ab,
-- SOC 2 CC7.2 / CC6.1).

ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'viewer';

-- Promote the oldest existing user to admin — idempotent because it only
-- fires when no admin exists yet.
UPDATE auth_users
   SET role = 'admin'
 WHERE username = (
        SELECT username FROM auth_users
         ORDER BY created_at ASC, username ASC
         LIMIT 1
       )
   AND NOT EXISTS (SELECT 1 FROM auth_users WHERE role = 'admin');

CREATE TABLE IF NOT EXISTS audit (
    id            BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor         TEXT,
    actor_role    TEXT,
    ip            TEXT,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    status        INTEGER NOT NULL,
    body_summary  TEXT
);

CREATE INDEX IF NOT EXISTS audit_ts_idx
    ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS audit_actor_ts_idx
    ON audit(actor, ts DESC);
