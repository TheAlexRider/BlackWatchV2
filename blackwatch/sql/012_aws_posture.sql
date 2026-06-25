-- Unified AWS-posture findings read-model. One row per (account, resource_id,
-- finding_type) — deterministic finding_id from a hash of those three lets the
-- same drift scan re-run idempotently. `resolved_at` is set on the scan tick
-- after a finding disappears, so historical findings stay queryable while only
-- the currently-active ones drive alerts.

CREATE TABLE IF NOT EXISTS posture_findings (
    finding_id     TEXT         PRIMARY KEY,
    resource_id    TEXT         NOT NULL,
    resource_type  TEXT         NOT NULL,
    -- resource_type ∈ {sg, ebs_volume, ebs_snapshot, ec2_instance, ami,
    --                  iam_user, iam_access_key, kms_key, cloudtrail}
    finding_type   TEXT         NOT NULL,
    severity       TEXT         NOT NULL,
    region         TEXT,
    account        TEXT,
    evidence       JSONB,            -- structured details (port, CIDR, key age, etc.)
    first_seen     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen      TIMESTAMPTZ  NOT NULL,
    resolved_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS posture_findings_unresolved
    ON posture_findings (severity, resource_type) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS posture_findings_resource
    ON posture_findings (resource_type, resource_id);
CREATE INDEX IF NOT EXISTS posture_findings_account_region
    ON posture_findings (account, region) WHERE resolved_at IS NULL;
