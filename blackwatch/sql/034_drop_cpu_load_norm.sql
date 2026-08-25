-- Retire cpu_load_norm as the default user-facing perf metric. Everything new
-- uses cpu_utilization_pct (true /proc/stat CPU %, matches CloudWatch).
--
-- Steps:
--   1. Rewrite any existing rules that reference cpu_load_norm to use
--      cpu_utilization_pct. Preserves rule identity and channels; the
--      threshold may need operator review since the semantics differ
--      (queue-depth 90 != utilization 90).
--   2. Keep cpu_load_norm in the metric CHECK constraint for existing rules.
--   3. Preserve host_metrics_hourly. Existing rows are historical evidence;
--      fresh data populated by the projection rollup will be true utilization
--      %. No automatic migration may delete those rows.

BEGIN;

UPDATE perf_alert_rules
   SET metric = 'cpu_utilization_pct'
 WHERE metric = 'cpu_load_norm';

ALTER TABLE perf_alert_rules
    DROP CONSTRAINT IF EXISTS perf_alert_rules_metric_ck;

ALTER TABLE perf_alert_rules
    ADD CONSTRAINT perf_alert_rules_metric_ck
    CHECK (metric IN ('memory_pct', 'cpu_load_norm', 'cpu_utilization_pct', 'disk_pct_max'));

COMMIT;
