-- Performance alert rules — threshold-based alerting on host heartbeats.
--
-- Separate from notification_rules (which match existing events) because
-- the mechanic is different: perf alerts evaluate *continuous metrics*
-- against user-configured thresholds + sliding time windows. When a rule
-- breaches its threshold for the configured duration, the evaluator emits
-- a synthetic host.perf.alert event AND directly dispatches to the rule's
-- bound channels (so the operator doesn't have to create both a perf rule
-- AND a notification rule).
--
-- Scope can be:
--   instance_id="i-08…"                — one specific instance
--   tag_key="env", tag_value="prod"    — all instances matching this tag
-- Both being NULL would mean "all instances" but the API rejects that —
-- avoids creating a fleet-wide pager on accident.
--
-- Built-in alerts (host.memory.exhausted 95%, host.disk.warn 90%,
-- host.cpu.anomaly) are unchanged. Custom perf alerts fire alongside.

CREATE TABLE IF NOT EXISTS perf_alert_rules (
    id                  UUID        PRIMARY KEY,
    name                TEXT        NOT NULL,
    enabled             BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- SCOPE
    module              TEXT        NOT NULL,    -- 'ec2.host' for now; later 'aws.rds', 'aws.ecs'
    instance_id         TEXT,                    -- exact-match scope (XOR with tag_*)
    tag_key             TEXT,                    -- e.g. 'env'
    tag_value           TEXT,                    -- e.g. 'prod' — paired with tag_key

    -- THRESHOLD
    metric              TEXT        NOT NULL,    -- 'memory_pct' | 'cpu_load_norm' | 'disk_pct_max'
    comparison          TEXT        NOT NULL DEFAULT 'gte',  -- 'gte'|'gt'|'lte'|'lt'
    threshold           NUMERIC     NOT NULL,    -- e.g. 80 for "80%"

    -- TIME WINDOW (looser semantics — see docs/fim.md style)
    -- Fire when min_breach_ratio of samples in the trailing window are breached.
    -- 1.0 = strict (every sample must breach), 0.6 = looser (60% of samples).
    window_seconds      INT         NOT NULL DEFAULT 300,    -- 5 minutes
    min_breach_ratio    NUMERIC     NOT NULL DEFAULT 0.6,

    -- OUTPUT
    severity            TEXT        NOT NULL DEFAULT 'high',
    channels            JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- list of channel names
    throttle_seconds    INT         NOT NULL DEFAULT 1800,    -- 30 min between re-fires

    -- EVALUATOR STATE — managed by perf_alerts.py, never touched by UI/API.
    -- samples: rolling buffer of {t, b, v} tuples within window_seconds.
    samples             JSONB       NOT NULL DEFAULT '[]'::jsonb,
    last_fired_at       TIMESTAMPTZ,
    last_value          NUMERIC,                 -- for display in /perf-alerts list

    -- One of (instance_id, tag_key+tag_value) must be set. Enforced in app
    -- code rather than CHECK constraint so we can give a friendly error.
    CONSTRAINT perf_alert_rules_metric_ck CHECK (
        metric IN ('memory_pct', 'cpu_load_norm', 'disk_pct_max')
    ),
    CONSTRAINT perf_alert_rules_comparison_ck CHECK (
        comparison IN ('gte', 'gt', 'lte', 'lt')
    )
);

CREATE INDEX IF NOT EXISTS perf_alert_rules_enabled_module
    ON perf_alert_rules (enabled, module) WHERE enabled = TRUE;
