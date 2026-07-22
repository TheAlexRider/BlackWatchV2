-- Hourly rollup of host resource metrics — one row per (host, hour) with
-- min/avg/max for memory % and CPU load %. Populated from every heartbeat
-- by the projection (blackwatch/hosts/projection.py). Retained for 9 days
-- — enough for week-over-week comparison, small enough to keep the table
-- trivially cheap.
--
-- Size math: ~24 rows/host/day × 9 days = 216 rows/host. Even at 100 hosts
-- that's 21.6k rows total. Prune runs on every insert as a cheap DELETE.
--
-- Disk was intentionally left out — it drifts day-over-day rather than
-- spiking on human timescales, so a min/avg/max/hour rollup adds no signal
-- over the perf-alert threshold model (fire when disk % breaches). See
-- sql/032_host_metrics_drop_disk.sql for the retroactive drop.

CREATE TABLE IF NOT EXISTS host_metrics_hourly (
    instance_id  TEXT        NOT NULL,
    hour_start   TIMESTAMPTZ NOT NULL,   -- floor to the top of the hour, UTC
    mem_min      NUMERIC,
    mem_avg      NUMERIC,
    mem_max      NUMERIC,
    cpu_min      NUMERIC,
    cpu_avg      NUMERIC,
    cpu_max      NUMERIC,
    sample_count INTEGER     NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instance_id, hour_start)
);

-- Range scans by host + time window (the chart's typical query).
CREATE INDEX IF NOT EXISTS host_metrics_hourly_instance_time
    ON host_metrics_hourly (instance_id, hour_start DESC);

-- Retention prune target — DELETE WHERE hour_start < NOW() - '9 days'.
CREATE INDEX IF NOT EXISTS host_metrics_hourly_hour_start
    ON host_metrics_hourly (hour_start);
