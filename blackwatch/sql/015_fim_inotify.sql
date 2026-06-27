-- FIM Part 2: real-time inotify support.
--
-- The agent now has two detection paths: periodic 6h scan (Part 1) and
-- real-time inotify watcher (Part 2). The UI needs to show which path
-- caught each change AND how many paths are covered by each.

-- Per-event detection method ("baseline" | "inotify" | future "auditd").
ALTER TABLE fim_history
    ADD COLUMN IF NOT EXISTS detection TEXT;

-- Per-host coverage breakdown so the UI can show
-- "47 paths real-time, 277 baseline-only".
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS paths_inotify INT NOT NULL DEFAULT 0;
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS paths_baseline_only INT NOT NULL DEFAULT 0;
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS inotify_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS inotify_watch_count INT NOT NULL DEFAULT 0;
