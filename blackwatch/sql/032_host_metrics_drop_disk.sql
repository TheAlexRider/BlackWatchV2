-- Roll back the disk columns from the hourly rollup. Disk usage doesn't
-- change fast enough for min/avg/max per hour to add signal — it drifts
-- day-over-day, so the perf-alert threshold+breach model already covers
-- "disk got full", nothing to plot.
--
-- Memory and CPU stay in the rollup — those spike and recover on human
-- timescales and the chart shape genuinely tells you something.

ALTER TABLE host_metrics_hourly DROP COLUMN IF EXISTS disk_min;
ALTER TABLE host_metrics_hourly DROP COLUMN IF EXISTS disk_avg;
ALTER TABLE host_metrics_hourly DROP COLUMN IF EXISTS disk_max;
