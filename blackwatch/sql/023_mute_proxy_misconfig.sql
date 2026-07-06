-- Pre-mute rds.proxy.misconfig by default. The line
-- "Credentials couldn't be retrieved. The database user "X" was found in
-- multiple DB proxy authentication entries" fires ~100/hour whenever the
-- Secrets Manager mapping has duplicates for a user, which drowns out real
-- security signal. The operator can unmute from the UI once the DBA has
-- collapsed the duplicate entry.
--
-- Idempotent: ON CONFLICT DO NOTHING means re-running the migration won't
-- re-mute if the operator has since unmuted.
INSERT INTO muted_actions (action) VALUES ('rds.proxy.misconfig')
ON CONFLICT (action) DO NOTHING;
