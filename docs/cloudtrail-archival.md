# CloudTrail Archival Pipeline

Automated monthly consolidation of CloudTrail logs from the live source bucket
into a long-term Glacier Deep Archive bucket. Runs unattended on the monitoring
EC2. Keeps the last 3 calendar months hot (queryable in the source bucket) and
moves everything older to cheap cold storage for the 7-year compliance window.

---

## 1. Overview

**Problem** — CloudTrail writes many small `.json.gz` objects to S3 continuously
(one per API call batch per region, roughly every 5 minutes). Over years this
becomes hundreds of thousands to millions of tiny objects. Applying a lifecycle
rule to move each one to Deep Archive is expensive: per-object transition cost
+ 40 KB metadata overhead billed forever per object.

**Solution** — Bundle each month's per-region files into a single tarball,
upload that tar with `--storage-class DEEP_ARCHIVE`, delete the originals.
Instead of 1.4M objects transitioning, we have ~24 per year (12 months × 2
regions). Same data, negligible transition + overhead cost.

**Retention target** — Source bucket keeps the current month + previous 2
(3 months of live-queryable data). Archive bucket keeps everything for 7 years,
then auto-expires.

---

## 2. Architecture

```
                    CloudTrail (live delivery)
                             │
                             ▼
             ┌─────────────────────────────────┐
             │ SOURCE BUCKET                   │
             │ aws-cloudtrail-logs-...-58aad3c4│
             │ (rolling ~3 months, Standard)   │
             └────────────────┬────────────────┘
                              │
             [monthly systemd timer, 1st @ 03:00 UTC]
                              │
                              ▼
             ┌─────────────────────────────────┐
             │ /opt/blackwatch/                │
             │   cloudtrail_archive.py         │
             │                                 │
             │  1. List src objects for month  │
             │  2. Download (64 threads)       │
             │  3. tar → 1 file per region     │
             │  4. Upload to Deep Archive      │
             │  5. Verify (HEAD + size match)  │
             │  6. Delete src objects          │
             │  7. Mark DONE in state file     │
             │  8. Send SES notification       │
             └────────────────┬────────────────┘
                              │
                              ▼
             ┌─────────────────────────────────┐
             │ ARCHIVE BUCKET                  │
             │ cloudtrail-archive-longhealth   │
             │ (Glacier Deep Archive, 7yr)    │
             └─────────────────────────────────┘
```

---

## 3. AWS Resources

### Source bucket

- **Name**: `aws-cloudtrail-logs-095899260107-58aad3c4`
- **Region**: `us-west-1`
- **Purpose**: CloudTrail delivery target. Auto-managed by CloudTrail.
- **Layout**: `AWSLogs/{account}/CloudTrail/{region}/{YYYY}/{MM}/{DD}/*.json.gz`
- **Contents post-pipeline**: only prefixes for the current month + previous 2

### Archive bucket

- **Name**: `cloudtrail-archive-longhealth`
- **Region**: `us-west-1` (same as source and EC2 → transfer is free)
- **Storage class**: everything lands in Glacier Deep Archive on Day 0
  (lifecycle rule fallback in case something uploads without `--storage-class`)
- **Public access**: fully blocked
- **Encryption**: SSE-S3 (AES-256)
- **Retention**: expire after **2555 days (7 years)**
- **Layout**:
  - `backlog/cloudtrail-{YYYY}-{MM}-{region}.tar` — initial one-time backlog
  - `monthly/cloudtrail-{YYYY}-{MM}-{region}.tar` — future ongoing runs
    (script currently writes to `backlog/`; if you want ongoing under a
    different prefix, change `archive_key = f"backlog/..."` in the script)

### Lifecycle rule on archive bucket

```json
{
  "Rules": [{
    "ID": "DA-Day0-Expire7yr",
    "Status": "Enabled",
    "Filter": {},
    "Transitions": [{"Days": 0, "StorageClass": "DEEP_ARCHIVE"}],
    "Expiration": {"Days": 2555}
  }]
}
```

---

## 4. IAM

Attached to the EC2 instance role `blackwatch-manager-role` as inline policy
`cloudtrail-archive`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SourceBucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::aws-cloudtrail-logs-095899260107-58aad3c4"
    },
    {
      "Sid": "SourceObjectReadDelete",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::aws-cloudtrail-logs-095899260107-58aad3c4/*"
    },
    {
      "Sid": "ArchiveBucketReadWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:PutObjectTagging", "s3:GetObject"],
      "Resource": "arn:aws:s3:::cloudtrail-archive-longhealth/*"
    },
    {
      "Sid": "ArchiveBucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::cloudtrail-archive-longhealth"
    }
  ]
}
```

And a separate inline policy `ses-send-cta` for SES notifications:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ses:SendEmail", "ses:SendRawEmail"],
    "Resource": [
      "arn:aws:ses:us-west-1:095899260107:identity/mail.longhealth.io",
      "arn:aws:ses:us-west-1:095899260107:configuration-set/*"
    ]
  }]
}
```

`s3:GetObject` on the archive bucket is needed by `HeadObject`, which the
script uses for verify-before-delete.

---

## 5. Component Locations

| Path | Purpose |
|---|---|
| `/opt/blackwatch/cloudtrail_archive.py` | The archive script itself |
| `/var/lib/cloudtrail-archive/state.json` | Per-month-region tracking (idempotent resume) |
| `/var/lib/cloudtrail-archive/work/` | Temporary download + tar workspace (auto-cleaned each run) |
| `/var/log/cloudtrail-archive.log` | All script output (also duplicated to journald) |
| `/etc/systemd/system/cloudtrail-archive.service` | systemd unit that runs the script |
| `/etc/systemd/system/cloudtrail-archive.timer` | Schedule (1st of month, 03:00 UTC) |
| `/etc/logrotate.d/cloudtrail-archive` | Monthly log rotation, 12-month retention |

---

## 6. How It Runs

### Modes

```
python3 /opt/blackwatch/cloudtrail_archive.py --mode=backlog   # everything older than the keep window
python3 /opt/blackwatch/cloudtrail_archive.py --mode=monthly   # single month that just crossed the boundary
python3 /opt/blackwatch/cloudtrail_archive.py --mode=backlog --force  # retry FAILED entries
```

### Constants (top of script)

```python
SOURCE_BUCKET  = "aws-cloudtrail-logs-095899260107-58aad3c4"
ARCHIVE_BUCKET = "cloudtrail-archive-longhealth"
ACCOUNT_ID     = "095899260107"
REGIONS        = ["us-west-1", "us-east-1"]
KEEP_MONTHS    = 2   # keep current + previous KEEP_MONTHS in source
BACKLOG_START  = (2024, 1)
```

`KEEP_MONTHS = 2` means the source bucket retains **3 calendar months** total
(the current month + 2 previous). Everything else is archived.

### Per-month processing (atomic)

For each `(year, month, region)` combination the script:

1. Checks state — skips if already `DONE`
2. Marks `IN_PROGRESS` in state, checkpoints to disk
3. Lists all source objects under
   `AWSLogs/{account}/CloudTrail/{region}/{YYYY}/{MM}/`
4. Downloads all objects into `/var/lib/cloudtrail-archive/work/{key}/`
   using 64 threads with a 100-connection pool
5. Creates a single tar: `cloudtrail-{YYYY}-{MM}-{region}.tar`
6. Uploads with `--storage-class DEEP_ARCHIVE` to
   `s3://cloudtrail-archive-longhealth/backlog/cloudtrail-{YYYY}-{MM}-{region}.tar`
7. Verifies via HeadObject — size on S3 must equal local tar size
8. Deletes source objects in batches of 1000
9. Cleans up local work directory + tar
10. Marks `DONE` with metadata (object count, source bytes, tar bytes, timestamp)

Any failure marks `FAILED` in state, records the error, and continues to the
next month-region. Source objects are never deleted unless verification passes.

### Concurrency + speed

- 64 download threads
- 100 connection pool
- Typical throughput: ~500 objects/sec = ~20 MB/s
- A 4 GB month with 25K objects processes in ~5 minutes

---

## 7. State Tracking

`/var/lib/cloudtrail-archive/state.json` is a flat JSON dictionary. Written
atomically (temp file + rename) after every status change so a crash never
corrupts state.

```json
{
  "2024-12_us-west-1": {
    "status": "DONE",
    "started_at": "2026-07-30T18:33:20.123456+00:00",
    "src_object_count": 16878,
    "src_bytes": 699529687,
    "tar_bytes": 729808896,
    "archive_key": "backlog/cloudtrail-2024-12-us-west-1.tar",
    "completed_at": "2026-07-30T18:34:05.014789+00:00"
  },
  "2024-12_us-east-1": { "status": "DONE", "..." : "..." },
  "2025-01_us-west-1": {
    "status": "FAILED",
    "started_at": "...",
    "failed_at": "...",
    "error": "An error occurred (403) when calling the HeadObject operation: Forbidden"
  }
}
```

Statuses:
- `DONE` — successful, source deleted
- `FAILED` — verification or upload failed, source still present
- `IN_PROGRESS` — crashed mid-run, will restart from scratch on next invocation

---

## 8. Notification (SES)

Every run sends one email via SES to `apoorva.sharma@longhealth.io`
from `alerts@mail.longhealth.io`.

### Subject line examples

- `May 2026 - CloudTrail logs archived successfully`
- `May 2026 - CloudTrail archive FAILED`
- `CloudTrail archive check - nothing new to do`
- `May 2026 and June 2026 - CloudTrail logs archived successfully` (multi-month)
- `4 months - CloudTrail logs archived successfully` (backlog)

### Body example (success)

```
May 2026 CloudTrail logs have been archived to the long-term storage bucket.

25,432 objects (2.10 GB) moved to Deep Archive.

Run completed: 01 Aug 2026, 03:04 UTC
Mode: monthly

Newly archived:
  2026-05_us-west-1  |  22,145 objects  |  2000.5 MB source  |  2048.1 MB tar
  2026-05_us-east-1  |   3,287 objects  |   100.5 MB source  |   103.2 MB tar

Moved from:  aws-cloudtrail-logs-095899260107-58aad3c4
Moved to:    cloudtrail-archive-longhealth (S3 Glacier Deep Archive)

Log file: /var/log/cloudtrail-archive.log
```

### Body example (failure)

```
CloudTrail archive run for May 2026 failed. See details below.

Run completed: 01 Aug 2026, 03:04 UTC
Mode: monthly

Failures:
  2026-05_us-west-1  |  reason: An error occurred (403) when calling HeadObject: Forbidden

Skipped (already processed in a prior run): 0

Moved from:  aws-cloudtrail-logs-095899260107-58aad3c4
Moved to:    cloudtrail-archive-longhealth (S3 Glacier Deep Archive)

Log file: /var/log/cloudtrail-archive.log
```

---

## 9. Scheduling

### systemd service — `cloudtrail-archive.service`

```ini
[Unit]
Description=CloudTrail archive - monthly consolidation to Deep Archive
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/bin/python3 /opt/blackwatch/cloudtrail_archive.py --mode=monthly
StandardOutput=journal
StandardError=journal
Nice=10
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target
```

`Nice=10 + IOSchedulingClass=idle` means the script only uses CPU/IO the system
isn't already using — never starves BW or Wazuh.

### systemd timer — `cloudtrail-archive.timer`

```ini
[Unit]
Description=Monthly CloudTrail archive - 1st of each month at 03:00 UTC

[Timer]
OnCalendar=*-*-01 03:00:00 UTC
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
```

- `OnCalendar=*-*-01 03:00:00 UTC` — 1st of every month, 03:00 UTC exactly
- `Persistent=true` — if EC2 was down at 03:00 UTC on the 1st, timer runs when
  the box comes back up (catch-up behaviour)
- `AccuracySec=1m` — fires within 1 minute of scheduled time

### Timezone alignment

Both AWS CloudTrail (S3 prefix uses UTC) and our timer (`03:00:00 UTC`) run on
UTC. No timezone drift possible. Running on the **1st** with `KEEP_MONTHS = 2`
processes the month that ended **~2 months prior**, so every event has had
plenty of time to be delivered.

---

## 10. Log Rotation

`/etc/logrotate.d/cloudtrail-archive`:

```
/var/log/cloudtrail-archive.log {
    su root root
    monthly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

Runs from the system-wide `logrotate` cron. Keeps 12 months of gzipped history
on disk (`.log`, `.log.1`, `.log.2.gz` ... `.log.12.gz`). Anything older is
deleted. Total disk footprint stays bounded — realistically under 100 MB
lifetime for text logs.

---

## 11. Operations Runbook

### Check the timer

```bash
systemctl list-timers cloudtrail-archive.timer
systemctl status cloudtrail-archive.timer
```

Shows next scheduled run and last invocation.

### Check the last run's output

```bash
sudo journalctl -u cloudtrail-archive.service -n 200 --no-pager
sudo tail -100 /var/log/cloudtrail-archive.log
```

### State summary

```bash
sudo cat /var/lib/cloudtrail-archive/state.json | python3 -c "
import json, sys
s = json.load(sys.stdin)
d = sum(1 for e in s.values() if e.get('status') == 'DONE')
f = sum(1 for e in s.values() if e.get('status') == 'FAILED')
i = sum(1 for e in s.values() if e.get('status') == 'IN_PROGRESS')
gb = sum(e.get('src_bytes', 0) for e in s.values()) / 1024**3
print(f'DONE={d}  FAILED={f}  IN_PROGRESS={i}  Total moved: {gb:.2f} GB')
"
```

### Manual run (ad-hoc)

```bash
# Test a run without waiting for the timer:
sudo python3 /opt/blackwatch/cloudtrail_archive.py --mode=monthly

# Reprocess anything currently marked FAILED:
sudo python3 /opt/blackwatch/cloudtrail_archive.py --mode=monthly --force

# Full historic sweep (idempotent — only re-does non-DONE entries):
sudo python3 /opt/blackwatch/cloudtrail_archive.py --mode=backlog
```

For long backlog runs, use `tmux` so an SSH/SSM disconnect doesn't kill it:

```bash
tmux new -s cta 'sudo python3 /opt/blackwatch/cloudtrail_archive.py --mode=backlog; echo DONE; sleep 300'
# Ctrl+B then D to detach
# tmux attach -t cta to reattach
```

### Trigger the timer manually (no waiting)

```bash
sudo systemctl start cloudtrail-archive.service
```

### Reset a specific month for re-processing

```bash
sudo python3 -c "
import json
p = '/var/lib/cloudtrail-archive/state.json'
s = json.load(open(p))
s.pop('2026-05_us-west-1', None)  # ← change key
json.dump(s, open(p, 'w'), indent=2, sort_keys=True)
"
sudo python3 /opt/blackwatch/cloudtrail_archive.py --mode=backlog
```

### Verify archive bucket contents

```bash
aws s3 ls s3://cloudtrail-archive-longhealth/backlog/ --summarize --human-readable
```

### Verify source bucket is trimmed correctly

```bash
aws s3 ls s3://aws-cloudtrail-logs-095899260107-58aad3c4/AWSLogs/095899260107/CloudTrail/us-west-1/
```

Should show only the current month + previous 2 (three `YYYY/` or `MM/` subdirs).

---

## 12. Troubleshooting

### "AccessDenied" during upload / verify / delete

Instance role IAM policy is missing a permission. Check current permissions:

```bash
aws iam get-role-policy --role-name blackwatch-manager-role --policy-name cloudtrail-archive
```

Required permissions listed in Section 4. Common gap: `s3:GetObject` on
archive bucket (needed for HeadObject verification).

### Script running slow

Check `max_workers` and `max_pool_connections` in the script. Defaults are
64 and 100 respectively. Bumping higher rarely helps because throughput is
bounded by network egress on the EC2 network interface.

### "Connection pool is full" warnings

`max_pool_connections` (currently 100) is lower than `max_workers` (currently
64). Bump the pool higher if you increase workers.

### Disk fills up during a run

Work dir is `/var/lib/cloudtrail-archive/work/`. Under load a single month can
transiently use up to 2× the source size (raw download + tar). Check:

```bash
df -h /
du -sh /var/lib/cloudtrail-archive/work/
```

If the run crashed mid-way and left files, they get cleaned on next run. Safe
to `rm -rf /var/lib/cloudtrail-archive/work/` if the script is not currently
running.

### No email received

- Check SES sandbox status (recipient must be verified if in sandbox):
  ```bash
  aws ses get-identity-verification-attributes --region us-west-1 \
      --identities apoorva.sharma@longhealth.io
  ```
- Check IAM policy `ses-send-cta` has both `identity/*` and
  `configuration-set/*` resources
- Check script log for `SES notification failed` lines

### Timer says "inactive" or missing

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cloudtrail-archive.timer
sudo systemctl list-timers cloudtrail-archive.timer
```

---

## 13. Cost

### Per-month steady-state

| Item | Estimate |
|---|---|
| Ops (LIST + GET + PUT + DELETE requests, ~30K objects) | **$0.012/month** |
| Archive storage (grows over time — see below) | **$0.008 → $0.78/month** |
| Data transfer (all us-west-1 → us-west-1) | **$0** |
| Source bucket storage (3 months rolling) | **~$0.30/month** (12 GB × $0.026) |

### Archive storage growth

Assuming ~4 GB/month CloudTrail volume:

| Time from now | Archive size | Monthly bill |
|---|---|---|
| Month 1 | ~5 GB | $0.01 |
| Year 1 | ~55 GB | $0.11 |
| Year 3 | ~200 GB | $0.40 |
| Year 5 | ~295 GB | $0.59 |
| Year 7 | ~391 GB | $0.78 |

### One-time backlog cost (already paid)

The initial ~40 GB historic consolidation cost:

- GET requests to read ~1.4M source objects: ~$0.56
- PUT requests for ~50 tarballs: ~$0.003
- Data transfer (same region): $0
- **Total one-time**: ~$0.56

### 7-year all-in TCO

**~$38** including backlog, ongoing storage, requests, and ops.

Compare to naïve "just apply a lifecycle rule directly to DA" which would cost
~$155 over 7 years (mostly the $84 one-time transition fee + ~$4.60/year in
per-object metadata overhead). **Savings: ~$117 over 7 years** for ~2 hours of
one-time setup.

---

## 14. Design Decisions & Constraints

### Why monthly bundling, not daily

- Deep Archive charges per-object 40 KB metadata forever. Daily bundles would
  mean ~365 objects/year/region instead of 12 — more metadata cost, more
  transition fees, more retrieval complexity.
- Recovery workflow (auditor asks for "August 2024 CloudTrail") pulls one tar
  instead of hunting through 30 daily bundles.

### Why 3 months hot instead of 90 days

- Aligns with calendar-month boundaries (matches how audit questions are
  usually framed).
- Simplifies the mental model — the source bucket always contains "this month,
  last month, month before".

### Why 03:00 UTC on the 1st

- Off-hours in the primary usage region (US west coast is 19:00 previous day).
- The month being archived ended 2+ months ago — any late CloudTrail
  deliveries have had plenty of time to settle.

### Why verify before delete

- CloudTrail data is compliance evidence. Losing any of it during a botched
  transfer is unacceptable.
- HeadObject + size match catches partial uploads (the most common failure
  mode for large multipart transfers).
- SHA1 of the tar isn't compared to a sum of source SHA1s because those don't
  compose (tar wraps the files with metadata). Size match on the uploaded
  object is the pragmatic strongest check.

### Why not use `aws s3 sync` or Kinesis Firehose

- `aws s3 sync` doesn't produce a bundled artifact — it copies file-for-file,
  which defeats the consolidation goal.
- Firehose would work but requires configuring EventBridge triggers,
  provisioning Firehose delivery streams, and a second processing bucket.
  Overkill for a pipeline that just needs to run monthly.

### Why not delete IAM read/delete on source right after the run

- The permission is scoped to the specific source bucket, so blast radius is
  the CloudTrail bucket alone.
- Rotating the permission each run would double the operational surface for
  minimal gain.

---

## 15. Change History

- **2026-07-30** — Initial deployment. Backlog processed: 54 month-region
  combos, 39.76 GB moved to Deep Archive. Timer scheduled for first automated
  run on 2026-08-01 03:00 UTC.
