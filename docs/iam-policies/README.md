# BlackWatch IAM policies

Least-privilege AWS policies attached to the IAM identities BlackWatch uses to ingest telemetry. One JSON per purpose. Do not bundle unrelated grants into a single policy.

## bw-s3-access-logs-reader.json

**Purpose:** lets the BlackWatch S3 access-log connector list + read objects in the central log bucket `longhealth-security-s3-access-logs`. Nothing else. Cannot touch any source bucket.

**Preferred attach target: the EC2 instance role** that the BlackWatch monitoring server runs under. Instance-role credentials rotate automatically via IMDS, never touch disk, and can't be leaked via env vars or accidental commits. Use the IAM-user variant only when the workload doesn't run on EC2.

### Attach to the BW monitoring EC2's instance role (preferred)

Find the role name attached to the BW instance profile:

```powershell
aws ec2 describe-instances --instance-ids <bw-instance-id> --query "Reservations[].Instances[].IamInstanceProfile.Arn" --output text
```

The name after `instance-profile/` is the profile name; get the role behind it:

```powershell
$PROFILE_NAME = "<instance-profile-from-above>" ; aws iam get-instance-profile --instance-profile-name $PROFILE_NAME --query "InstanceProfile.Roles[].RoleName" --output text
```

Create the managed policy from this file and attach:

```powershell
$POLICY_ARN = (aws iam create-policy --policy-name BWReadS3AccessLogsOnly --policy-document file://docs/iam-policies/bw-s3-access-logs-reader.json --description "Read-only on longhealth-security-s3-access-logs. Used by BlackWatch S3 access-log connector via EC2 instance role." --query Policy.Arn --output text) ; Write-Host "Policy ARN: $POLICY_ARN"
```

```powershell
$ROLE = "<role-name-from-above>" ; aws iam attach-role-policy --role-name $ROLE --policy-arn $POLICY_ARN ; aws iam list-attached-role-policies --role-name $ROLE
```

Effect is immediate on next STS credential refresh (seconds). The BW connector uses boto3's default credential chain, which falls through to IMDS on EC2 automatically — no config change on the BW side.

**Verify from inside the BW EC2 (via SSM):**

```bash
aws sts get-caller-identity ; aws s3api list-objects-v2 --bucket longhealth-security-s3-access-logs --max-items 3
```

Should succeed. Then confirm the boundary holds:

```bash
aws s3api list-objects-v2 --bucket prod-lh-textract --max-items 3
```

Should return `AccessDenied`. If it succeeds, the role has another attached policy (like `AmazonS3ReadOnlyAccess`) granting broader access — inspect with `aws iam list-attached-role-policies --role-name $ROLE` and detach the broader policy, or accept the exposure knowing BW's process can also reach source buckets.

### Alternate: attach to an IAM user (only when NOT running on EC2)

Only use this when the workload has no instance role available (dev laptop, non-EC2 host). Same policy, different attach:

```powershell
$USER = "<USER>" ; aws iam attach-user-policy --user-name $USER --policy-arn $POLICY_ARN ; aws iam list-attached-user-policies --user-name $USER
```

Verify identically: the user should be able to list objects in the log bucket but be denied on any source bucket. Ideally the user has NO other S3 policies attached.

### Attach via AWS Console

1. IAM → Policies → Create policy → JSON tab → paste contents of `bw-s3-access-logs-reader.json` → Next.
2. Name: `BWReadS3AccessLogsOnly`. Description: `Read-only on longhealth-security-s3-access-logs. Used by BlackWatch S3 access-log connector.` → Create policy.
3. IAM → Roles (or Users) → pick the BW EC2 role (or user) → Add permissions → Attach existing policies directly → search `BWReadS3AccessLogsOnly` → Add permissions.

### Update / roll

If you rename or move the log bucket, edit `Resource` in `bw-s3-access-logs-reader.json`, then create a new policy version:

```powershell
aws iam create-policy-version --policy-arn $POLICY_ARN --policy-document file://docs/iam-policies/bw-s3-access-logs-reader.json --set-as-default
```

No credential rotation needed — instance-role creds are managed by AWS.
