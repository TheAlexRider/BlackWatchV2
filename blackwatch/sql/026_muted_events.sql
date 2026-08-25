-- Contextual mute: replace muted_actions (dropped events by action string only)
-- with muted_events, which filters by (action, source_type, username, reason).
-- NULL in any filter column means "match any value". This lets the operator
-- silence a specific noisy combo — e.g. postgres pg_hba rejects for the
-- shared pool user — without also blinding themselves to real credential
-- failures on the same action.
--
-- Migrate the old action-only rows into the new shape (all filters NULL =
-- same behavior as before), then drop the old table.
--
-- Seed the application_user + no_pg_hba_entry combo up front. The DBA has to
-- add the RDS Proxy ENIs to pg_hba.conf on the backend; until then, the
-- failure fires ~192/day and dominates every /rds view. The seed row lists
-- the exact fix in `note` so the next operator to open /rules understands
-- why it's muted and how to unblock.

CREATE TABLE IF NOT EXISTS muted_events (
    id           BIGSERIAL PRIMARY KEY,
    action       TEXT NOT NULL,
    source_type  TEXT,
    username     TEXT,
    reason       TEXT,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_muted_events_action ON muted_events (action);

-- Migrate legacy action-only mutes into the new shape. The legacy table is
-- intentionally retained so this migration can never remove operator data.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'muted_actions') THEN
        INSERT INTO muted_events (action, note)
        SELECT legacy.action, 'migrated from muted_actions'
          FROM muted_actions AS legacy
         WHERE NOT EXISTS (
             SELECT 1
               FROM muted_events AS current
              WHERE current.action = legacy.action
                AND current.note = 'migrated from muted_actions'
         );
        -- Do not drop muted_actions. It is retained as a compatibility
        -- backup until an operator explicitly archives it outside migrations.
    END IF;
END $$;

-- Seed the pg_hba-reject silencing so the dashboard is usable NOW.
INSERT INTO muted_events (action, source_type, username, reason, note)
SELECT
    'rds.auth.failure',
    'postgres',
    'application_user',
    'no_pg_hba_entry',
    'Waiting on DBA to add proxy ENIs 172.19.140.36/32 + 172.19.154.144/32 to backend pg_hba.conf. Unmute after the fix ships so genuine application_user auth issues are visible again.'
WHERE NOT EXISTS (
    SELECT 1 FROM muted_events
    WHERE action = 'rds.auth.failure'
      AND source_type = 'postgres'
      AND username = 'application_user'
      AND reason = 'no_pg_hba_entry'
);
