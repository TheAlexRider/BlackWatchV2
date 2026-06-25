-- ECS service monitoring: targets + per-target status + per-VPC probe agents.
-- Mirrors the host_status / vpn_status pattern: one row per monitored thing,
-- updated by the projection in response to probe results.

CREATE TABLE IF NOT EXISTS probe_targets (
    id                  UUID         PRIMARY KEY,
    name                TEXT         NOT NULL,
    vpc                 TEXT         NOT NULL,
    tier                TEXT         NOT NULL,
    -- tier ∈ {'ecs_health', 'ecs_running', 'http_alive', 'tcp'}.
    -- ecs_health / ecs_running are AWS API calls (BlackWatch reads them; no VPC presence required).
    -- http_alive / tcp need network reachability to the target's private IP (probe agent runs inside the VPC).
    config              JSONB        NOT NULL,
    severity_when_down  TEXT         NOT NULL DEFAULT 'high',
    tags                JSONB,
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (name, vpc)
);

CREATE INDEX IF NOT EXISTS probe_targets_vpc_enabled ON probe_targets (vpc, enabled);
CREATE INDEX IF NOT EXISTS probe_targets_tier ON probe_targets (tier);

CREATE TABLE IF NOT EXISTS service_status (
    target_id            UUID         PRIMARY KEY REFERENCES probe_targets(id) ON DELETE CASCADE,
    vpc                  TEXT         NOT NULL,
    name                 TEXT         NOT NULL,
    tier                 TEXT         NOT NULL,
    status               TEXT,           -- 'up' | 'down' | 'degraded' | 'unknown'
    last_seen            TIMESTAMPTZ,
    latency_ms           INT,
    consecutive_fails    INT          NOT NULL DEFAULT 0,
    consecutive_success  INT          NOT NULL DEFAULT 0,
    extra                JSONB
);

CREATE INDEX IF NOT EXISTS service_status_vpc ON service_status (vpc);
CREATE INDEX IF NOT EXISTS service_status_status ON service_status (status);

-- Per-VPC probe agent heartbeat. Staleness check (parallel to host staleness)
-- fires probe.agent.stale when last_report ages past the threshold.
CREATE TABLE IF NOT EXISTS probe_agent_status (
    vpc            TEXT         PRIMARY KEY,
    last_report    TIMESTAMPTZ,
    agent_version  TEXT,
    active         BOOLEAN
);
