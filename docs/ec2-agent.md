# EC2 host agent — full reference

The canonical document for everything on the BlackWatch EC2 reporter agent:
what it does, where it lives, how to install/upgrade it, what it protects
against, and how to verify it's working.

The quick-start install is at [`deploy/ec2/README.md`](../deploy/ec2/README.md);
read this when you want the *full* picture or are debugging at 3am.

Current agent version: **v1.2** (hardened: scrubbing, sandbox, watchdog,
size caps, send backoff)

---

## 1. What it does

Runs as a systemd service on every EC2 we want monitored. Every `INTERVAL`
seconds (default 60s) it:

1. Reads recent `sshd` + `sudo` lines from `journalctl`.
2. Runs whichever collectors are *due* (each has its own cadence — fast
   ones every minute, FIM-tier every 2 min, heavy ones every 10 min).
3. Samples always-on lightweight metrics (memory, CPU, sessions, OOM,
   rpm-DB health).
4. Builds **one JSON payload** and pushes it to an SQS queue using the
   instance role (no static creds on the box).
5. Spools to disk and replays if SQS is unreachable. Bounded — see
   [Failure modes](#13-failure-modes--recovery).

BlackWatch (running elsewhere, currently in Docker on operator PC, soon
on Lightsail) drains the SQS queue and turns each payload into normalized
events.

---

## 2. Architecture / pipeline

```
   ┌──────────────────────┐                                 ┌─────────────────────────┐
   │  EC2 instance        │                                 │  BlackWatch             │
   │                      │                                 │  (Docker / Lightsail)   │
   │  ec2_agent.py        │   sqs:SendMessage               │                         │
   │  ──────────────┐     │   (instance role)               │  aws_sqs.drain()        │
   │   collectors   │     │ ─────────────────────────────►  │   │                     │
   │   journalctl   │     │   queue: blackwatch-ec2-agents  │   ▼                     │
   │   heartbeat    │     │                                 │  Ec2HostAdapter         │
   │   metrics      │     │                                 │   │                     │
   │  ──────────────┘     │                                 │   ▼                     │
   │   ▲ watchdog ping    │                                 │  pipeline.ingest_payload│
   │  systemd notify      │                                 │   │                     │
   │                      │                                 │   ▼                     │
   └──────────────────────┘                                 │  events table +         │
                                                            │  hosts projection       │
                                                            │  /hosts page            │
                                                            └─────────────────────────┘
```

Agents PUSH outbound to SQS (no inbound port open on the EC2). This is
critical for internal-only boxes — they need full egress to reach SQS,
but no inbound from the public internet ever.

---

## 3. Files & paths

### On the EC2 box (set up by `install-agent.sh`)

| Path | Mode | Purpose |
|---|---|---|
| `/opt/blackwatch/ec2_agent.py` | `0755 root:root` | The agent script itself. Not a secret. |
| `/etc/systemd/system/blackwatch-agent.service` | `0644 root:root` | systemd unit. Owns all env vars + sandboxing. |
| `/var/lib/blackwatch-agent/` | `0700 root:root` | Spool parent. Locked at install time. |
| `/var/lib/blackwatch-agent/spool/` | `0700 root:root` | Created on first send failure. Files are `0600`. |
| `/var/lib/blackwatch-agent/spool/<unix-ms>.json` | `0600 root:root` | One spooled report. JSON, gzipped if grown. |
| systemd journal (`journalctl -u blackwatch-agent`) | n/a | All agent stdout/stderr lands here. |

### In the BlackWatch repo

| Path | Purpose |
|---|---|
| `scripts/ec2_agent.py` | Source-of-truth for the agent. Pushed to each EC2's `/opt/blackwatch/`. |
| `deploy/ec2/install-agent.sh` | Idempotent installer. Sets up systemd unit + perms. |
| `deploy/ec2/setup.ps1` | One-time AWS bootstrap (creates SQS queue, IAM policies). |
| `deploy/ec2/blackwatch-ec2-agent-send-policy.json` | Minimal IAM policy: `sqs:SendMessage` to the one queue. |
| `deploy/ec2/README.md` | Quick-start (5 min). |
| `blackwatch/modules/ec2_host.py` | Adapter that converts the JSON payload into BlackWatch Events. |
| `blackwatch/hosts/projection.py` | Stateful read-model (last-seen, staleness, diffs). |
| `blackwatch/hosts/diff.py` | Snapshot diffing — what changed since last snapshot. |
| `blackwatch/connectors/aws_sqs.py` | Generic SQS poller. `target_module=ec2.host` routes to the adapter. |
| `docs/ec2-agent.md` | **This file.** |

---

## 4. Configuration (environment variables)

All set in the systemd unit's `Environment=` lines (read at startup; restart
the unit to apply changes).

### Required

| Variable | Example | Purpose |
|---|---|---|
| `BLACKWATCH_SQS_URL` | `https://sqs.us-west-1.amazonaws.com/095899260107/blackwatch-ec2-agents` | The queue. Validated by regex at startup — refuses bad shapes. |

### Common overrides

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | from IMDS | SQS queue region. Almost always same as the instance. |
| `INTERVAL` | `60` | Tick interval in seconds. Also drives the `auth_events` lookback (`INTERVAL + 120`). |
| `BLACKWATCH_TAGS` | `""` | `k=v,k=v` pairs stamped onto every event's extras. E.g. `env=prod,role=api`. Used for routing rules. |
| `SPOOL_DIR` | `/var/lib/blackwatch-agent` | Parent of `spool/`. |
| `SPOOL_MAX_FILES` | `5000` | Hard cap. Oldest files deleted when exceeded. |
| `SPOOL_MAX_BYTES` | `100*1024*1024` (100 MB) | Hard byte cap. Oldest files deleted when exceeded. |

### Per-collector cadence (only override if you know why)

| Variable | Default (sec) | Collector |
|---|---|---|
| `COLLECT_PORTS_SEC` | 60 | listening sockets |
| `COLLECT_PROCESSES_SEC` | 60 | process table (visibility-only, non-diffable) |
| `COLLECT_DISK_SEC` | 60 | per-mount fill |
| `COLLECT_USERS_SEC` | 120 | `getent passwd` |
| `COLLECT_AUTHORIZED_KEYS_SEC` | 120 | `~/.ssh/authorized_keys` per user |
| `COLLECT_SUDOERS_SEC` | 120 | `/etc/sudoers` + `/etc/sudoers.d/*` hashes |
| `COLLECT_CRITICAL_FILES_SEC` | 120 | FIM on `/etc/passwd`, `/etc/shadow`, `sshd_config`, etc. |
| `COLLECT_CRON_SEC` | 120 | `/etc/cron.*`, `/var/spool/cron` |
| `COLLECT_PACKAGES_SEC` | 600 | `rpm -qa` or `dpkg-query` |
| `COLLECT_SYSTEMD_UNITS_SEC` | 600 | enabled service+timer units |
| `COLLECT_SUID_SEC` | 600 | `find / -perm -4000` (scoped) |
| `COLLECT_KERNEL_MODULES_SEC` | 600 | `lsmod` |

---

## 5. What gets collected

### Collectors (cadence-driven, diff against last snapshot)

| Collector | Cadence | Diffable | What it captures |
|---|---|---|---|
| `ports` | 60s | ✓ | `ss -tlnp` — proto, addr, port, binding process |
| `processes` | 60s | ✗ | `ps -eo user,pid,comm,args` — args truncated to 240 chars, **scrubbed** |
| `disk` | 60s | ✓ | `df -PT` — per-mount fill, skips tmpfs/devtmpfs/overlay |
| `users` | 120s | ✓ | `getent passwd` — name, uid, shell |
| `authorized_keys` | 120s | ✓ | Per-user keys → `{user, fingerprint, type}`. **No pubkey body, no comment.** |
| `sudoers` | 120s | ✓ | SHA256 of `/etc/sudoers` + each `/etc/sudoers.d/*` |
| `critical_files` | 120s | ✓ | SHA256 of `/etc/passwd`, `/etc/shadow`, `sshd_config`, `hosts`, `resolv.conf`, `pam.d/{sshd,sudo,openvpn}`, `crontab` |
| `cron` | 120s | ✓ | SHA256 of `/etc/crontab`, `/etc/cron.{d,hourly,daily,weekly,monthly}/*`, `/var/spool/cron/*` |
| `packages` | 600s | ✓ | Sorted set of installed package names (RPM or DPKG, auto-detected) |
| `systemd_units` | 600s | ✓ | Sorted set of enabled `.service` + `.timer` units |
| `suid` | 600s | ✓ | `find /usr /opt /bin /sbin -xdev -perm -4000 -type f` |
| `kernel_modules` | 600s | ✓ | Sorted set of loaded modules from `lsmod` |

**Snapshots only ship when something changed** (hash of all diffable
collectors). Forced full resync every 1 hour even if unchanged.

### Always-on heartbeat fields (every tick)

| Field | Source | Purpose |
|---|---|---|
| `memory` | `/proc/meminfo` | total/available/used kB + used % |
| `cpu` | `/proc/loadavg` + `/proc/cpuinfo` | 1/5/15-min load, CPU count, load normalized by CPU count |
| `active_sessions` | `who --ips` (fallback `who`) | currently logged-in interactive sessions, with source IP for SSH |
| `oom_events` | `journalctl -k` | OOM-killer entries from kernel ring buffer |
| `rpm_db_corrupted` | `/var/lib/rpm/__db.*` + `pgrep` | Stale lock files w/o live rpm process → DB stuck |
| `stalled_collectors` | derived | Collectors that succeeded once but not within `3 * interval` |
| `collector_errors` | derived | Last error per failing collector |
| `tick_duration_ms` | timer | How long this tick took. Watchdog signal. |

### Journal events (sshd + sudo)

Read every tick with overlap window `INTERVAL + 120s`. Deterministic
event IDs via journal `__CURSOR` → dedup at insert.

**`MESSAGE` field is scrubbed before shipping** (see [scrubber](#84-secret-scrubbing-patterns)).
`__CURSOR` and `__REALTIME_TIMESTAMP` are preserved so dedup still works.

---

## 6. Events emitted (BlackWatch-side)

The `Ec2HostAdapter` converts each payload into one or more normalized
events. Action names you'll see in `/events`:

| Action | Trigger | Notes |
|---|---|---|
| `host.service.health` | every heartbeat | Drives `host_status` read model. Always emitted. |
| `host.state.snapshot` | when snapshots shipped | Diff is computed in projection. Capped at 512 KB body. |
| `host.state.snapshot.rejected` | snapshot > 512 KB | Synthetic event so operator sees something went wrong instead of silently dropping. |
| `host.auth.ssh.success` | `Accepted publickey for ec2-user from …` | One per match. `actor.principal=user`, `actor.source_ip=ip`. |
| `host.auth.ssh.failure` | `Failed publickey for …` OR `Invalid user …` | Includes `extra.reason=invalid_user` for the latter. |
| `host.sudo.exec` | `sudo: user : COMMAND=...` | `extra.command` populated (scrubbed). |
| `host.sudo.failure` | `authentication failure`, `NOT in the sudoers`, etc. | |
| `host.oom_kill` | matched kernel OOM message | Includes truncated kernel message. Severity `failure`. |

Diff-derived events (emitted by `hosts/projection.py`, not the adapter):

| Action | Trigger |
|---|---|
| `host.authorized_key.added` / `removed` | diff between snapshots |
| `host.user.added` / `removed` | diff in `users` collector |
| `host.sudoers.changed` | sudoers hash change |
| `host.port.opened` / `closed` | diff in `ports` collector |
| `host.suid.added` / `removed` | diff in SUID set |
| `host.cron.added` / `removed` / `changed` | diff in cron files |
| `host.file.changed` | critical_files hash change |
| `host.service.added` / `removed` | diff in systemd units |
| `host.packages.changed` | diff in package set |
| `host.agent.stale` | no heartbeat in 3× interval |
| `host.agent.recovered` | heartbeat returns after staleness |
| `host.collector.stalled` | individual collector hasn't succeeded in 3× its interval |

---

## 7. IAM (the only AWS permission the agent needs)

`deploy/ec2/blackwatch-ec2-agent-send-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BlackWatchAgentSendToQueue",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:blackwatch-ec2-agents"
    }
  ]
}
```

That's it. The agent can:
- Send messages to ONE specific queue.

It cannot:
- Read from the queue
- Delete messages
- List queues
- Touch S3, IAM, EC2, anything else

Attach this policy to each EC2's instance role. If the role is missing or
unattached, every `SendMessage` returns `AccessDenied` — the agent
spools, backs off, and reports loudly in the journal. The install
script's preflight (`aws sts get-caller-identity` + `sqs
get-queue-attributes`) catches this at install time.

---

## 8. Security model (the hardening)

### 8.1 Privilege model

The agent runs as **root**. Non-negotiable — it must:

- Read `/etc/shadow` (FIM)
- Read journald (any UID is fine if in `systemd-journal` group, but
  shadow forces root)
- Run `find` across `/usr /opt /bin /sbin` for SUID detection
- Read `/root/.ssh/authorized_keys`

Since we can't drop privileges, we sandbox aggressively instead.

### 8.2 systemd sandboxing

| Directive | Effect | Min systemd |
|---|---|---|
| `NoNewPrivileges=true` | Can't gain new privs via SUID/setcap binaries | 209 ✓ AL2 |
| `ProtectSystem=full` | `/usr`, `/boot`, `/efi` read-only | 208 ✓ AL2 |
| `ProtectHome=read-only` | `/home` read-only (need read for `~/.ssh/authorized_keys`) | 217 ✓ AL2 |
| `PrivateTmp=true` | Private `/tmp` namespace | 199 ✓ AL2 |
| `PrivateDevices=true` | No raw device access | 209 ✓ AL2 |
| `SystemCallArchitectures=native` | Only this host's syscall ABI | 209 ✓ AL2 |
| `SystemCallFilter=@system-service` | seccomp allowlist; blocks `bpf()`, raw sockets, obscure attack surface | 187 ✓ AL2 |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK` | No raw sockets, no obscure socket families | 211 ✓ AL2 |
| `WatchdogSec=180` | systemd kills + restarts if no `WATCHDOG=1` ping in 3 min | 209 ✓ AL2 |
| **Below: silently ignored on AL2; auto-enable on AL2023 / Ubuntu 22.04** | | |
| `ProtectKernelTunables=true` | `/proc/sys/*` and `/sys/*` read-only | 232 |
| `ReadWritePaths=/var/lib/blackwatch-agent /var/log` | With `ProtectSystem=strict`, only these are writable | 231 |
| `ProtectKernelModules=true` | Block module load/unload | 232 |
| `ProtectControlGroups=true` | `/sys/fs/cgroup` read-only | 232 |
| `ProtectClock=true` | Can't change wall clock | 245 |
| `RestrictNamespaces=true` | Block namespace creation | 233 |
| `RestrictRealtime=true` | No realtime scheduling | 231 |
| `RestrictSUIDSGID=true` | Can't create SUID/SGID files | 242 |
| `LockPersonality=true` | Personality syscall locked | 235 |
| `LogRateLimitIntervalSec=10` / `LogRateLimitBurst=200` | A bug in the agent can't flood journald | 240 |

### 8.3 Resource limits

| Directive | Limit |
|---|---|
| `MemoryLimit=200M` | OOM-killed if exceeded |
| `CPUQuota=20%` | Throttled if exceeded |
| `TasksMax=64` | Process count cap |
| `LimitNOFILE=1024` | Open file descriptor cap |
| `Nice=10` | De-prioritized vs. workloads |

### 8.4 Secret scrubbing patterns

Applied to: process `args`, sudo `COMMAND=...` lines, sshd journal
`MESSAGE` fields. Implemented in `scripts/ec2_agent.py::scrub()`.

| Pattern | Example match | Replaced with |
|---|---|---|
| `mysql -p` flag | `mysql -ppassword` | `mysql -p***` |
| `--password=` / `--passwd=` / `--pass=` | `--password=secret` | `--password=***` |
| `MYSQL_PWD=` / `PGPASSWORD=` | `PGPASSWORD=hunter2` | `PGPASSWORD=***` |
| `--token=` / `--secret=` / `--api-key=` / `--apikey=` / `--key=` | `--token=ABC123` | `--token=***` |
| Uppercase env-assigned secrets | `AWS_SECRET_KEY=xyz` | `AWS_SECRET_KEY=***` |
| AWS access key ID | `AKIAIOSFODNN7EXAMPLE` | `AKIA****REDACTED****` |
| `aws_secret_access_key=` | `aws_secret_access_key=xyz...` | `aws_secret_access_key=***` |
| `Authorization: Bearer …` / `Basic …` | `Authorization: Bearer eyJabc.def` | `Authorization: Bearer ***` |

False-positive risk: the broad uppercase pattern catches `LDAP_PASSWORD`,
`MY_API_KEY`, etc. — desired. Doesn't match lowercase generic words.
False-negative known: shell-quoted secrets like `mysql -p "hunter2"`
won't match the `-p` pattern; quoting is rare in real ps output.

### 8.5 Spool permissions

| Path | Mode |
|---|---|
| `/var/lib/blackwatch-agent/` | `0700 root:root` (at install + at spool time) |
| `/var/lib/blackwatch-agent/spool/` | `0700 root:root` |
| `/var/lib/blackwatch-agent/spool/*.json` | `0600 root:root` (created with explicit `os.open(..., 0o600)`, umask-independent) |

Contains: scrubbed journal lines, scrubbed process args, snapshots. Even
post-scrubbing, treat as sensitive — never `chmod` to anything else.

### 8.6 SQS URL allowlist

At startup, `BLACKWATCH_SQS_URL` is regex-checked against:

```
^https://sqs\.[a-z0-9-]+\.amazonaws\.com/\d{12}/[A-Za-z0-9_\-]{1,80}$
```

If it doesn't match, the agent refuses to start. This catches tampered
systemd units that might point at an attacker-controlled queue. The IAM
policy (queue ARN-scoped `SendMessage`) is the real defense; this is a
fail-fast signal so the operator sees the misconfig in seconds, not via
silently-spooled rejected sends.

### 8.7 Payload size cap

SQS message body limit is 256 KiB. The agent reserves 240 KiB headroom
(`SQS_BODY_MAX_BYTES`). Pre-flight check on every send; if oversized,
fields are dropped in priority order until under cap:

1. `snapshots.suid` (huge on package-heavy boxes)
2. `snapshots.systemd_units`
3. `snapshots.packages`
4. `snapshots.kernel_modules`
5. `snapshots.cron`
6. `snapshots.processes`
7. Entire `snapshots` block
8. `auth_events` (last resort — followers replay next tick)

What was dropped is recorded in `payload.truncated: [field1, field2, ...]`
and surfaces in BlackWatch under `extra.adapter_truncated` and as the
`trunc=...` flag in the agent's per-tick journal line.

### 8.8 Send-failure backoff

| Consecutive failures | Extra sleep after spool |
|---|---|
| 1–3 | none (treat as transient) |
| 4–6 | 30 s |
| 7–9 | 60 s |
| 10–12 | 90 s |
| ≥ 13 | 300 s (capped) |

Resets to zero on first successful send. Without this, a permanently
broken URL or revoked IAM would burn the 5000-file spool cap in 2–3
hours.

### 8.9 Watchdog

`Type=notify` + `WatchdogSec=180`. The agent sends `READY=1` at startup
and `WATCHDOG=1` after every tick (`_sd_notify` writes to `$NOTIFY_SOCKET`).
If a collector hangs and a tick fails to complete in 3 min, systemd
SIGKILLs + restarts the agent — and the projection emits
`host.collector.stalled` so the cause shows up in `/iam` /
`/events` rather than as silent agent death.

---

## 9. Installation

### 9.1 Prerequisites

- Linux EC2 instance (Amazon Linux 2, 2023, Debian, Ubuntu — all
  supported). RPM- and DPKG-based families auto-detected.
- `python3 >= 3.7` (AL2's default 3.7 works; pin handles boto3 compat).
- `journald` running.
- Instance role attached, with the `blackwatch-ec2-agent-send` policy
  (Section 7).
- Outbound network access to SQS (`sqs.<region>.amazonaws.com` over
  HTTPS:443). Internal-only EC2s with full egress: works.
- One-time AWS bootstrap done (queue + IAM policy created — see
  `deploy/ec2/setup.ps1`).

### 9.2 Install steps

On your dev machine:

```powershell
$KEY = "<path to .pem>"
$BOX = "ec2-user@<instance-ip>"

scp -i $KEY scripts/ec2_agent.py            ${BOX}:/tmp/
scp -i $KEY deploy/ec2/install-agent.sh     ${BOX}:/tmp/
```

On the EC2 box:

```bash
sudo BLACKWATCH_SQS_URL="https://sqs.us-west-1.amazonaws.com/<ACCT>/blackwatch-ec2-agents" \
     AWS_REGION="us-west-1" \
     INTERVAL="60" \
     BLACKWATCH_TAGS="env=prod,role=api" \
     AGENT_SRC=/tmp/ec2_agent.py \
     bash /tmp/install-agent.sh
```

What the install script does (in order):

1. Validates `BLACKWATCH_SQS_URL` is set.
2. Installs `python3-pip` if missing (yum/dnf/apt-get).
3. `pip3 install 'boto3>=1.28,<1.35'` — pinned to a 3.7-compatible range.
4. `install -d -m 0755 /opt/blackwatch` and `install -d -m 0700 /var/lib/blackwatch-agent`.
5. Copies the agent (skipped if `AGENT_SRC` == installed path).
6. Preflight: `aws sts get-caller-identity` + `aws sqs get-queue-attributes`.
   Warnings only (non-fatal) — catches missing IAM role before you walk
   away.
7. Writes `/etc/systemd/system/blackwatch-agent.service` with the full
   sandboxing + watchdog config.
8. `systemctl daemon-reload` → `systemctl enable` → `systemctl restart`.
9. Prints the first ~8 lines of `systemctl status` for sanity.

### 9.3 Upgrade / reinstall

The script is idempotent. Re-run with a new `AGENT_SRC` and it replaces
the script + rewrites the unit + restarts. **Use `AGENT_SRC=/tmp/...`,
not the installed path** — `install(1)` refuses copy-onto-self
(handled gracefully now: the script detects same-path and skips the
copy, but the rest of the script still runs).

To upgrade ONLY the systemd unit (no code change):

```bash
sudo BLACKWATCH_SQS_URL="..." AWS_REGION="..." \
     AGENT_SRC=/opt/blackwatch/ec2_agent.py \
     bash /tmp/install-agent.sh
```

The "same file" detection skips the copy; the unit is rewritten and the
service restarted.

### 9.4 Uninstall

```bash
sudo systemctl stop blackwatch-agent
sudo systemctl disable blackwatch-agent
sudo rm -f /etc/systemd/system/blackwatch-agent.service
sudo systemctl daemon-reload
sudo rm -rf /opt/blackwatch /var/lib/blackwatch-agent
# Optional: detach the IAM policy from the instance role.
```

---

## 10. Operational commands

### Status + logs

```bash
# Current state
sudo systemctl status blackwatch-agent

# Live tail
sudo journalctl -u blackwatch-agent -f

# Recent activity
sudo journalctl -u blackwatch-agent --since "10 min ago" --no-pager

# Just the per-tick summary lines
sudo journalctl -u blackwatch-agent --since "1 hour ago" --no-pager | grep "^reported"
```

### Per-tick log line — field reference

```
reported instance=i-03499c8ce39a70d21 auth_lines=24 snaps=yes tick_ms=268 mem=56% load=0.065 sess=0 rpmdb=BAD
```

| Field | Meaning |
|---|---|
| `instance=...` | EC2 instance ID from IMDS |
| `auth_lines=N` | sshd + sudo lines shipped this tick |
| `snaps=yes` / `no` | Whether the snapshot block was included (only when changed or hourly resync) |
| `tick_ms=N` | How long collectors + send took |
| `mem=X%` | Used memory percentage |
| `load=X` | Normalized 1-min load (1.0 = saturated) |
| `sess=N` | Currently logged-in interactive sessions |
| Optional flags: | |
| `oom=N` | OOM kills detected this tick |
| `rpmdb=BAD` | RPM DB has stale locks |
| `stalled=ports,packages` | Collectors that haven't succeeded in 3× their interval |
| `errs=ports,packages` | Last-run errored (one-off) |
| `trunc=snapshots.suid,...` | Payload size cap kicked in; these fields were dropped |

### Force a tick + exit (debug)

```bash
sudo /usr/bin/python3 /opt/blackwatch/ec2_agent.py --once
```

Runs one tick to stdout (still sends to SQS). Useful when systemd-managed
output is hiding something.

### Restart, stop, start

```bash
sudo systemctl restart blackwatch-agent
sudo systemctl stop blackwatch-agent
sudo systemctl start blackwatch-agent
```

### Inspect spool

```bash
sudo ls -la /var/lib/blackwatch-agent/spool/
sudo cat /var/lib/blackwatch-agent/spool/<latest>.json | jq .
```

Spool is FIFO: oldest gets sent first on next flush. Cap enforcement
drops oldest first.

### Trigger spool flush manually (boto3 must be reachable)

```bash
# There's no admin command — the agent flushes on the next successful
# send() call. To force it now, restart:
sudo systemctl restart blackwatch-agent
```

---

## 11. Verifying hardening is active

```bash
# Sandboxing — note systemd 219 (AL2) silently omits properties it
# doesn't recognize from `show`; check the unit file directly if so.
sudo systemctl show blackwatch-agent \
  -p NoNewPrivileges -p ProtectSystem -p ProtectHome \
  -p PrivateTmp -p PrivateDevices \
  -p WatchdogSec -p RestrictAddressFamilies

# Expected on AL2:
#   NoNewPrivileges=yes
#   ProtectSystem=full
#   ProtectHome=read-only
#   PrivateTmp=yes
#   PrivateDevices=yes
#   WatchdogSec=3min   (may be missing from show; check unit file)
#   RestrictAddressFamilies=[unprintable]   (set, display quirk on 219)

# Read directly from the unit file to be sure (these are present in the
# unit file but systemd 219 ignores ProtectKernelTunables and friends —
# they activate automatically on AL2023+):
sudo grep -E "^(WatchdogSec|RestrictAddressFamilies|Type|NotifyAccess)=" \
  /etc/systemd/system/blackwatch-agent.service

# Spool permissions
sudo stat -c "%a %U %G" /var/lib/blackwatch-agent
# 700 root root

# Watchdog is alive — silence means working
sudo journalctl -u blackwatch-agent --since "10 min ago" | grep -i "watchdog timeout" \
  || echo "no watchdog timeouts (good)"
```

### Test scrubbing end-to-end

```bash
# Start a process that lingers long enough to be captured (>= 60s)
sudo bash -c 'sleep 120 --token=SHOULD_BE_REDACTED --password=SECRETPASS' &
```

Wait 90s, then on the BlackWatch host:

```powershell
docker compose exec db psql -U blackwatch -d blackwatch -c "
SELECT envelope->'extra'->'snapshots'->'processes'
FROM events
WHERE module = 'ec2.host' AND action = 'host.state.snapshot'
ORDER BY event_time DESC LIMIT 1;" | Select-String -Pattern 'SHOULD_BE_REDACTED|SECRETPASS|sleep 120'
```

You should see `sleep 120` in the output but NOT the literal secret
strings — they'll appear as `--token=***` and `--password=***`.

---

## 12. End-to-end pipeline

```
[on EC2]                          [AWS]                    [BlackWatch]
   ec2_agent.py                                              
   └─ snapshot collectors                                    
      heartbeat metrics                                      
      journalctl sshd/sudo                                   
   └─ scrub()                                                
   └─ _shrink_for_sqs() cap                                  
   └─ json.dumps                                             
   └─ boto3 SendMessage   ───►   SQS queue              ───► aws_sqs.drain()
                                  blackwatch-ec2-agents      └─ json.loads body
                                                              └─ pipeline.ingest_payload(
                                                                    module="ec2.host", ...)
                                                                 └─ Ec2HostAdapter.parse()
                                                                    │ type guards
                                                                    │ size cap (snapshots)
                                                                    │ build Events
                                                                 └─ engine.evaluate()  → severity
                                                                 └─ storage.insert_event()
                                                                 └─ notifier.dispatch() if new
                                                                 └─ hosts.projection.project()
                                                                    └─ diff vs last snapshot
                                                                    └─ emit derived events
                                                                       (port.opened, key.added,
                                                                        agent.stale, etc.)
```

### Dedup model

Two layers:

1. **Per-line journal cursor** in event_id (`uuid5(NAMESPACE_URL,
   f"host-auth:{instance_id}:{__CURSOR}")`). Re-reads of overlapping
   `read_auth_events` windows always produce the same event_id →
   `ON CONFLICT (event_id) DO NOTHING` at insert.
2. **Insert-time gated dispatch** (added in v1.2 of the pipeline):
   notifications fire ONLY when `insert_event()` returned `True` (a new
   row was created). Re-shipped lines don't double-notify.

---

## 13. Failure modes & recovery

### Common operational failures

| Symptom | Diagnosis | Recovery |
|---|---|---|
| `send failed, spooling: An error occurred (AccessDenied)` repeating | Instance role missing the `blackwatch-ec2-agent-send` policy, or queue ARN mismatch | Attach the policy; verify `aws sqs get-queue-attributes --queue-url $URL` succeeds from the box |
| `send failed: Could not connect to the endpoint URL` | Egress to SQS blocked (security group, NACL, VPC endpoint misconfig) | Allow outbound 443 to `sqs.<region>.amazonaws.com` |
| `ERROR: BLACKWATCH_SQS_URL doesn't look like a valid SQS URL` at startup | Typo in env var or tampered unit | Fix in `/etc/systemd/system/blackwatch-agent.service`, `daemon-reload`, restart |
| `watchdog timeout (limit 3min)` in journal | Agent tick hung >3 min — usually a collector subprocess blocking | systemd auto-restarts; check `collector_errors` and `stalled_collectors` on next ticks |
| `rpmdb=BAD` flag persists across ticks | Stale RPM lock files (`/var/lib/rpm/__db.*`) | `sudo rm -f /var/lib/rpm/__db.*; sudo rpm --rebuilddb` |
| `trunc=snapshots.suid,...` flag every tick | Box is bigger than the SQS body cap | Expected on large boxes; the truncation is recorded. To reduce: raise per-collector intervals, or accept the dropped fields. |
| `stalled=ports,packages` in flag set | A collector errored once and hasn't recovered | Check `collector_errors`, often a missing binary or perms issue. Restart agent if env changed. |
| Spool hits its cap (`Dropped oldest spool file`) | SQS unreachable for hours | Once SQS recovers, the oldest backlog is gone — accepted trade-off for not filling `/var` |
| No `reported` lines but unit is active | Most likely IAM-related; check journal for `AccessDenied` | Same as first row |

### Boot-time recovery

The unit has `Restart=always` + `RestartSec=10`. Any crash (OOM kill,
unhandled exception, watchdog timeout) results in a 10-second restart.
Spool survives — pending payloads are sent on the next successful tick.

### Total data loss scenarios

- Spool dir wiped (`rm -rf /var/lib/blackwatch-agent`) → that backlog
  is gone, agent recreates the dir on next spool.
- EC2 instance terminated → that box's history is gone. No agent
  state on BW survives the box, except whatever events have already
  been received and stored in BW's database.

---

## 14. Known limitations / accepted risk

### Accepted today

| Risk | Mitigation today | Future fix |
|---|---|---|
| Compromised box could spoof events under another `instance_id` | IAM policy on instance roles restricts to ONE queue (single-tenant queue per BW deployment); adapter validates `instance_id` regex but can't verify sender identity from SQS body | Per-instance HMAC signing using a key in SSM Parameter Store; BW-side key store verifies before adapter runs |
| Tampered agent binary at `/opt/blackwatch/ec2_agent.py` not detected | File installed `0755 root:root`; non-root can't modify | Code-signing + signature check at startup |
| boto3 fetched from PyPI at install time | Pin range `>=1.28,<1.35`; reasonably stable | Vendored wheel in `deploy/ec2/` |
| Local journal can be tampered with by root on the box | None — root on the box can do anything | Forwarder to remote journald (rsyslog) for tamper-evident log of last-known-good lines |
| sd_notify not supported on systemd <209 | Doesn't apply to any actively supported distro | n/a |
| Many sandboxing directives no-op on AL2 systemd 219 | Compatibility documented; activate automatically on AL2023+ | Move to AL2023 |

### Out of scope (different feature, not a fix)

- Outbound network connection monitoring (DNS, established TCP) — handled
  by VPC Flow Logs path (planned).
- Per-process syscall auditing — would need auditd integration.
- File integrity at content level (current FIM only hashes a fixed
  whitelist of paths).
- Container introspection (cgroup, namespaces) — agent runs at host
  level only.

---

## 15. Quick reference card

```
INSTALL:        sudo BLACKWATCH_SQS_URL=... AWS_REGION=... AGENT_SRC=/tmp/ec2_agent.py bash /tmp/install-agent.sh
LOGS LIVE:      sudo journalctl -u blackwatch-agent -f
LOGS RECENT:    sudo journalctl -u blackwatch-agent --since "10 min ago" --no-pager
STATUS:         sudo systemctl status blackwatch-agent
FORCE TICK:     sudo /usr/bin/python3 /opt/blackwatch/ec2_agent.py --once
RESTART:        sudo systemctl restart blackwatch-agent
SPOOL DIR:      /var/lib/blackwatch-agent/spool/
UNIT FILE:      /etc/systemd/system/blackwatch-agent.service
AGENT BINARY:   /opt/blackwatch/ec2_agent.py
IAM POLICY:     blackwatch-ec2-agent-send (sqs:SendMessage to blackwatch-ec2-agents)
SQS QUEUE:      blackwatch-ec2-agents (region: us-west-1)
TARGET MODULE:  ec2.host (BlackWatch SQS connector)
PIPELINE:       agent → SQS → aws_sqs.drain → Ec2HostAdapter → pipeline → events table + hosts projection
```

---

*Document version: v1.2 (matches agent version). Update on any agent or
install-script change.*
