-- Add cpu_utilization_pct as an allowed metric for perf alert rules.
--
-- Load-normalized CPU (cpu_load_norm) is a queue-depth signal — value ÷ cpu
-- count × 100 — and can legitimately exceed 100 under contention. That
-- confuses operators used to CloudWatch's 0-100% CPUUtilization semantic.
-- cpu_utilization_pct is the true /proc/stat-derived utilization, always
-- capped at 100, matching what CloudWatch shows.
--
-- We keep cpu_load_norm around for anyone who wants to alert on queue-depth
-- (early signal that a box is oversubscribed even before CPUs saturate).

ALTER TABLE perf_alert_rules DROP CONSTRAINT IF EXISTS perf_alert_rules_metric_ck;
ALTER TABLE perf_alert_rules ADD CONSTRAINT perf_alert_rules_metric_ck
    CHECK (metric IN (
        'memory_pct',
        'cpu_load_norm',
        'cpu_utilization_pct',
        'disk_pct_max'
    ));
