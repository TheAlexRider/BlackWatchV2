-- Shape B (stolen-credential / new-source) detection support.
--
-- rds_proxy_sources — every real client IP that has ever touched the RDS
-- Proxy, with first/last seen and a running connect count. Fed by the
-- proxy "A new client connected from IP:PORT" line. Used by the projection
-- to fire rds.proxy.source.new the first time an IP shows up.
--
-- rds_user_source_history — (username, real_client_ip) pairs derived from
-- postgres session starts that we successfully enriched via the proxy
-- client→db pinning chain. Used to fire rds.session.new_source when a
-- known user shows up from an IP we've never seen for them before.
--
-- rds_user_allowlist — the list of DB usernames the operator considers
-- expected. Anyone connecting whose username isn't on this list fires
-- rds.user.unknown. Seeded with AWS system users only; humans/service
-- accounts must be added explicitly by the operator.

CREATE TABLE IF NOT EXISTS rds_proxy_sources (
    source_ip     TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    connect_count BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rds_proxy_sources_last_seen
    ON rds_proxy_sources (last_seen_at DESC);

CREATE TABLE IF NOT EXISTS rds_user_source_history (
    username      TEXT NOT NULL,
    source_ip     TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_count BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (username, source_ip)
);
CREATE INDEX IF NOT EXISTS idx_rds_user_source_last_seen
    ON rds_user_source_history (last_seen_at DESC);

CREATE TABLE IF NOT EXISTS rds_user_allowlist (
    username  TEXT PRIMARY KEY,
    kind      TEXT NOT NULL CHECK (kind IN ('human','service')),
    note      TEXT,
    added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed only the AWS system users. Everything else — humans AND app service
-- accounts — has to be added explicitly. First-run will alert on the current
-- traffic; that IS the intended behavior: it forces the operator to review
-- and inventory who has DB access.
INSERT INTO rds_user_allowlist (username, kind, note) VALUES
    ('rdsadmin',              'service', 'AWS RDS control plane'),
    ('rdsproxyadmin',         'service', 'AWS RDS Proxy control plane'),
    ('rds_superuser',         'service', 'AWS RDS extension owner'),
    ('rds_iam_authorization', 'service', 'AWS RDS IAM auth helper'),
    ('rdssecadmin',           'service', 'AWS RDS security control plane'),
    ('rds_replication',       'service', 'AWS RDS replication'),
    ('rds_monitor',           'service', 'AWS RDS enhanced monitoring')
ON CONFLICT (username) DO NOTHING;
