-- Drop cpu_load_norm as a user-facing perf metric. Everything now uses
-- cpu_utilization_pct (true /proc/stat CPU %, matches CloudWatch).
--
-- Steps:
--   1. Rewrite any existing rules that reference cpu_load_norm to use
--      cpu_utilization_pct. Preserves rule identity and channels; the
--      threshold may need operator review since the semantics differ
--      (queue-depth 90 != utilization 90).
--   2. Drop cpu_load_norm from the metric CHECK constraint.
--   3. Truncate host_metrics_hourly. Existing rows stored queue-depth
--      values in the cpu_* columns (chart showed >100%). Fresh data
--      populated by the projection rollup will be true utilization %.

BEGIN;

UPDATE perf_alert_rules
   SET metric = 'cpu_utilization_pct'
 WHERE metric = 'cpu_load_norm';

ALTER TABLE perf_alert_rules
    DROP CONSTRAINT IF EXISTS perf_alert_rules_metric_ck;

ALTER TABLE perf_alert_rules
    ADD CONSTRAINT perf_alert_rules_metric_ck
    CHECK (metric IN ('memory_pct', 'cpu_utilization_pct', 'disk_pct_max'));

-- One-shot cleanup: wipe rows that stored queue-depth (>100) in the cpu_*
-- columns. Guarded so this doesn't nuke healthy data if the migration ever
-- gets executed a second time (e.g. an operator restores an old DB without
-- the schema_migrations tracker).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM host_metrics_hourly WHERE cpu_avg > 100 LIMIT 1) THEN
        TRUNCATE TABLE host_metrics_hourly;
    END IF;
END $$;

COMMIT;
