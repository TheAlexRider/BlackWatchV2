-- User-editable friendly name for a host. Distinct from `hostname` (which
-- is the auto-populated DNS/system name the agent reports). Everywhere the
-- UI shows an instance, the label resolves to:
--   display_name > hostname > instance_id
-- so operators see "Prod-NAT" instead of "i-08ba0757a3aa1c5e0".

ALTER TABLE host_status ADD COLUMN IF NOT EXISTS display_name TEXT;
