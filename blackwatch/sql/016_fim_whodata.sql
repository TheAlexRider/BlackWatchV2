-- FIM Part 3: whodata (actor attribution) via Linux audit framework.
--
-- The agent now tails /var/log/audit/audit.log and joins fresh write events
-- to the FIM events the inotify watcher emits, by path + 2-second window.
-- That gives us uid / pid / comm / exe / proctitle for "who actually edited
-- this file" instead of just "this file changed at T."
--
-- Also: list of configured paths per host so the UI can show "what are we
-- watching?" without the user inspecting agent env vars or systemd unit.

-- Actor attribution on fim_history. Nullable — whodata is best-effort
-- (auditd may not be installed; events may be detected by the periodic
-- scanner long after the audit window expires).
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_uid INT;
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_gid INT;
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_pid INT;
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_comm TEXT;
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_exe TEXT;
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS actor_proctitle TEXT;

-- Per-host: is auditd available (and our rules loaded?) and what's the
-- agent's full configured-paths list, for the "what are we watching" UI.
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS auditd_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS configured_paths JSONB;
