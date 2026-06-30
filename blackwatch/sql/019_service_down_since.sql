-- Track when each service first transitioned to DOWN (or degraded). The
-- projection sets this on the UP->DOWN edge, clears it on DOWN->UP, and uses
-- it on the /services API to surface services that have been down longer than
-- the archive threshold (default 7 days). Without this column we'd have to
-- approximate from consecutive_fails * interval which drifts as cadence changes.

ALTER TABLE service_status
  ADD COLUMN IF NOT EXISTS down_since TIMESTAMPTZ;

-- Backfill: services already DOWN at migration time get a best-effort down_since
-- of last_seen. This is the earliest moment we can prove the service was down;
-- a row that was actually down longer will just take its full archive window
-- to age out, which is fine -- the alternative is to falsely claim "down for
-- 7+ days" when we don't have the data to back it up.
UPDATE service_status
   SET down_since = COALESCE(last_seen, now())
 WHERE status IN ('down', 'degraded') AND down_since IS NULL;

CREATE INDEX IF NOT EXISTS service_status_down_since ON service_status (down_since);
