# File Integrity Monitoring (FIM) — full reference

BlackWatch's FIM is an in-house replacement for Wazuh's File Integrity
Monitor. It runs as three independent threads inside the EC2 agent (no
separate daemon), shares one local SQLite baseline, and ships changes
through the existing SQS → BlackWatch pipeline.

Built in three parts, all shipped:

- **Part 1 (agent v1.3)** — periodic baseline scan
- **Part 2 (agent v1.4)** — real-time inotify watcher
- **Part 3 (agent v1.5)** — auditd whodata (actor attribution)

For the agent as a whole (install, sandbox, etc.), see
[`docs/ec2-agent.md`](ec2-agent.md). This file is the FIM-specific deep
dive: architecture, defaults, UI surfaces, troubleshooting.

---

## 1. Why we built our own

Wazuh's FIM works, but it ships in a heavy manager + indexer stack, charges
for whodata in the paid tier, and produces compliance reports that don't
fit BlackWatch's event-first model. We wanted:

- Sub-second detection on critical config files (`/etc/sudoers`, `sshd_config`,
  authorized_keys, PAM, cron, systemd units)
- Periodic full-coverage scan as the compliance backstop
- "Who did it" via the kernel audit framework, **without** a paid tier
- Same event store + same rule engine + same notifier as everything else
  in BlackWatch — no parallel pipeline
- Per-instance per-path file counts in the UI

What we got: parity with Wazuh on the free tier, parity with Wazuh Pro on
whodata, plus a cleaner UI integration.

---

## 2. Architecture — three threads, one baseline

```
              ┌────────────────────────────────────────────┐
              │  EC2 agent (ec2_agent.py + fim_engine.py)  │
              │                                            │
              │  ┌─────────────────────────────────────┐   │
              │  │ Periodic baseline scanner (6h)      │   │
              │  │  walks ~3000 files                  │   │
              │  │  hashes, diffs vs baseline.db       │   │
              │  └─────────────────┬───────────────────┘   │
              │                    │ queues change         │
              │                    ▼                       │
              │  ┌─────────────────────────────────────┐   │
              │  │ FimEngine pending changes queue     │   │
              │  └─────────────────────────────────────┘   │
              │                    ▲                       │
              │                    │ queues change         │
              │  ┌─────────────────┴───────────────────┐   │
              │  │ Inotify watcher (real-time)         │   │
              │  │  ~43 watches on critical paths      │   │
              │  │  200ms debounce per path            │   │
              │  └─────────────────┬───────────────────┘   │
              │                    │ asks for actor        │
              │                    ▼                       │
              │  ┌─────────────────────────────────────┐   │
              │  │ Audit reader (whodata)              │   │
              │  │  tails /var/log/audit/audit.log     │   │
              │  │  filters key="bw_fim"               │   │
              │  │  builds path → actor map (2s TTL)   │   │
              │  └─────────────────────────────────────┘   │
              │                                            │
              │  Main agent tick: drain + ship via SQS     │
              └────────────────────────────────────────────┘
                          │
                          ▼
              SQS (blackwatch-ec2-agents)
                          │
                          ▼
          ┌──────────────────────────────────────────┐
          │  BlackWatch (Lightsail)                  │
          │                                          │
          │   Ec2HostAdapter: payload → events       │
          │      host.fim.{created,modified,…}       │
          │      host.fim.coverage                   │
          │                                          │
          │   hosts/projection.py:                   │
          │      → fim_baselines  (current state)    │
          │      → fim_history    (append-only log)  │
          │      → fim_coverage   (per-host summary) │
          │                                          │
          │   /fim, /fim/[id], /events/[id]          │
          └──────────────────────────────────────────┘
```

All three threads share `/var/lib/blackwatch-agent/fim/baseline.db` (SQLite,
WAL journal mode). Every baseline read-then-write is wrapped in an
`RLock` so periodic and inotify don't race each other.

---

## 3. Default watched paths

Hardcoded in `scripts/fim_engine.py` constants. Override via env vars
(see [§5](#5-configuration)).

### `critical_files` — exact file watches

```
/etc/passwd           /etc/shadow          /etc/group
/etc/gshadow          /etc/sudoers         /etc/login.defs
/etc/ssh/sshd_config  /etc/hosts           /etc/hosts.allow
/etc/hosts.deny       /etc/resolv.conf     /etc/crontab
/etc/nsswitch.conf    /etc/pam.conf        /etc/profile
/etc/bashrc           /etc/environment
```

### `critical_dirs` — recursive watches (inotify watches the dir + 1 level of subdirs)

```
/etc/ssh/sshd_config.d  /etc/sudoers.d   /etc/pam.d
/etc/security           /etc/cron.d      /etc/cron.hourly
/etc/cron.daily         /etc/cron.weekly /etc/cron.monthly
/etc/systemd/system     /etc/profile.d   /root/.ssh
```

### `binary_dirs` — periodic-scan-only (too many files for inotify)

```
/bin   /sbin   /usr/bin   /usr/sbin   /usr/local/bin   /usr/local/sbin
```

### Hard exclusions (never traversed, even via inotify subdir auto-discovery)

```
/proc/  /sys/  /dev/  /run/  /var/run/
/var/log/  /var/cache/  /var/tmp/  /tmp/
/var/lib/blackwatch-agent  (don't track our own state)
```

### Safety caps

- **Per-file hash cap**: 50 MB. Files over that are skipped (with a log
  line) — prevents the scanner from getting stuck on a stray multi-GB
  log file in `/etc`.
- **Per-scan change queue cap**: 1000 changes. On exhaustion we emit a
  single `<<truncated>>` marker so the operator sees the scan exceeded
  the cap rather than silently losing events.
- **Per-payload SQS shrink**: if FIM changes push the SQS body over
  240 KB, the agent halves the list iteratively (still cached locally —
  the dropped ones won't re-fire next scan because the baseline already
  has the after-state).

---

## 4. Detection paths in detail

### 4.1 Periodic baseline scanner

- Cadence: `COLLECT_FIM_SEC` (6h default).
- First scan: 15s after agent startup (lets agent finish init).
- Walks every configured path. Recursive for `critical_dirs` + `binary_dirs`,
  exact for `critical_files`.
- For each file: `os.stat` + `sha256` of contents (streaming, 64 KB chunks).
- Compares against `baseline.db` row (sha256 + size + perm + owner_uid +
  owner_gid).
- Diff result drives the change type:
  - hash differs → `modified`
  - perm only differs → `perm_changed`
  - owner only differs → `owner_changed`
- After all walked paths: query baseline for rows whose path is in our
  configured scope but wasn't walked this scan → `deleted` events. Skip
  paths the inotify watcher would have caught (avoids double-emit).
- At end: refresh coverage stats + per-path file counts and bytes,
  expose via `FimEngine.coverage()` for the next heartbeat.

Catches: drift the inotify watcher missed (e.g. binary modifications,
inotify watch limit was hit, agent restart gap).

### 4.2 Inotify watcher

Pure-Python via [`inotify_simple`](https://pypi.org/project/inotify-simple/)
(installed by `install-agent.sh`).

- Subscribes to `critical_files` + `critical_dirs` + one level of subdirs
  of each `critical_dir`. **Does NOT subscribe to `binary_dirs`** — that
  would be thousands of watches, the kernel limit, and unnecessary because
  binaries rarely change.
- Typical install: ~43 watches.
- Kernel watch budget bumped via `/etc/sysctl.d/99-blackwatch-agent.conf`
  (default cap is sometimes 128 on old systems; we set 16384).
- Subscribed inotify flags: `MODIFY | CREATE | DELETE | ATTRIB |
  MOVED_TO | MOVED_FROM | DELETE_SELF | MOVE_SELF`.

### 4.2.1 200ms debounce

Editor saves typically fire 3-5 inotify events within <50ms (write swap
file → rename → fsync). Without debouncing, we'd emit 5 separate
`host.fim.modified` events for one logical save.

Implementation: a map of `path → last_event_time`. Each loop iteration we
read events (100ms timeout), update the map, and then process any path
that's been quiet for ≥200ms. The 200ms window catches the entire save
sequence as one logical change.

### 4.2.2 Per-event handler

On debounce expiry, the watcher calls back into `FimEngine`:

1. `os.stat` + sha256 the file (or detect `FileNotFoundError` → deleted).
2. Under `_baseline_lock`: read prior baseline row, compute diff, update
   baseline.
3. Look up audit reader (if active) for a fresh writer record on this path
   within 2s.
4. Queue `FimChange` with `detection="inotify"` and (optionally) `actor`.

### 4.3 Audit reader (whodata)

Tails `/var/log/audit/audit.log`. The install script registers rules in
`/etc/audit/rules.d/bw_fim.rules`, all tagged with `-k bw_fim`:

```
-w /etc/passwd  -p wa -k bw_fim
-w /etc/shadow  -p wa -k bw_fim
…
```

`-p wa` watches for **w**rite + **a**ttribute changes (perm/owner) on each
path. The agent reader filters lines by the literal `bw_fim` key.

#### 4.3.1 Parsing — one logical event spans 4 lines

```
type=SYSCALL   msg=audit(<ts>:<id>): uid=1000 pid=22 comm="vim" exe="..."  key="bw_fim"
type=CWD       msg=audit(<ts>:<id>): cwd="/root"
type=PATH      msg=audit(<ts>:<id>): item=0 name="/etc/sudoers" ...
type=PROCTITLE msg=audit(<ts>:<id>): proctitle="vim /etc/sudoers"
```

The reader buffers partial events keyed by `audit_id`. On `PROCTITLE`
(typically the last record) the partial is committed: each path in the
buffer gets `recent_writers[path] = (now, actor)`. Partials that never see
a `PROCTITLE` are swept after 5s.

#### 4.3.2 Path → actor lookup

When `FimEngine._handle_realtime_change` (or `_scan_one_path`) emits a
change, it calls `AuditReaderThread.lookup(path)`:

- Returns the `actor` dict if the most recent write happened within
  `_AUDIT_WINDOW_SEC = 2.0`.
- Returns `None` otherwise — typical for periodic scans (changes happened
  hours before).

Lookup is **non-blocking** under a small lock. Map size capped at 4096
LRU entries.

#### 4.3.3 Graceful degradation

- `auditd` not installed → reader logs once, exits cleanly.
- `audit.log` not readable → reader logs once, exits cleanly.
- Audit rules failed to load → install script prints a warning; agent
  starts anyway, just without whodata.

In all cases, FIM events still flow — they just don't have an `actor`.

---

## 5. Configuration

All env vars are set in the systemd unit. Restart to apply.

| Variable | Default | Purpose |
|---|---|---|
| `COLLECT_FIM_SEC` | `21600` (6h) | Periodic scan interval. |
| `BLACKWATCH_FIM_DISABLED` | `""` (off) | `1`/`true`/`yes` disables all FIM threads. |
| `BLACKWATCH_FIM_EXTRA_FILES` | `""` | Comma-separated extra file paths to watch. |
| `BLACKWATCH_FIM_EXTRA_DIRS` | `""` | Comma-separated extra directories. |

### Adding custom paths

```bash
sudo systemctl edit blackwatch-agent
# add to [Service]:
Environment=BLACKWATCH_FIM_EXTRA_FILES=/etc/redis/redis.conf,/etc/postgresql/postgresql.conf
Environment=BLACKWATCH_FIM_EXTRA_DIRS=/etc/nginx,/etc/letsencrypt
# save, then:
sudo systemctl restart blackwatch-agent
```

Within ~15-20 seconds (first scan after restart) the new paths appear in
the UI's **Monitored paths** table with their file counts. The startup
log line also confirms: `fim=enabled scan_every=21600s
paths_configured=37 extras=+2f/+2d`.

> **Phase B (planned)**: live add/remove from the UI without SSH. Will
> use AWS SSM Parameter Store — BlackWatch writes the desired path list
> to `/blackwatch/fim/<instance_id>`, agent polls it on heartbeats. No
> new firewall rules or network paths needed.

---

## 6. Event shape

Every FIM change becomes one event of action
`host.fim.{created|modified|deleted|perm_changed|owner_changed}`. The
event envelope:

```json
{
  "source": { "module": "ec2.host", "account": "…", "region": "…" },
  "category": "host",
  "action": "host.fim.modified",
  "outcome": "success",
  "target": { "id": "i-08ba…", "type": "ec2.instance", "name": "ip-…" },
  "actor": { "principal": "tee uid=0" },  // only when audit attached
  "extra": {
    "path": "/etc/sudoers.d/bw-test",
    "change_type": "modified",
    "sha256_before": "7dd5…",
    "sha256_after":  "9986…",
    "size_before": 39, "size_after": 44,
    "perm_before": 420, "perm_after": 420,
    "owner_before": "0:0", "owner_after": "0:0",
    "detection": "inotify",     // or "baseline" / "auditd"
    "actor": {                  // only on detection=inotify when audit hit
      "uid": 0, "gid": 0, "euid": 0, "egid": 0,
      "pid": 8377, "ppid": 8375, "tty": "pts0",
      "comm": "tee", "exe": "/usr/bin/tee",
      "proctitle": "tee -a /etc/sudoers.d/bw-test"
    },
    "tags": { "env": "prod", "role": "Dev-NAT" }
  }
}
```

The `host.fim.coverage` event has a different shape — projection-only,
never stored — carrying counts + last-scan stats + the per-path file
counts (consumed by the `/fim` UI).

---

## 7. Backend persistence

Three Postgres tables (created by migrations `014` — `017`):

### `fim_baselines` — current known-good per (instance, path)

```sql
instance_id TEXT, path TEXT, sha256 TEXT, size BIGINT, perm SMALLINT,
owner_uid INT, owner_gid INT, mtime TIMESTAMPTZ, last_seen_at TIMESTAMPTZ,
established_at TIMESTAMPTZ
PRIMARY KEY (instance_id, path)
```

Updated on every FIM change event. **Only contains paths that have ever
drifted** — not the full per-host file inventory (that lives in the
agent's local SQLite, surfaced via `fim_coverage.path_stats`).

### `fim_history` — append-only change log

```sql
id BIGSERIAL, instance_id, path, changed_at, change_type,
sha256_before/after, size_before/after, perm_before/after,
owner_before/after, event_id,
detection,            -- "baseline" | "inotify" | "auditd"
actor_uid, actor_gid, actor_pid, actor_comm, actor_exe, actor_proctitle
```

One row per detected change. Drives the "recent changes" tables in the UI.

### `fim_coverage` — per-host summary (one row per instance)

```sql
instance_id PRIMARY KEY,
paths_configured, files_tracked,
last_full_scan_at, last_scan_duration_ms, scan_errors,
paths_inotify, paths_baseline_only,
inotify_active, inotify_watch_count,
auditd_active,
configured_paths JSONB,    -- {critical_files: [...], …}
path_stats       JSONB,    -- {<path>: {file_count, total_size_bytes, category}}
updated_at
```

Updated on every heartbeat via `host.fim.coverage` (projection-only event).
Drives the coverage card + monitored-paths table in `/fim/<id>`.

---

## 8. UI surfaces

### `/fim` (top level)

- Header table — every host with FIM data
  - Env / Role / Instance / Hostname / Files / Paths / Real-time pill /
    Whodata pill / Last scan
- Recent FIM activity across **all** hosts
  - Time / Detected pill / Change pill / Host / Path (clickable to event
    detail) / Who

### `/fim/<instance_id>`

- Coverage card (same 5 stats as the host page section)
- **Monitored paths** table — every configured path with file count + total
  bytes. Counts come from agent's local SQLite, shipped each heartbeat
- **Stray baselines** (only if any) — files in `fim_baselines` whose path
  isn't under any current configured path (= operator changed config but
  agent hasn't been restarted)
- Recent file integrity events for this host (full Who column)
- **Configuration** section — copy-paste systemd drop-in for env vars

### Existing `/events/<event_id>`

Renders the full envelope + raw payload generically. Works for FIM events
with no FIM-specific code — you get the whole `extra` dict including
`actor`, `sha256_*`, `detection`, etc.

### Drag-resizable columns

All FIM tables use the `ResizableTable` wrapper — drag any column edge to
resize, widths persist to `localStorage` per `tableId`. Same pattern is
applied to `/hosts` and `/events` tables.

---

## 9. Detection rules

Defined in `rules/host.yaml`. Severity defaults:

| Rule | When | Severity |
|---|---|---|
| `host-fim-sudoers-changed` | any change under `/etc/sudoers` or `/etc/sudoers.d/` | **critical** |
| `host-fim-sshd-config-changed` | `sshd_config` or drop-ins modified | high |
| `host-fim-authorized-keys-changed` | any `authorized_keys` modified | high |
| `host-fim-pam-changed` | `/etc/pam.d/*` modified | high |
| `host-fim-cron-changed` | `/etc/cron*` modified | high |
| `host-fim-systemd-unit-changed` | `/etc/systemd/system/*` modified | medium |
| `host-fim-system-binary-changed` | binary under `/bin`, `/sbin`, `/usr/bin`, etc. modified | high |
| `host-fim-generic-modified` | catch-all `host.fim.modified` | medium |
| `host-fim-created` | `host.fim.created` | low |
| `host-fim-deleted` | `host.fim.deleted` | low |
| `host-fim-perm-changed` | `host.fim.perm_changed` | medium |
| `host-fim-owner-changed` | `host.fim.owner_changed` | medium |
| **Part 3 whodata-aware rules** | | |
| `host-fim-non-root-edit-critical` | non-root uid edits sudoers/shadow/etc. | **critical** |
| `host-fim-editor-touched-binary` | system binary modified AND `actor.comm` ∈ {vim, vi, nano, emacs, ed} | **critical** |

Notification rules can match the new actions directly — e.g.
`action contains host.fim.password` for password-style changes, or filter
on `extra.actor.uid != 0` for non-root activity (whodata rules).

---

## 10. Auditd setup (installed automatically)

The install script (`deploy/ec2/install-agent.sh`) does this on first run:

1. Installs the `audit` / `auditd` package if missing
2. Writes `/etc/audit/rules.d/bw_fim.rules` with `-w … -p wa -k bw_fim`
   entries for every critical path
3. Enables + starts auditd
4. Loads the new rules via `augenrules --load` (no auditd restart needed)
5. Verifies via `auditctl -l | grep bw_fim` and prints a status line

Verify any time:

```bash
sudo auditctl -l | grep bw_fim     # should list all watch rules
sudo systemctl is-active auditd    # should print "active"
sudo tail /var/log/audit/audit.log | grep bw_fim   # see live audit hits
```

---

## 11. Resource budget

| Resource | Cost | Enforced by |
|---|---|---|
| Agent RAM | +25-30 MB steady (3 FIM threads + SQLite WAL cache) | systemd `MemoryLimit=200M` total |
| Scan CPU spike | 5-30s burst every 6h, low-priority (Nice=10) | natural — scan is bounded by ~3000 files |
| Steady CPU | inotify + auditd readers are ~0% when idle | n/a |
| Baseline DB size | <1 MB for typical ~3000 files | SQLite WAL with vacuum on rotation |
| inotify watches | ~43 typical, capped at kernel limit | `fs.inotify.max_user_watches=16384` |
| Audit log read | tail-only, no rewrites | n/a |
| SQS bytes per heartbeat | +~150 bytes coverage + ~250 bytes per change event | shrink-priority kicks in at 240 KB |

---

## 12. Troubleshooting

### Symptom: agent journal shows `OperationalError('near "ON"')`

Old fim_engine.py using `ON CONFLICT DO UPDATE` (SQLite 3.24+). Updated
agent uses `INSERT OR REPLACE` which works on every SQLite version
including AL2's bundled one. Push the latest `fim_engine.py` and restart.

### Symptom: `[fim] inotify_simple not installed; real-time FIM disabled`

The Python package is missing. The install script `pip3 install`s it, but
if the install failed (rare — network blip), re-run:

```bash
sudo pip3 install 'inotify_simple>=1.3,<2.0'
sudo systemctl restart blackwatch-agent
```

### Symptom: `[fim] audit log not found at /var/log/audit/audit.log`

auditd isn't installed. Without it, FIM still works — you just lose actor
attribution. To install:

```bash
sudo yum install -y audit                  # AL2 / AL2023
sudo systemctl enable --now auditd
sudo augenrules --load
sudo systemctl restart blackwatch-agent
```

### Symptom: FIM coverage card shows everything 0

The agent hasn't completed its first scan yet. Wait 30 seconds — the
first scan runs 15s after agent start, plus ~5-15s for scan completion,
plus ~5s for the coverage event to flow through SQS.

### Symptom: monitored paths show 0 files even after a scan

Coverage isn't propagating `path_stats`. Verify on the Lightsail DB:

```bash
docker compose exec db psql -U blackwatch -d blackwatch -c "
SELECT path_stats IS NOT NULL FROM fim_coverage WHERE instance_id = 'i-XXX';
"
```

If `false` — the agent shipped a coverage event before `path_stats` was
populated (pre-v1.5-fix agent). Restart the agent on the EC2 to force a
fresh scan + coverage event.

### Symptom: sudo broken after FIM test

You wrote a non-comment line to `/etc/sudoers.d/<file>`. sudoers fail-safe
rejects sudo entirely. Recover via SSM (which runs as root, bypassing
sudo):

```powershell
aws ssm send-command --instance-ids i-XXX --document-name "AWS-RunShellScript" `
  --parameters 'commands=["rm -f /etc/sudoers.d/<file>","visudo -c"]' `
  --region us-west-1
```

**Never test FIM by writing to `/etc/sudoers.d/`.** Use `/etc/cron.d/`,
`/etc/security/`, or any other watched path instead — they're tolerant
of garbage content.

### Symptom: "Unknown lvalue 'LockPersonality'" in journal at install time

Expected on AL2 (systemd 219). These directives need systemd 231+ and are
silently ignored on AL2. They auto-activate on AL2023+.

---

## 13. Known limitations / future work

### Accepted today

- **First-scan create flood**: on a fresh agent install, the first scan
  emits a `host.fim.created` event for every monitored file (~3000
  events). The agent caps to 1000 + truncation marker; BlackWatch shrinks
  further at the SQS body limit. Reasonable as "this is what we now
  monitor"; could be silenced in a follow-up (mark first-scan as baseline-
  establishment, no events).
- **No rollback detection**: if a file is reverted to a previously-seen
  hash, we don't flag it specifically. Just shows as another modify.
  Wazuh doesn't do this either.
- **Audit attribution is only useful for inotify-detected changes**. The
  periodic scanner runs hours after a change; the 2s audit window will
  almost always be expired. Acceptable — inotify catches 99% of attacker
  edits anyway.

### Phase B — live customization from UI

Currently you customize paths via env vars on the host (requires SSH +
restart). Phase B will use AWS SSM Parameter Store:

- BlackWatch writes desired config to `/blackwatch/fim/<instance_id>`
- Agent polls on every heartbeat (already has IAM for SSM-from-its-own-role)
- No new network paths, no firewall rules, no agent-side daemon changes

Estimated effort: ~150 lines (agent reader + backend writer + UI form).

### Phase C — possible Wazuh-style extras

- Pre-built compliance report exports (PDF/CSV) — only if an auditor asks
- Per-tag policy profiles (env=prod gets PCI-style strictness, env=dev
  relaxed) — could attach via the `BLACKWATCH_TAGS` mechanism
- Network-attached file tracking (NFS / EFS shares) — currently we just
  hash whatever the agent can stat; remote mounts work but are slow
- "What did this user do today" timeline by joining `fim_history.actor_*`
  across instances — easy UI add when needed

---

## 14. Quick reference

| Need to … | Command / file |
|---|---|
| See FIM status across all hosts | `/fim` |
| See one host's monitored paths + recent changes | `/fim/<instance_id>` |
| Check a single FIM event in full | `/events/<event_id>` |
| Add a path to watch | `systemctl edit blackwatch-agent` → `Environment=BLACKWATCH_FIM_EXTRA_DIRS=...` → restart |
| Disable FIM entirely on one host | `Environment=BLACKWATCH_FIM_DISABLED=1` |
| Verify auditd rules loaded | `sudo auditctl -l \| grep bw_fim` |
| Verify inotify watches active | `journalctl -u blackwatch-agent \| grep "inotify active"` |
| Trigger a real-time FIM event | `sudo touch /etc/cron.d/bw-fim-test && sleep 2 && sudo rm /etc/cron.d/bw-fim-test` |
| Inspect the local baseline | `sudo sqlite3 /var/lib/blackwatch-agent/fim/baseline.db 'select count(*) from baseline'` |
| Tail FIM-related journal lines | `journalctl -u blackwatch-agent -f \| grep -iE "fim\|inotify\|audit"` |
| Force an immediate scan | `sudo systemctl restart blackwatch-agent` (next scan runs in 15s) |

---

## Related docs

- [`docs/ec2-agent.md`](ec2-agent.md) — the agent overall (install, sandbox, all collectors, IAM)
- [`docs/vpn-agent.md`](vpn-agent.md) — sister VPN agent (no FIM, same hardening playbook)
- [`docs/EVENT_SCHEMA.md`](EVENT_SCHEMA.md) — Event envelope schema
