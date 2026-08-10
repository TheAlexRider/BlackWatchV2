"""Connector config models. A connector is a telemetry source BlackWatch
actively *pulls* from on a schedule (vs. push sources that POST to /ingest).

OpenVPN previously used an SSH-pull connector here; that's been retired in
favour of the on-host `vpn_agent.py` (push to SQS, drained by the same generic
SQS connector below as `target_module=vpn.openvpn`)."""

from __future__ import annotations

from pydantic import BaseModel


class CertProbeTarget(BaseModel):
    """One TLS endpoint to probe. `sni` defaults to the same as host."""

    name: str
    host: str
    port: int = 443
    sni: str | None = None


class CertProbeConfig(BaseModel):
    """Periodic TLS cert expiry probe. Connects to a list of TCP endpoints,
    reads the leaf cert via the TLS handshake (no validation — we WANT to see
    expired certs), and ships a probe report through the cert adapter.

    UDP-based services (OpenVPN) need a different mechanism — out of scope for
    this connector. Add an HTTPS sidecar on the box or use the SSH probe
    variant (planned)."""

    targets: list[CertProbeTarget] = []
    interval_seconds: int = 3600   # hourly is plenty — certs don't change minute-to-minute
    timeout_seconds: int = 5


class AwsCloudtrailSqsConfig(BaseModel):
    """Generic SQS connector: poll a queue and feed each message to a target
    module. Used for CloudTrail (EventBridge->Lambda->SQS), EC2 host agents
    (reporter->SQS), and the OpenVPN agent (`target_module=vpn.openvpn`).
    AWS creds come from a mounted profile (never stored by BlackWatch)."""

    queue_url: str
    aws_region: str = "us-east-1"
    aws_profile: str | None = None  # profile name in the mounted ~/.aws
    target_module: str = "aws.cloudtrail"
    interval_seconds: int = 60
    wait_seconds: int = 10  # SQS long-poll wait
    max_batches: int = 5  # safety cap on receive loops per run


class AwsEcsProbeSqsConfig(BaseModel):
    """SQS-backed in-VPC probe drain. Each in-VPC ECS probe agent (one per VPC)
    pushes its result reports to a per-VPC queue with IAM auth — see
    `scripts/ecs_probe.py`. This connector polls that queue and feeds each
    report into the `ecs.probe` adapter (same one the legacy HTTP /ingest path
    fed). The connector stamps each report's `vpc` field from its own config so
    a compromised probe in one VPC cannot forge reports for another VPC even
    if it manages to write to its own queue with a different body."""

    queue_url: str
    aws_region: str = "us-west-1"
    aws_profile: str | None = None
    vpc: str                          # which VPC label this queue represents (stamped onto every report)
    # The connector also mirrors the per-VPC SSM targets parameter into the
    # probe_targets table on each drain cycle, so the UI and notification
    # routing see the canonical target list. Defaults to the path setup.ps1
    # writes; override if you store targets under a different prefix.
    ssm_targets_param: str | None = None
    interval_seconds: int = 60
    wait_seconds: int = 10            # SQS long-poll wait
    max_batches: int = 5              # safety cap on receive loops per run


class AwsEcsHealthConfig(BaseModel):
    """ECS health-status reader. For each enabled probe_target with tier in
    {ecs_health, ecs_running}, calls ecs:DescribeTasks to read AWS's view of
    the service's health. Generates the same shaped report the in-VPC probe
    agent would, and pipes it through the same ecs.probe adapter — so AWS's
    healthStatus is just *another probe result* downstream of the projection."""

    vpc: str                                       # which VPC label this poll covers (matches probe_targets.vpc)
    aws_region: str = "us-west-1"
    aws_profile: str | None = None                 # mounted ~/.aws profile name
    interval_seconds: int = 60
    # For ecs_running tier: how many consecutive minutes runningCount must
    # remain below desiredCount before declaring 'down'. Smooths Fargate Spot
    # interruptions (which are normal — task gets reclaimed, ECS replaces, brief gap).
    running_smoothing_minutes: int = 5


class AwsS3AccessLogsConfig(BaseModel):
    """Pulls S3 server access logs from a central log bucket, parses each line,
    emits one `s3.object.access` event per request. Feeds intel + UEBA hooks
    automatically. Cursor is time-based (LastModified > last_run_at - overlap)
    so no schema changes needed; dedupe on insert via deterministic event_id.

    IAM: the runtime credential must be scoped to list+get on `bucket` ONLY —
    do NOT reuse a broad-S3 role. See docs/iam-policies/bw-s3-access-logs-reader.json."""

    bucket: str
    aws_region: str = "us-west-1"
    aws_profile: str | None = None
    # How often to poll for new log files.
    interval_seconds: int = 300
    # Overlap window to catch files whose LastModified straddled the last run.
    # AWS delivers access logs with hours of delay, so a small overlap is fine —
    # dedupe covers the rest.
    overlap_seconds: int = 900
    # Safety cap per run — the log bucket can burst under heavy source traffic.
    # Anything not processed this run comes through on the next tick (time
    # cursor still advances only on success).
    max_files_per_run: int = 200
    # Optional key prefix filter. Empty = every prefix (all source buckets).
    # If you only want to process a subset, set e.g. "logs/prod-lh-".
    prefix: str = ""


class AwsS3DriftConfig(BaseModel):
    """S3 bucket-inventory drift scan. Periodically iterates every bucket in
    the account, reads its current security posture (public access, encryption,
    versioning, BPA, logging), and emits a snapshot the projection compares to
    the stored state. Hourly is plenty — these settings don't change minute-by-
    minute. The bootstrap script (`scripts/s3_bucket_inventory.py`) is the same
    logic in CLI form for the very first scan."""

    aws_profile: str | None = None                 # mounted ~/.aws profile name
    interval_seconds: int = 3600                   # 1 hour by default — these don't change fast


class AwsRdsSqsConfig(BaseModel):
    """SQS-backed RDS log drain. The BW `bw-log-forwarder` Lambda subscribes
    to each RDS log group's CloudWatch Logs stream and puts one message per
    log batch on this queue. The connector polls the queue and feeds each
    batch through the aws.rds adapter."""

    queue_url: str
    aws_region: str = "us-west-1"
    aws_profile: str | None = None
    interval_seconds: int = 60
    wait_seconds: int = 10
    max_batches: int = 5


class AwsApiGwSqsConfig(BaseModel):
    """SQS-backed API Gateway access-log drain. The BW forwarder Lambda
    subscribes to each API Gateway stage's access log group and puts one
    message per log batch on this queue. The connector polls the queue and
    feeds each batch through the aws.api_gw adapter."""

    queue_url: str
    aws_region: str = "us-west-1"
    aws_profile: str | None = None
    interval_seconds: int = 60
    wait_seconds: int = 10
    max_batches: int = 5


class AwsPostureDriftConfig(BaseModel):
    """AWS posture drift scan. Walks the account's resources and flags Tier-1
    posture problems. Per-check booleans let operators ramp up coverage
    incrementally. Empty `regions` = all enabled regions in the account."""

    aws_profile: str | None = None
    regions: list[str] = []                        # empty = scan all enabled
    interval_seconds: int = 3600
    # Phase 2a — infrastructure posture (per-region):
    check_sg_public_ingress: bool = True
    check_ebs_encryption: bool = True
    check_ebs_snapshot_public: bool = True
    check_ec2_imdsv2: bool = True
    check_ami_public: bool = True
    # Phase 2b — IAM hygiene (account-global):
    check_iam_user_no_mfa: bool = True
    check_iam_key_age: bool = True
    check_iam_key_unused: bool = True
    check_iam_role_wildcard_trust: bool = True
    iam_key_max_age_days: int = 90
    iam_key_unused_threshold_days: int = 90
    # Phase 2b — KMS hygiene (per-region):
    check_kms_rotation: bool = True
    check_kms_policy_wildcard: bool = True
    # Phase 2b — CloudTrail self-validation (account-global):
    check_cloudtrail_validation: bool = True
    # Phase 2c — RDS posture (per-region). Inventory emits one
    # rds.instance.state event per DB so the /rds page shows every DB the
    # account owns, regardless of whether CloudTrail has seen a change event
    # for it. Findings flow through the normal posture pipeline.
    check_rds: bool = True
