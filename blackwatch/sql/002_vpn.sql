-- VPN live-state read-model. One row per VPN server holds the latest known
-- service state and connected-client snapshot. This is a PROJECTION derived
-- from vpn.* events, not a second source of truth — it exists so "who is
-- connected right now" is a cheap single-row read. Idempotent.

CREATE TABLE IF NOT EXISTS vpn_status (
    server      TEXT        PRIMARY KEY,
    updated_at  TIMESTAMPTZ NOT NULL,
    active      BOOLEAN,
    -- NULL means "no client snapshot has ever been recorded" (distinct from an
    -- empty list = a snapshot with zero connected clients). The projection uses
    -- this to skip session diffing on the very first snapshot.
    clients     JSONB
);
