-- S3 bucket inventory + posture read-model. One row per bucket the scanner has
-- ever seen. Projection updates this on every snapshot event and emits
-- transition events (became_public, encryption_removed, etc.) only when
-- something actually changed. Routine snapshots themselves are projection-only.

CREATE TABLE IF NOT EXISTS bucket_status (
    bucket_name          TEXT         PRIMARY KEY,
    region               TEXT,
    account              TEXT,
    created_date         TIMESTAMPTZ,             -- per AWS: when the bucket itself was created
    first_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scan            TIMESTAMPTZ,
    public               BOOLEAN,                 -- is the bucket currently reachable by Anonymous
    public_reasons       JSONB,                   -- which checks fired: ["bpa_off", "acl_grants", "policy_allows"]
    encryption           TEXT,                    -- 'AES256' | 'aws:kms' | 'none'
    versioning           TEXT,                    -- 'Enabled' | 'Suspended' | 'Disabled'
    mfa_delete           BOOLEAN,
    block_public_access  JSONB,                   -- the four BPA booleans
    logging_target       TEXT,                    -- target bucket for server access logs, or NULL
    policy               TEXT,                    -- the raw bucket policy doc (truncated to 16k for UI)
    tags                 JSONB,
    extra                JSONB
);

CREATE INDEX IF NOT EXISTS bucket_status_public ON bucket_status (public)
    WHERE public = TRUE;
CREATE INDEX IF NOT EXISTS bucket_status_unencrypted ON bucket_status (bucket_name)
    WHERE encryption = 'none';
CREATE INDEX IF NOT EXISTS bucket_status_account_region ON bucket_status (account, region);
