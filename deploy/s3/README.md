# S3 module — setup

Two-piece security coverage for S3:

1. **CloudTrail-driven detections** (`rules/s3.yaml`) — automatic over your
   existing CloudTrail forwarder. Detects: public bucket via ACL or policy,
   Block Public Access weakened, encryption removed, versioning suspended,
   MFA Delete disabled, logging disabled, bucket deletion. No new infra.
2. **Drift detection** — periodic scan of every bucket's current posture, plus
   the ability to detect buckets that were *already bad* before BlackWatch
   existed.

This README covers (2). (1) just works once the CloudTrail forwarder is up.

## 1. Attach the S3-read IAM policy

The drift scanner needs read-only S3 management permissions on the same user
the CloudTrail/EC2 connectors use (`blackwatch-sqs-reader`):

```powershell
$READER = "blackwatch-sqs-reader"
$ACCT = aws sts get-caller-identity --query Account --output text

$polPath = Join-Path $env:TEMP "bw-s3-read.json"
Copy-Item deploy\s3\blackwatch-s3-read-policy.json $polPath
aws iam put-user-policy --user-name $READER --policy-name read-s3 --policy-document "file://$polPath"
Write-Host "S3 read attached to $READER"
```

## 2. Restart BlackWatch so the migration runs

```bash
docker compose restart app
```

Migration `011_s3.sql` creates the `bucket_status` table. The "S3" tab appears
in the navbar.

## 3. Bootstrap — first scan, from your laptop, before setting up the connector

This is what tells you "here is the current state of every bucket in our
account." Run this with your own admin AWS credentials (your normal local
profile, not the read-only `blackwatch` one — you want the most-permissive
read so nothing is missed):

```powershell
# Make sure your default profile or a named one can see all buckets
aws s3api list-buckets --query "Buckets[].Name" --output text

$env:BLACKWATCH_URL = "http://localhost:8000"
$env:BLACKWATCH_TOKEN = "<a token mapped to module=aws.s3 in BLACKWATCH_TOKENS>"
$env:AWS_PROFILE = "default"
python scripts\s3_bucket_inventory.py
```

You need a token in `BLACKWATCH_TOKENS` that maps to module `aws.s3`. Add it
to your BlackWatch container's environment if it's not there yet:

```
BLACKWATCH_TOKENS="devtoken:generic,vpntoken:vpn.openvpn,s3token:aws.s3"
```

Restart BW after adding, then re-run the script with `s3token` as the value.

If BW isn't running locally, you can dump to a file instead:

```powershell
$env:AWS_PROFILE = "default"
python scripts\s3_bucket_inventory.py --out s3-snapshot.json
# inspect the file; later POST it manually with curl
```

After a successful bootstrap, the **S3** tab shows every bucket with its
posture (public / private, encryption, versioning, BPA, logging) — including
any that were already in a bad state.

## 4. Wire ongoing drift detection (the connector)

Settings → **Add S3 drift connector**:

- Name: `s3 inventory`
- AWS profile: `blackwatch`
- Scan interval: `3600` (1 hour)

Save → Test → Enable. Every hour the connector rescans, compares to the stored
state, and emits transition events:

| Event | When | Severity |
|---|---|---|
| `s3.bucket.public` | A previously-private bucket is now public | critical |
| `s3.bucket.public_removed` | A previously-public bucket is no longer public | informational |
| `s3.bucket.unencrypted` | Encryption was removed (or new bucket found without it) | high |
| `s3.bucket.encryption_added` | Encryption was added back | informational |
| `s3.bucket.versioning_suspended` | Versioning was suspended from Enabled | high |
| `s3.bucket.logging_disabled` | Logging target was removed | medium |
| `s3.bucket.first_seen` | A new bucket appeared | informational |
| `s3.bucket.disappeared` | A previously-tracked bucket is gone from inventory | high |

## 5. What's NOT done by this module

- **Object scanning** — Phase 3 (ClamAV-on-ECS) covers malware in user-uploaded objects. Separate setup.
- **Server access log analysis** — high-volume, queue-then-process pattern. Defer.
- **Cross-region tracking** — `ListBuckets` is global; per-bucket region detection is built in. You don't need a per-region connector.
- **Lifecycle / replication rule sanity** — captured as raw CloudTrail events; no detection rules yet (intentionally — most lifecycle changes are ops, not security).
