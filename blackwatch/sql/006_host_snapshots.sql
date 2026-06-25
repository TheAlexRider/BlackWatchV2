-- Phase B: per-host state snapshots (latest only) so the projection can diff
-- new -> previous and emit host.port.opened / host.user.added / etc. Additive.

ALTER TABLE host_status ADD COLUMN IF NOT EXISTS snapshots JSONB;
