# AWS posture module — setup

Two-layer security coverage:

1. **CloudTrail rules** (`rules/aws_posture.yaml`) — automatic over your existing
   CloudTrail forwarder. Catches `AuthorizeSecurityGroupIngress` to a risky
   port, `ModifySnapshotAttribute` going public, `ModifyInstanceMetadataOptions`
   weakening IMDS, `PutKeyPolicy` with wildcard principal, etc. Zero new infra.
2. **Drift detection** (`aws_posture_drift` connector) — periodic scan of
   current state. Catches things that are *already bad* before BW existed:
   public SGs, unencrypted EBS, public snapshots, IMDSv1-enabled instances.

This README covers (2). (1) is already working as soon as CloudTrail events flow.

## 1. Attach the posture-read IAM policy

```powershell
$READER = "blackwatch-sqs-reader"
$polPath = Join-Path $env:TEMP "bw-posture-read.json"
Copy-Item deploy\aws-posture\blackwatch-aws-posture-policy.json $polPath
aws iam put-user-policy --user-name $READER --policy-name read-aws-posture --policy-document "file://$polPath"
Write-Host "AWS posture read attached to $READER"
```

Permissions added (read-only — same posture as S3 drift):
- **EC2 / EBS**: `DescribeRegions`, `DescribeSecurityGroups`, `DescribeInstances`, `DescribeVolumes`, `DescribeSnapshots`, `DescribeSnapshotAttribute`, `DescribeImages`, `DescribeImageAttribute`
- **STS**: `GetCallerIdentity` (for account ID)
- **IAM** (Phase 2b): `ListUsers`, `ListAccessKeys`, `GetAccessKeyLastUsed`, `ListMFADevices`, `GetLoginProfile`, `ListRoles`
- **KMS** (Phase 2b): `ListKeys`, `DescribeKey`, `GetKeyRotationStatus`, `GetKeyPolicy`
- **CloudTrail** (Phase 2b): `DescribeTrails`, `GetTrailStatus`

If you previously applied the Phase 2a-only policy, re-run the same put-user-policy command above to update it to the Phase 2b version — `put-user-policy` is replace-not-merge, so the new file fully replaces what's attached.

## 2. Restart BlackWatch so migration `012_aws_posture.sql` runs

```bash
docker compose restart app
```

Creates `posture_findings` table. "AWS posture" appears in the navbar.

## 3. Add the drift connector in the UI

Settings → **Add AWS posture drift connector**:
- Name: `aws posture`
- AWS profile: `blackwatch`
- Regions: leave blank for all enabled (or comma-separated list like `us-west-1,us-east-1`)
- Scan interval: `3600` (1h)
- All 4 checks enabled by default

Save → **Test** (runs once immediately) → **Enable**.

## 4. Watch findings appear

Refresh `/ui/aws-posture`. Counter grid at the top shows Critical / High / Medium / Low. Below: one card per resource type with the actual findings.

If you see:

- **SG findings** — usually expected on dev VPCs (someone opened port 22 for testing). Suppress per-SG via a rule allowlist if intentional.
- **EBS unencrypted** — legacy volumes from before EBS default-encryption was on at the account level. Encrypt at the next snapshot/restore cycle.
- **Public snapshots** — almost always a bug; review immediately.
- **IMDSv1 instances** — fix with: `aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-endpoint enabled`. Won't affect running workloads as long as the SDK in use supports v2 (which boto3 / AWS CLI / EKS pods all do).

## 5. Test that resolution events fire

Pick one finding, fix the underlying issue (or temporarily flip an SG closed), then click **Run now** on the connector. Within seconds:

- `aws.posture.finding.resolved` event fires (`/ui/events?action=aws.posture.finding.resolved`)
- The row disappears from `/ui/aws-posture`
- Historical record stays in `posture_findings` with `resolved_at` set, queryable later

## Checks covered

### Phase 2a — infrastructure posture (per-region)
- **`sg_public_ingress`** — security groups with ingress from 0.0.0.0/0 or ::/0 (worst-finding-per-SG dedup: all-traffic > risky-port > non-web)
- **`ebs_encryption`** — EBS volumes without encryption at rest
- **`ebs_snapshot_public`** — own snapshots shared with `all`
- **`ec2_imdsv2`** — running EC2 instances with HttpTokens != "required"
- **`ami_public`** — own AMIs with launch permission granted to `all`

### Phase 2b — IAM hygiene (account-global)
- **`iam_user_no_mfa`** — users with a console login profile but no MFA device
- **`iam_key_age`** — active access keys older than the threshold (default 90 days; 90–180d = medium, >180d = high)
- **`iam_key_unused`** — active access keys never used (>30 days old) or not used within the threshold
- **`iam_role_wildcard_trust`** — roles whose trust policy allows `Principal: "*"` with no scoping `Condition`

### Phase 2b — KMS hygiene (per-region)
- **`kms_rotation`** — customer-managed CMKs without automatic key rotation
- **`kms_policy_wildcard`** — CMK key policies with wildcard principal in current state (different from the CloudTrail `kms.policy.put` rule which catches the change event)

### Phase 2b — CloudTrail self-validation (account-global)
- **`cloudtrail_validation`** — three sub-findings:
  - `no_multi_region_trail` (high): no trail is multi-region+actively-logging
  - `not_logging` (high): a trail exists but isn't currently logging
  - `log_file_validation_disabled` (medium): logging is on but integrity validation isn't

Each check is independently togglable in the connector config.

## What this module still doesn't do (deferred)

- Lambda function URLs with `AuthType=NONE` (Tier 2; we don't run Lambda heavily yet)
- Lambda IAM roles with `*:*` policies (same; defer)
- EC2 with no IAM role attached (Tier 3; low value)
- VPC flow logs status (Tier 3; ops decision more than security)
