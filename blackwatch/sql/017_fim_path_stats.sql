-- FIM coverage gets per-configured-path file counts.
--
-- Previously the per-instance page tried to derive counts by joining
-- fim_baselines in Postgres — but that table is only populated when a
-- change event arrives, so it always read as ~0 except for paths that
-- had drifted. The agent has the real counts in its local SQLite
-- baseline; we now ship them in the heartbeat coverage payload.
--
-- path_stats shape:
--   { "<configured-path>": { "file_count": N, "total_size_bytes": N,
--                            "category": "critical_files|critical_dirs|binary_dirs" } }

ALTER TABLE fim_coverage
    ADD COLUMN IF NOT EXISTS path_stats JSONB;
