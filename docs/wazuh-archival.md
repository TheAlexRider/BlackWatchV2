# Wazuh Archival Pipeline

Automated monthly consolidation of Wazuh manager logs from the local docker
volume into a long-term Glacier Deep Archive bucket. Runs unattended on the
monitoring EC2. Keeps the last 3 calendar months hot on disk (searchable in
the Wazuh dashboard) and moves everything older to cheap cold storage for the
7-year compliance window.

---

## 1. Overview

**Problem** — Wazuh manager writes daily log files under `/var/ossec/logs/`
inside the manager container. Over time this fills the EC2 disk. Keeping years
of `.json.gz` files on the box is wasteful — after 3 months, the dashboard
never queries them and their only remaining value is compliance evidence.

**Solution** — Bundle each month's per-feed directory into a single tarball,
upload with `--storage-class DEEP_ARCHIVE` to S3, then delete the local
directory. Same monthly bundling pattern as the CloudTrail pipeline. Restore
is plug-and-play: extract the tar and the month directory drops straight back
into `/var/ossec/logs/{archives,alerts}/YYYY/`.

**Retention target** — Local disk keeps the current month + previous 2
(3 months of live-queryable data on the Wazuh dashboard). Archive bucket
keeps everything for 7 years, then auto-expires.

---

## 2. Architecture

```
Wazuh manager (docker container: single-node-wazuh.manager-1)
        │
        │ writes to /var/ossec/logs/{archives,alerts}/YYYY/MMM/
        ▼
docker volume: single-node_wazuh_logs
        │
        │ host path:
        │ /var/lib/docker/volumes/single-node_wazuh_logs/_data/
        │     ├── archives/YYYY/MMM/ossec-archive-DD.{json.gz,log.gz,sum}
        │     └── alerts/YYYY/MMM/ossec-alerts-DD.{json.gz,log.gz,sum}
        │
[monthly systemd timer, 1st @ 04:00 UTC]
        │
        ▼
/opt/blackwatch/wazuh_archive.py
   1. Walk local dirs, find months older than KEEP window
   2. tar each month directory (per feed)
   3. Upload with --storage-class DEEP_ARCHIVE
   4. Verify (HEAD + size match)
   5. rm -rf local monthly directory
   6. Mark DONE in state file
   7. SES notification
        │
        ▼
s3://wazuh-archive-longhealth/monthly/
   ├── archives-2026-May.tar
   ├── alerts-2026-May.tar
   ├── archives-2026-Jun.tar
   └── ...
```

---

## 3. AWS Resources

### Archive bucket

- **Name**: `wazuh-archive-longhealth`
- **Region**: `us-west-1` (same as EC2 → transfer is free)
- **Storage class**: Glacier Deep Archive on Day 0 (lifecycle rule fallback in
  case something uploads without the storage-class flag)
- **Public access**: fully blocked
- **Encryption**: SSE-S3 (AES-256)
- **Retention**: expire after **2555 days (7 years)**
- **Layout**:
  - `backlog/{feed}-{YYYY}-{Mon}.tar` — initial one-time historical import
    from the Lightsail decommissioning (Jan 2024 → March 2026, 34 tars)
  - `monthly/{feed}-{YYYY}-{Mon}.tar` — ongoing automated runs

Bucket was created and configured during the CloudTrail phase using the same
lifecycle rule template.

### Lifecycle rule on archive bucket

```json
{
  "Rules": [{
    "ID": "AllToDeepArchiveDay0",
    "Status": "Enabled",
    "Filter": {},
    "Transitions": [{"Days": 0, "StorageClass": "DEEP_ARCHIVE"}]
  }]
}
```

Note: the initial bucket setup did not include an expiration rule. Add one
if you want strict 7-year purge (matches CloudTrail bucket):

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket wazuh-archive-longhealth \
  --lifecycle-configuration '{"Rules":[{"ID":"DA-Day0-Expire7yr","Status":"Enabled","Filter":{},"Transitions":[{"Days":0,"StorageClass":"DEEP_ARCHIVE"}],"Expiration":{"Days":2555}}]}'
```

### Source (local filesystem — no S3 involved on the source side)

Wazuh manager container mounts `single-node_wazuh_logs` at `/var/ossec/logs`.
Host-side that resolves to:

```
/var/lib/docker/volumes/single-node_wazuh_logs/_data/
    archives/            ← full raw event stream
    alerts/              ← rules that matched
    firewall/            ← firewall events (not archived by design)
    wazuh/               ← internal state (not archived)
    api/                 ← Wazuh API access log (not archived)
    ossec.log            ← manager daemon log (not archived)
    ossec.json           ← daemon log in JSON (not archived)
    cluster.log          ← cluster daemon (not archived, empty on single-node)
```

Only `archives/` and `alerts/` are in scope for archival — those are the
compliance evidence. The rest are operational/daemon logs, small, and stay
local.

---

## 4. IAM

Attached to the EC2 instance role `blackwatch-manager-role` as inline policy
`wazuh-archive`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ArchiveBucketReadWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:PutObjectTagging", "s3:GetObject"],
      "Resource": "arn:aws:s3:::wazuh-archive-longhealth/*"
    },
    {
      "Sid": "ArchiveBucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::wazuh-archive-longhealth"
    }
  ]
}
```

`s3:GetObject` is required for `HeadObject` (used by verify-before-delete).

SES notification reuses the `ses-send-cta` policy already attached for the
CloudTrail pipeline — same email identity, no additional IAM changes needed.

---

## 5. Component Locations

| Path | Purpose |
|---|---|
| `/opt/blackwatch/wazuh_archive.py` | The archive script |
| `/var/lib/wazuh-archive/state.json` | Per-month-feed tracking (idempotent resume) |
| `/var/lib/wazuh-archive/work/` | Temporary tar workspace (auto-cleaned each run) |
| `/var/log/wazuh-archive.log` | All script output (also duplicated to journald) |
| `/etc/systemd/system/wazuh-archive.service` | systemd unit |
| `/etc/systemd/system/wazuh-archive.timer` | Schedule (1st of month, 04:00 UTC) |
| `/etc/logrotate.d/wazuh-archive` | Monthly log rotation, 12-month retention |
| `/var/lib/docker/volumes/single-node_wazuh_logs/_data/{archives,alerts}/` | Source (read) — Wazuh's daily log dirs |

---

## 6. How It Runs

### Modes

```
python3 /opt/blackwatch/wazuh_archive.py --mode=backlog          # everything older than the keep window
python3 /opt/blackwatch/wazuh_archive.py --mode=monthly          # single month that just crossed the boundary
python3 /opt/blackwatch/wazuh_archive.py --mode=backlog --force  # retry FAILED entries
```

### Constants (top of script)

```python
ARCHIVE_BUCKET = "wazuh-archive-longhealth"
WAZUH_DATA_DIR = Path("/var/lib/docker/volumes/single-node_wazuh_logs/_data")
FEEDS          = ["archives", "alerts"]
KEEP_MONTHS    = 2   # keep current + previous KEEP_MONTHS on disk
```

`KEEP_MONTHS = 2` → local disk retains **3 calendar months** total (current
month + 2 previous). Anything older gets archived.

### Per-month processing (atomic)

For each `(year, month, feed)` the script:

1. Checks state — skips if already `DONE`
2. If the source directory doesn't exist locally, marks `DONE` with zero
   bytes (nothing to do for that month)
3. Marks `IN_PROGRESS` in state, checkpoints to disk
4. Walks the source directory: `WAZUH_DATA_DIR/{feed}/{YYYY}/{Mon}/`
5. Creates tar directly from local disk into
   `/var/lib/wazuh-archive/work/{feed}-{YYYY}-{Mon}.tar`.
   Tar is built with `arcname=Mon` so the archive contains just `Mon/...`
   entries — restore is plug-and-play into the correct year folder.
6. Uploads with `--storage-class DEEP_ARCHIVE` to
   `s3://wazuh-archive-longhealth/monthly/{feed}-{YYYY}-{Mon}.tar`
7. Verifies via HeadObject — size on S3 must equal local tar size
8. `rm -rf` the local monthly directory
9. Cleans up local tar
10. Marks `DONE` with metadata (file count, source bytes, tar bytes, timestamp)

Any failure marks `FAILED` in state and continues to the next month-feed.
Source directory is never deleted unless upload + verification succeed.

### Backlog vs monthly month discovery

- **Backlog mode**: walks `WAZUH_DATA_DIR/{feed}/` on disk, finds every
  `YYYY/MMM/` combination that exists, filters to only those older than the
  cutoff. Iterates in chronological order (oldest first).
- **Monthly mode**: computes the single month that just crossed the age
  boundary (e.g., on 2026-11-01 with `KEEP_MONTHS=2`, processes 2026-Aug).

### No download step

Unlike CloudTrail (which pulls from a source S3 bucket first), Wazuh's source
is local disk on the same box. Tar is built directly from the mount, so the
whole run is much faster than the equivalent CloudTrail run. Typical monthly
archival of ~4 GB completes in under a minute.

---

## 7. State Tracking

`/var/lib/wazuh-archive/state.json` is a flat JSON dictionary. Written
atomically (temp file + rename) after every status change so a crash never
corrupts state.

```json
{
  "2026-May_archives": {
    "status": "DONE",
    "started_at": "2026-08-01T04:00:12.345678+00:00",
    "src_object_count": 124,
    "src_bytes": 3980000000,
    "tar_bytes": 3980500000,
    "archive_key": "monthly/archives-2026-May.tar",
    "completed_at": "2026-08-01T04:00:58.111222+00:00"
  },
  "2026-May_alerts": { "status": "DONE", "..." : "..." }
}
```

Statuses:
- `DONE` — successful, local dir deleted (or was already empty)
- `FAILED` — verification or upload failed, local dir still present
- `IN_PROGRESS` — crashed mid-run, will restart from scratch on next invocation

---

## 8. Notification (SES)

Every run sends one email via SES to `apoorva.sharma@longhealth.io`
from `alerts@mail.longhealth.io`.

### Subject line examples

- `May 2026 - Wazuh logs archived successfully`
- `May 2026 - Wazuh archive FAILED`
- `Wazuh archive check - nothing new to do`
- `May 2026 and June 2026 - Wazuh logs archived successfully`
- `4 months - Wazuh logs archived successfully` (backlog)

### Body example (success)

```
May 2026 Wazuh logs have been archived to the long-term storage bucket.

156 files (3.98 GB) moved to Deep Archive and removed from disk.

Run completed: 01 Aug 2026, 04:00 UTC
Mode: monthly

Newly archived:
  2026-May_archives  |  124 files  |  3800.1 MB source  |  3801.0 MB tar
  2026-May_alerts    |   32 files  |     2.5 MB source  |     2.7 MB tar

Moved from:  local disk on monitoring EC2 (Wazuh manager /var/ossec/logs)
Moved to:    wazuh-archive-longhealth (S3 Glacier Deep Archive)

Log file: /var/log/wazuh-archive.log
```

### Body example (nothing to do)

Very common in the first few months of the pipeline (until Wazuh has
accumulated 3+ months of data on the new EC2):

```
Wazuh archive checked. Everything is already up to date.

Run completed: 01 Aug 2026, 04:00 UTC
Mode: monthly

Moved from:  local disk on monitoring EC2 (Wazuh manager /var/ossec/logs)
Moved to:    wazuh-archive-longhealth (S3 Glacier Deep Archive)

Log file: /var/log/wazuh-archive.log
```

---

## 9. Scheduling

### systemd service — `wazuh-archive.service`

```ini
[Unit]
Description=Wazuh archive - monthly consolidation to Deep Archive
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/bin/python3 /opt/blackwatch/wazuh_archive.py --mode=monthly
StandardOutput=journal
StandardError=journal
Nice=10
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target
```

`Nice=10 + IOSchedulingClass=idle` means the script only uses CPU/IO the
system isn't already using — Wazuh manager traffic + BW traffic take
precedence.

### systemd timer — `wazuh-archive.timer`

```ini
[Unit]
Description=Monthly Wazuh archive - 1st of each month at 04:00 UTC

[Timer]
OnCalendar=*-*-01 04:00:00 UTC
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
```

- Fires **04:00 UTC on the 1st** — one hour after the CloudTrail pipeline so
  they don't compete for disk I/O
- `Persistent=true` → if EC2 was down at 04:00 UTC on the 1st, timer runs
  when the box comes back
- `AccuracySec=1m` → fires within 1 minute of scheduled time

### Timezone / boundary safety

Wazuh's manager container also writes logs in UTC (systemd/OS timezone),
and the timer runs `04:00:00 UTC` explicitly. `KEEP_MONTHS = 2` gives 2+
months of buffer before a month becomes archive-eligible, so there is zero
risk of archiving a month that still has late writes coming in.

---

## 10. Log Rotation

`/etc/logrotate.d/wazuh-archive`:

```
/var/log/wazuh-archive.log {
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
(`.log`, `.log.1`, `.log.2.gz` ... `.log.12.gz`). Anything older is deleted.
Total disk footprint stays bounded — realistically under 100 MB lifetime for
text logs.

---

## 11. Operations Runbook

### Check the timer

```bash
systemctl list-timers wazuh-archive.timer
systemctl status wazuh-archive.timer
```

Shows next scheduled run and last invocation.

### Check the last run's output

```bash
sudo journalctl -u wazuh-archive.service -n 200 --no-pager
sudo tail -100 /var/log/wazuh-archive.log
```

### State summary

```bash
sudo cat /var/lib/wazuh-archive/state.json | python3 -c "
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
sudo python3 /opt/blackwatch/wazuh_archive.py --mode=monthly

# Reprocess anything currently marked FAILED:
sudo python3 /opt/blackwatch/wazuh_archive.py --mode=monthly --force

# Sweep everything on disk older than the keep window:
sudo python3 /opt/blackwatch/wazuh_archive.py --mode=backlog
```

### Trigger the timer manually (no waiting)

```bash
sudo systemctl start wazuh-archive.service
```

### Reset a specific month for re-processing

```bash
sudo python3 -c "
import json
p = '/var/lib/wazuh-archive/state.json'
s = json.load(open(p))
s.pop('2026-May_archives', None)  # ← change key
json.dump(s, open(p, 'w'), indent=2, sort_keys=True)
"
```

Then re-run `--mode=backlog` (only re-does non-DONE entries).

### Verify archive bucket contents

```bash
aws s3 ls s3://wazuh-archive-longhealth/monthly/ --summarize --human-readable
```

### Verify local disk is trimmed correctly

```bash
sudo ls /var/lib/docker/volumes/single-node_wazuh_logs/_data/archives/
sudo ls /var/lib/docker/volumes/single-node_wazuh_logs/_data/alerts/
```

Should show only the current year's directory, and inside it only the current
month + previous 2.

### Restore a specific month back into Wazuh (for audit)

1. Find the tar in the archive bucket (`aws s3 ls s3://wazuh-archive-longhealth/monthly/`)
2. Initiate a Bulk retrieval (~48 hours, ~$0.0035/GB):
   ```bash
   aws s3api restore-object --bucket wazuh-archive-longhealth --key monthly/archives-2026-May.tar --restore-request '{"Days":7,"GlacierJobParameters":{"Tier":"Bulk"}}'
   ```
3. When retrieval completes (check with `aws s3api head-object`), download:
   ```bash
   aws s3 cp s3://wazuh-archive-longhealth/monthly/archives-2026-May.tar /tmp/
   ```
4. Extract into place — because tars are built with `arcname=Mon`, the tar
   contains just `May/...` entries. Drop straight in:
   ```bash
   sudo tar -xf /tmp/archives-2026-May.tar -C /var/lib/docker/volumes/single-node_wazuh_logs/_data/archives/2026/
   ```
5. Wazuh manager sees the files immediately (they're in its live directory
   structure). Search from dashboard as normal.
6. When done, delete `May/` directory again (or let the archive script pick it
   up on next run — it will re-archive if it's older than the keep window).

---

## 12. Troubleshooting

### "AccessDenied" during upload / verify

Instance role IAM policy is missing a permission. Check current permissions:

```bash
aws iam get-role-policy --role-name blackwatch-manager-role --policy-name wazuh-archive
```

Required permissions listed in Section 4. Common gap: `s3:GetObject` on the
archive bucket (needed for HeadObject verification).

### Local source directory doesn't exist

Script marks the month as DONE with `src_object_count=0`. This is normal for
months when Wazuh wasn't running or had no traffic. Not an error.

### Docker volume path missing

If `/var/lib/docker/volumes/single-node_wazuh_logs/_data/` doesn't exist, the
Wazuh manager container was removed (`docker compose down --volumes`) or the
compose file changed volume names. Verify:

```bash
docker volume ls | grep single-node_wazuh_logs
docker inspect single-node_wazuh_logs | grep Mountpoint
```

Update `WAZUH_DATA_DIR` in the script if the mount path changed.

### Disk fills up during a run

Work dir is `/var/lib/wazuh-archive/work/`. During tar creation, disk needs to
hold ~2× the source month size (raw data + tar). Check:

```bash
df -h /
du -sh /var/lib/wazuh-archive/work/
```

If script crashed mid-way and left files, they get cleaned on next run. Safe
to `rm -rf /var/lib/wazuh-archive/work/` if the script is not running.

### No email received

- Verify SES sandbox status (recipient must be verified while in sandbox):
  ```bash
  aws ses get-identity-verification-attributes --region us-west-1 \
      --identities apoorva.sharma@longhealth.io
  ```
- Verify IAM `ses-send-cta` policy exists (shared with CloudTrail pipeline):
  ```bash
  aws iam get-role-policy --role-name blackwatch-manager-role --policy-name ses-send-cta
  ```
- Check script log for `SES notification failed` lines.

### Timer says "inactive" or missing

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wazuh-archive.timer
sudo systemctl list-timers wazuh-archive.timer
```

### Manager container was recreated — is the mount still the same?

If you `docker compose down` and `up` the Wazuh manager, the named volume
persists — data + our script's assumptions stay valid. If you deliberately
delete the volume (`docker volume rm`), you lose all local Wazuh logs. Archive
bucket copies are unaffected.

---

## 13. Cost

### Per-month steady-state

| Item | Estimate |
|---|---|
| Ops (PUT requests, ~2 tars/month) | **$0.0001/month** |
| Archive storage (grows over time — see below) | **$0.05 → $0.62/month** |
| Data transfer (all us-west-1 → us-west-1) | **$0** |
| Local disk saved (~11 GB kept vs ~300 GB grown over 7yr) | frees EBS capacity |

### Archive storage growth

Assuming ~4 GB/month Wazuh archive volume (per Lightsail-observed rates):

| Time from now | Archive size | Monthly bill |
|---|---|---|
| Backlog already uploaded | ~40 GB | $0.08 |
| +Year 1 growth | ~88 GB | $0.18 |
| Year 3 | ~184 GB | $0.37 |
| Year 5 | ~280 GB | $0.56 |
| Year 7 | ~376 GB | $0.75 |

### One-time backlog cost (already paid)

The initial ~87 GB backlog upload from the Lightsail migration:

- PUT requests: 34 tars × $0.05/1000 = **$0.002**
- Data transfer PC → S3: **$0** (S3 ingress is always free)
- Compute for tar/upload on PC: irrelevant
- **Total one-time**: ~$0.002

### 7-year all-in TCO

**~$45** including backlog, ongoing storage, and requests.

---

## 14. Design Decisions & Constraints

### Why only `archives` + `alerts`

- `archives/` = raw event stream (compliance gold)
- `alerts/` = rules that matched (compliance essential)
- `firewall/`, `wazuh/`, `api/` = operational/diagnostic, small (<1 GB/year
  total), rarely useful post-hoc — not worth the pipeline complexity
- Top-level daemon logs (`ossec.log`, `ossec.json`) rotate on their own and
  are operational, not compliance evidence

### Why monthly bundling, not daily

- Deep Archive charges per-object metadata forever. Daily bundling would mean
  365 tarballs/year/feed instead of 12 — more transition cost, more overhead.
- Restore workflow (auditor asks for "May 2026 alerts") pulls one tar instead
  of 30 daily files.
- Wazuh's own `.json.gz` files are already daily-consolidated — tarring
  monthly is the next logical granularity.

### Why plug-and-play tar layout

- Tar built with `arcname=Mon` so archive contains just `May/...` entries.
- Restore = `tar -xf ... -C /var/ossec/logs/archives/2026/` → done.
- No path munging, no rename step, no permission fix. Extract → Wazuh sees it.

### Why 3 months hot instead of 90 days

- Aligns with calendar-month boundaries (matches how audit questions are
  usually framed — "show me May 2026").
- Simplifies the mental model — the local disk always contains "this month,
  last month, month before".

### Why 04:00 UTC on the 1st

- One hour after CloudTrail's 03:00 UTC run — avoids disk I/O contention on
  the shared EBS volume.
- Off-hours in the primary usage region (US west coast is 20:00 previous day).
- The month being archived ended 2+ months ago — no risk of losing late writes.

### Why verify before delete

- Local Wazuh logs are the primary compliance evidence source. Losing any to
  a botched transfer is unacceptable.
- HeadObject + size match catches partial uploads (most common failure mode).
- The `rm -rf` local directory is destructive and only runs after verify passes.

### Why not use the existing wazuh-archive-longhealth `backlog/` prefix

- `backlog/` was used for the one-time historical import (34 tars, mixed
  format — see Section 15).
- Keeping `backlog/` and `monthly/` separated makes it obvious at a glance
  which tars came from which pipeline run.
- Simplifies retention/reprocessing if we ever need to purge one class.

### Why no separate lifecycle rule for expiration

- The bucket was originally set up with just the Day 0 → Deep Archive rule
  (no expiration). CloudTrail's bucket has expiration at 2555 days.
- Adding the same 2555-day expiration to the Wazuh bucket is one command
  (see Section 3). Deferred until you confirm you want the auto-purge.

---

## 15. Change History

- **2026-07-30** — Initial 87 GB backlog uploaded from Lightsail migration
  (Jan 2024 → March 2026, 34 tars under `backlog/`). Uploaded manually from
  local PC after downloading Lightsail's `/var/ossec/logs/` via rsync.
- **2026-07-31** — Automated pipeline deployed. Script at
  `/opt/blackwatch/wazuh_archive.py`, systemd timer scheduled for first run
  on 2026-08-01 04:00 UTC. First real archival expected ~November 2026 (once
  the new EC2 has accumulated 3+ months of Wazuh data).
