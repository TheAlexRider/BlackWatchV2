# BlackWatch — Future Modules (Backlog)

Planned telemetry modules not yet built. Each should reuse the existing
foundation (event schema, adapters, Connectors subsystem, rules, projection
read-models, UI pages) — additive only.

---

## RDS Postgres module

Goal: same shape as the VPN module — list current connections + IPs, recent
connection attempts, plus production-DB security monitoring.

### VPN → RDS Postgres analogy (and the catch)

| VPN module | RDS Postgres equivalent | Source |
|---|---|---|
| status file = who's connected now | `pg_stat_activity` view | direct SQL |
| service up/down | can we connect? + RDS instance status | SQL connect test (+ AWS API) |
| journal = login successes/**failures** | Postgres server log | **logs, not SQL** |

The catch: **current connections = one SQL query, but failed login attempts are
NOT queryable.** A failed auth never creates a session, so it never appears in
`pg_stat_activity`; failed attempts live only in the Postgres log → on RDS that
means CloudWatch Logs or the RDS log API (needs AWS access).

- Current actives + IPs + recent *successful* connections → SQL-only.
- Recent *failed* tries (brute force) → needs RDS log access (AWS).

### Reachability (the real hurdle)

RDS is private (correct). BlackWatch on the PC can't connect directly. Reuse the
existing access: the OpenVPN EC2 box is inside the VPC and can reach RDS, so
**SSH to that bastion and run `psql` there** (exactly like the VPN connector runs
`cat`/`journalctl`); ship query output raw, parse in the adapter. No direct path,
no Postgres driver in the container, no tunnel. The same SSH path can later run
`aws rds download-db-log-file-portion` on the bastion for failed-auth logs.

### What it collects (Phase 1, SQL via SSH+psql)

- **Current connections** (`pg_stat_activity` + `pg_stat_ssl`): user, client IP,
  database, state, application_name, backend_start, SSL yes/no, current query →
  `db.session.snapshot` + live read-model (`/ui/db`).
- **Connection diffs** (snapshot-to-snapshot) → `db.session.start` / `db.session.end`
  (= recent *successful* connections).
- **Health**: connect ok? nearing `max_connections`? → `db.service.health`.
- **Role inventory** (`pg_roles`, `pg_auth_members`) diffed → `db.role.created`,
  `db.role.granted`.

New category `database` (additive); new `db.*` actions.

### Security monitors (prioritized)

**Tier 1 — high-signal**
1. Failed auth / brute force — *log-based (needs AWS).*
2. Connection from unexpected IP (outside app subnets / bastion / known CIDRs) — SQL.
3. Privileged-role login (master user, `rds_superuser`, high-grant roles) — SQL.
4. Non-SSL / plaintext connection (`pg_stat_ssl`) — SQL.

**Tier 2 — state/diff, SQL**
5. New role/user created or granted into a privileged role.
6. Connection-count anomaly / nearing `max_connections`.
7. Long idle-in-transaction / long-running sessions.
8. Connections to unexpected DBs or by unexpected users.

**Tier 3 — RDS posture & control-plane (needs AWS API + CloudTrail)**
9. RDS publicly accessible / SG open to 0.0.0.0/0:5432.
10. Snapshot exfiltration: `CreateDBSnapshot` → shared/public via `ModifyDBSnapshotAttribute`.
11. Config drift: encryption off, backups/retention reduced, deletion-protection off,
    `log_connections`/`ssl` turned off, `DeleteDBInstance`.

(pgaudit statement-level auditing = Tier 4 — powerful but noisy; skip initially.)

### Architecture fit (additive)
- New connector type `rds_postgres` (configured/tested/run from Settings UI).
- New adapter parsing psql output → `db.*` events.
- `db_status` read-model + projection (parallels `vpn_status`), snapshot diffing.
- New `/ui/db` page mirroring `/ui/vpn`.

### Prerequisites on their side
- Least-priv monitoring role: `CREATE ROLE blackwatch_monitor LOGIN PASSWORD …;
  GRANT pg_monitor TO blackwatch_monitor;` (full `pg_stat_activity` without superuser).
- `psql` on the bastion + creds in bastion `~/.pgpass` (or IAM DB auth).
- Phase 2: bastion `awscli` + instance role with `rds:DownloadDBLogFilePortion`
  (or CloudWatch Logs read); `log_connections=on` in the RDS parameter group.

### Phasing
- Phase 1 (SQL via SSH+psql): current connections + IPs, successful connect/disconnect,
  health, SSL/role/IP monitors, `/ui/db`. No AWS needed.
- Phase 2 (failed auth from RDS logs): needs AWS log access.
- Phase 3 (RDS posture/control-plane): folds into the AWS/CloudTrail module.

### Open decisions
1. Reachability: SSH-to-bastion-run-`psql` (recommended) vs direct connection over tunnel/VPN.
2. Monitoring credential: least-priv `pg_monitor` in bastion `~/.pgpass` (recommended) vs IAM DB auth.
3. Scope: Phase 1 only (no AWS) vs include failed-auth (Phase 2).

---

## EC2 Host Monitoring module (agent → SQS)

Goal: a lightweight **reporter** on every EC2 that ships host-level security
telemetry back to BlackWatch — access attempts, privilege/config changes,
persistence, integrity, heartbeat — **without SSH** and **without BlackWatch
needing to be reachable**.

### Data flow
```
reporter (systemd, each EC2)
  --(instance IAM role, sqs:SendMessage)-->  SQS blackwatch-ec2-agents (+DLQ)
  -->  BlackWatch SQS connector polls
  -->  ec2.host adapter normalizes
  -->  rules + storage + projection (per-host read-model)
  -->  /ui/hosts + alerts
```

Why this shape:
- **No SSH, no inbound** port on the EC2 — the agent only makes outbound calls to SQS.
- **No stored credentials** — the agent uses the instance's **IAM role** (the role is the trust; no enrollment/keys to manage).
- **Works with BlackWatch on the PC** — BlackWatch pulls from SQS; agents never need to reach it.
- **SQS buffers** if BlackWatch is offline; **DLQ** catches poison messages.
- Same connector/adapter/projection pattern as the IAM + VPN modules — additive, nothing rebuilt.

### The reporter agent (on each EC2)
- **Runtime:** **Python 3 + boto3** (consistency with the rest of BlackWatch). Packaged as a **systemd service, runs as root** (needs `/var/log/secure`, `ss -p`, shadow hashes).
- **Host identity:** instance-id from IMDSv2 + hostname + account + region, stamped on every message.
- **Each cycle (~60s)** it builds ONE SQS message containing: a **heartbeat**, **new log events** since the last cursor, and **state snapshots** (when changed / every N cycles).
- **Collection modes (mirror what we've already built):**
  1. **Log events** — incremental tail of journald (sshd, sudo) via a saved cursor → ship matched auth/sudo lines (like the VPN auth capture).
  2. **State snapshots** — `ss -tlnp` (listening ports), `getent passwd`/`group`, hashes of `authorized_keys` + sensitive files (`sshd_config`, `sudoers`, `passwd`/`shadow`), SUID inventory, cron/systemd timers → BlackWatch diffs vs the last snapshot.
  3. **Heartbeat** — always, for liveness/staleness.
- **Local buffering:** small on-disk spool; if SendMessage fails, queue locally and replay later (dedup handles repeats).
- **Least-priv IAM:** instance-role policy allows ONLY `sqs:SendMessage` to the one queue.
- **Config:** queue URL, region, interval, enabled checks (file or instance tags).

### AWS infrastructure (deploy/ec2/)
- SQS `blackwatch-ec2-agents` (+ `blackwatch-ec2-agents-dlq`, maxReceiveCount 5), region **us-west-1** (consistent with the rest).
- **Instance-role policy** (attach to each EC2's instance profile): `sqs:SendMessage` on the queue ARN. Create/attach an instance profile for boxes that lack one (live, no reboot).
- **BlackWatch reader:** extend `blackwatch-sqs-reader` with Receive/Delete/GetQueueAttributes on the new queue (or a second reader).
- Deploy script `deploy/ec2/setup.ps1` (mirrors deploy/iam) + an `install-agent.sh` to drop on each box (binary + systemd unit + config).

### BlackWatch core additions (additive)
- Category **`host`** (additive enum); `host.*` actions.
- Adapter **`ec2.host`** — one agent message → heartbeat event + log-derived events + a snapshot envelope for the projection. Pure.
- Connector: **generalize the SQS connector** to a `sqs` type with a configurable `target_module` (one type serves both `aws.cloudtrail` and `ec2.host`). Config: queue_url, region, profile, target_module.
- Projection + **`host_status` read-model** keyed by instance-id (latest heartbeat, active, last_seen, ports, users, authorized_keys, …). Diffs consecutive snapshots → `host.port.opened/closed`, `host.user.added`, `host.authorized_key.added`, `host.sudoers.changed`, `host.suid.added`.
- **Staleness detection** (the absence-detection we deferred): a periodic scheduler check flags hosts whose `last_seen` exceeds a threshold → `host.agent.stale` (high). Reuse for VPN too.
- UI: **`/ui/hosts`** page (per instance: up/stale, last seen, recent SSH/sudo, open ports, recent changes) + a dashboard tile.
- Rules score `host.*`.

### Normalized actions + field mapping
- `host.auth.ssh.success` / `.failure` — actor.principal=user, source_ip, target=instance-id
- `host.sudo.exec` / `.failure` — actor=user, extra.command
- `host.user.added` / `.removed`, `host.authorized_key.added` (key fingerprint observable)
- `host.port.opened` / `.closed` (extra.port/proc), `host.sudoers.changed`, `host.file.changed` (FIM, target=path)
- `host.cron.added`, `host.service.added`, `host.package.installed` / `.removed`, `host.suid.added`
- `host.service.health` (host/agent up) + `host.agent.stale` (absence)
- Common: source.module=`ec2.host`, account/region, actor (user/ip), target (instance-id/path), observables (ip/user/hash/port), raw=agent payload, deterministic event_id from journald cursor for log events.

### Security monitoring list (tiers · source)
**Tier 1 — access + highest signal (build first)**
- SSH login success *(log)* · SSH failure / invalid user / **brute force** *(log)* · **sudo** usage + failures *(log)* · direct root login *(log)* · new `authorized_keys` *(snapshot-diff)* · user/group + **sudoers** changes *(log + diff)* · new **listening port** *(snapshot-diff)* · **heartbeat** + reboot *(heartbeat)*

**Tier 2 — persistence & integrity**
- cron/systemd-timer/rc additions *(diff)* · **FIM** on sshd_config/sudoers/passwd/shadow/authorized_keys *(hash diff)* · package install/remove *(yum/dnf history)* · new SUID/SGID *(diff)*

**Tier 3 — deep (later)**
- auditd `execve` (exec from /tmp, /dev/shm, as root) *(auditd)* · outbound to bad IPs / large egress *(ss + intel)* · kernel modules / LD_PRELOAD *(auditd)* · **IMDS abuse** (unexpected proc hitting 169.254.169.254) *(auditd/net)*

**Cloud-context (already via the IAM/CloudTrail module — don't duplicate):** instance start/stop/terminate, SG changes, AMI sharing, **SSM StartSession**.

### Detection rules to ship
- `host-ssh-brute-force` — N failures/IP/window — **STATEFUL** (needs the windowed counter; shared with VPN brute force)
- `host-ssh-login-success` (info; high if root / unexpected IP)
- `host-sudo-failure` (medium), `host-new-authorized-key` (high), `host-new-user` (medium), `host-new-sudoer` (high), `host-new-listening-port` (medium/high), `host-fim-critical-file` (high), `host-agent-stale` (high), `host-cron-added` (medium)

### Dedup & noise
- Log events: deterministic event_id from journald cursor → `ON CONFLICT DO NOTHING` (covers SQS redelivery + agent buffer replay).
- Snapshot diffs: idempotent — re-sending the same snapshot yields no change vs stored state, so no duplicate derived events.
- Existing rule toggles + muted-actions controls apply.

### Build phases
- **A (✅ built):** queue + instance-role policy + reader; agent Tier-1 (SSH/sudo auth + heartbeat); `ec2.host` adapter; generalized SQS connector; `/ui/hosts`; **staleness alerting** (the absence-detection capability).
- **B (✅ built):** agent ships state snapshots (ports/users/authorized_keys/sudoers) only on change; projection diffs vs. last; emits `host.port.opened/closed`, `host.user.added/removed`, `host.authorized_key.added/removed`, `host.sudoers.changed`; rules score the new-* ones; `/ui/hosts` gets port/user/key counts + a "Recent state changes" card.
- **C (✅ built):** agent snapshots **critical files**, **cron** (system + drop-ins + per-user), **enabled systemd unit-files**, **SUID binaries** (scoped to /usr/opt/bin/sbin), and **installed packages** (rpm -qa). Diff emits `host.file.changed`, `host.cron.changed`, `host.service.added/removed`, `host.suid.added/removed`, and a single batched `host.packages.changed` (capped at 50 added/removed to bound message size). Five new rules (file/cron/suid = high; service/packages = medium).
- **D (partial ✅):** *Stateful brute-force counter built* — shared across host SSH (`host.auth.ssh.failure → host.bruteforce`) and VPN (`vpn.auth.failure → vpn.bruteforce`). In-memory sliding window (5 failures / 5 min per source IP), suppressed for the rest of the window after one alert. Wired as a projection in the pipeline. Remaining: auditd `execve` and IMDS-abuse detection.
- **Visibility (✅ built):** `/ui/hosts/{instance_id}` per-host detail page — heartbeat, listening ports, **running processes**, users, authorized keys, sudoers, critical files, cron, systemd units, SUID, packages, recent SSH/sudo, recent state changes, recent notable activity. Agent now snapshots `processes` (visibility-only, no diff).

---

## Notifications / Webhooks module (advanced)

Goal: turn the current YAML-only notifier into a **UI-managed, fully customizable**
two-tier system: **rules** (what triggers a notification) and **channels** (how it's
delivered). Reuse what we already have (Condition matching, per-fingerprint dedup,
Slack + webhook channels); add the advanced features.

### Where we are today
- `notifications.yaml` defines channels (slack/webhook) + routes (match by
  severity/category/module/action/tag). Pipeline calls `notifier.dispatch(event)`
  after each stored event. Per-(channel, fingerprint) throttle window dedups floods.
- Limitations: file-only config; only 2 channel types; flat AND matching; no templates,
  retries, digests, silence, history, or acks.

### Two-phase plan

**PHASE 1 — Notification Rules (what fires)** *(✅ built)*

Replace the static YAML routes with a UI-managed, DB-backed rule list, and make the
matching as expressive as the detection rules. Built with migration 007 +
`NotificationRule` model (reusing `Condition`) + refactored Notifier (DB-loaded
rules, per-(rule, channel, fingerprint) throttle, silence_until skip) +
`/ui/notifications/rules` page + 5 endpoints (save/toggle/silence/test/delete) +
one-shot seed from `notifications.yaml` `routes:` on first boot.

- **Data model — `notification_rules` table:**
  `id, name, enabled, match JSONB (Condition tree), channels TEXT[],
   throttle_seconds, silence_until TIMESTAMPTZ, priority, created_at, updated_at`.
- **Match logic:** reuse `Condition` + `eval_condition` from `rules/` — same
  operators (`equals`, `in`, `contains`, `regex`, `cidr`, `exists`, `startswith`,
  `endswith`) and same `all`/`any`/`not` nesting we use for detection rules. One
  match language across the platform.
- **Fan-out:** every matched rule fires its channels (multiple rules can match the
  same event).
- **Throttle:** per-rule override on top of the channel default; (rule, channel,
  dedup_fingerprint) → time-window suppression.
- **Silence / maintenance windows:** UI buttons "silence 1h / 4h / 24h / custom" set
  `silence_until`; matcher skips silenced rules; auto-expires.
- **Test fire:** UI button synthesizes a dummy event whose envelope satisfies the
  rule's match, runs it through channels — confirms wiring end-to-end.
- **Audit:** every rule change writes a row to `notification_rule_changes` (who,
  when, before/after).
- **Stretch (defer if needed):** quiet hours (cron-style schedule), severity
  override per rule, tag injection for templates.

**UI — `/ui/notifications/rules`:**
- Table: name · match summary · channels · enabled · silenced-until · last fired ·
  fired-last-hour.
- Add/Edit form: name, condition editor (YAML), channels multi-select, throttle,
  per-row Silence / Enable / Test / Delete buttons.

**Migration:** on first boot, if `notifications.yaml` exists, seed its routes into
`notification_rules` once (idempotent). After that, YAML is ignored; UI is canonical.

---

**PHASE 2 — Channels & Delivery (how it sends)** *(✅ built)*

Turn the channel layer into a pluggable, reliable, templated delivery system.

Built with migrations 008 (channels) + 009 (log + acks); `Channel` model extended
with template/retries/rate-limit/digest; `channels.py` now has 6 senders
(slack/webhook/email/pagerduty/teams/discord) + Jinja2 templates with per-type
defaults; secrets via env-var references (`password_env`, `routing_key_env`);
`worker.py` send-queue thread (rate-limit + digest + retry-with-backoff + log);
Notifier refactored to enqueue (async); UI pages for **Channels** (CRUD with
type-specific YAML config), **Log** (filterable history), **Acks** (per-fingerprint
silence with Ack button on event-detail page); one-shot seed from
`notifications.yaml` `channels:` on first boot.

- **Channel types (built-in registry):**
  | Type | Status | Notes |
  |---|---|---|
  | `slack` | exists | incoming-webhook URL |
  | `webhook` | exists | generic POST JSON |
  | `email` | new | SMTP host/port/user/pass-ref/from/to |
  | `pagerduty` | new | Events API v2 (routing key) |
  | `teams` | new | MS Teams webhook |
  | `discord` | new | Discord webhook |
  | `aws_sns` | optional | needs AWS creds (reuses our profile mount) |
  | `command` | optional, power-user | local script run with event JSON |
- **Data model — `notification_channels` table:**
  `id, name, type, enabled, config JSONB (per-type schema),
   message_template TEXT, retries, retry_backoff_seconds,
   rate_limit_per_min, digest_window_seconds, dedup_window_seconds,
   last_status, last_error, last_sent_at`.
- **Secrets handling:** never store secrets in the DB. Config references
  **env vars or mounted secret files** (e.g. `password_env: SMTP_PASS`,
  `routing_key_file: /run/secrets/pd_key`) — same approach as our SSH key / AWS
  profile. BlackWatch stays out of the secrets-crypto business.
- **Templating:** Jinja2 (already a dep) per channel, with sensible defaults per
  type. Vars: full event envelope + rule name + channel name. Example Slack
  default: `:rotating_light: *{{ event.severity|upper }}* {{ event.action }}
  by {{ event.actor.principal or 'unknown' }} from {{ event.actor.source_ip or '-' }}`.
- **Reliability:**
  - **Send-queue worker** (background thread; pipeline enqueues only — keeps
    ingest snappy and isolated from slow/flaky channels).
  - **Retries with exponential backoff** per channel; final failure → status
    `failed` in the log + optional fallback channel.
  - **Per-channel rate limit** (max N/min) prevents floods on noisy days.
  - **Digest mode:** channel-level option to collapse N events within
    `digest_window_seconds` into one summary message; one delivery per window.
- **Observability:** `notification_log` table — every send attempt: `ts, event_id,
  rule_id, channel_id, status, retries_used, body_preview, error`. UI page to
  browse + filter + re-send.
- **Acknowledgments:** UI "ack" on an event/fingerprint → row in `notification_acks`
  (`fingerprint, ack_until, by, reason`); notifier skips matching fingerprints until
  expiry. Lets you mute a known-being-investigated alert without disabling the rule.

**UI — `/ui/notifications/channels` + `/ui/notifications/log`:**
- Channels CRUD with type-specific form fields; test-send button per channel.
- Log: time / rule / channel / status / retries; row → full body + error + re-send.

### Architecture
```
event ─▶ pipeline._process ─▶ notifier.evaluate(rules)  ──┐
                                                          ▼
                                  for each matched rule × channel:
                                       enqueue(event, rule, channel, template)
                                                          ▼
                                  send-worker thread ──▶ channel.send()
                                                          ├▶ notification_log
                                                          └▶ retry-on-fail / DLQ
```
Event core untouched; this all hangs off the existing `notifier.dispatch` seam.

### Build phases (within Phase 2)
- 2a: channels in DB + CRUD UI + test-send (replace YAML loader; migrate slack/webhook).
- 2b: add `email`, `pagerduty`, `teams`, `discord` types.
- 2c: per-channel Jinja templates (editable in UI; default per type).
- 2d: send-queue worker + retries + rate limit + `notification_log` UI.
- 2e: digest mode + acks + maintenance windows.

### Decisions to lock before building
1. **Migration:** seed `notifications.yaml` → DB on first boot, then YAML is ignored (recommended), or keep YAML as overlay?
2. **Secrets:** env-var / file references (recommended) or DB-encrypted?
3. **Send-queue:** in-process thread (simple; loses on crash) or DB-backed queue (durable)? Start in-process; add DB-backed only if needed.
4. **Which non-existing channel types to add first** in 2b? My guess: PagerDuty + Email cover most teams.

### Cost
- SQS within free tier at small fleet (~1 msg/host/min); no hosting; instance role = no credential infra. ~$0.

### Decisions (locked)
1. Agent language: **Python 3 + boto3** (consistency with the rest of BlackWatch).
2. **One shared SQS queue** for all hosts (`blackwatch-ec2-agents`).
3. **Log-only first**; auditd deferred to Phase D (phased build).
4. **Generalize the SQS connector** to take a `target_module` field — set `ec2.host` for the agent queue (and `aws.cloudtrail` for the existing one).

---

## ECS service module — PAUSED MID-ROLLOUT

### State as of pause

The module is **fully built and unit-tested (117/117 pass)** but **not yet wired
on a live cluster**. All code is in place; what's missing is the operator side
(IAM, connector creation, target seeding, optional probe-agent deployment).

### What's been built

- `blackwatch/sql/010_services.sql` — `probe_targets`, `service_status`, `probe_agent_status`
- `blackwatch/modules/ecs_probe.py` — adapter (target module `ecs.probe`)
- `blackwatch/services/{projection,staleness}.py` — hysteresis (2 fail → down, 1 success → up), agent staleness check
- `blackwatch/connectors/aws_ecs.py` + `AwsEcsHealthConfig` model — BW-side reader (calls `ecs:DescribeTasks`/`DescribeServices`, aggregates `healthStatus`, smooths `runningCount` for workers)
- `blackwatch/api.py` — `GET /api/probes/targets` (token-auth via `BLACKWATCH_PROBE_VPCS`)
- `blackwatch/ui/views.py` + `services.html` + `services_targets.html` — Services nav + per-target CRUD with live status + tier-aware config templates (one-at-a-time UX, no bulk import in the UI)
- `rules/ecs.yaml` — service.down (high) + prod override (critical) + degraded + probe-agent.stale + recovered + first_seen
- `scripts/ecs_probe.py` + `deploy/ecs/{Dockerfile,setup.ps1,policies}` — the in-VPC probe agent (Phase B, deferred)
- `tests/test_ecs_probe.py` — adapter, healthStatus aggregation, runningCount smoothing (incl. Spot-interruption case)
- `tests/test_transitions.py` — `_PROJECTION_ONLY_ACTIONS` set extended

### Four monitoring tiers (lock how each target gets monitored)

| Tier | How | Done by | When to use |
|---|---|---|---|
| `ecs_health` | `ecs:DescribeTasks → containers[].healthStatus` | BW-side reader (no VPC needed) | Services that ALREADY have a `healthCheck` block in their task def (showed "Healthy" in console) |
| `ecs_running` | smoothed `runningCount` vs `desiredCount` over 5 min | BW-side reader | Workers and services WITHOUT a healthCheck. Survives Fargate Spot interruptions. |
| `http_alive` | GET `<url>`, accept any HTTP response (200/30x/40x = up) | In-VPC probe agent | HTTP-ish services without a healthCheck — no `/health` endpoint required |
| `tcp` | open TCP socket | In-VPC probe agent | Databases / TCP-only services |

### Why the pause / what's next when we resume

1. **BW is on PC, not Lightsail.** The in-VPC probe agent can't reach `localhost:8000`.
   Until BW moves to a public URL, Phase B (`http_alive`/`tcp` tiers) is on hold.
   Phase A (`ecs_health` + `ecs_running`) works fine on the PC.
2. **What still needs to happen for Phase A:**
   - Restart BW container so 010_services.sql runs.
   - Attach the ECS-read IAM policy to `blackwatch-sqs-reader` (DONE in step 2 of the rollout — `read-ecs` inline policy is already attached).
   - In UI: Settings → Add ECS health connector (name=ecs dev cluster, vpc=dev, region=us-west-1, profile=blackwatch, interval=60). Test → Enable.
   - In UI: Services → Manage targets → add targets one-by-one (tier-aware config templates fill in the right shape; one-at-a-time live-feedback flow):
     * `ecs_health` tier: the 5 services that show "Healthy" in the ECS console (internal-api-server, document-llm-api, test-tibco-ems-service, web-admin-api-server, dev-elastic-ingestion-worker-service).
     * `ecs_running` tier: everything else for now (workers + services with no healthCheck).
3. **When BW moves to Lightsail, Phase B:**
   - Run `deploy/ecs/setup.ps1` per VPC.
   - Edit affected targets' tier from `ecs_running` → `http_alive` or `tcp`.
   - No data loss; targets stay, tier flips, config blob shape changes (UI tier picker auto-fills the new shape).

### Honest limitations to remember when resuming

- A worker that's "alive but stuck in an infinite loop" is invisible to any external monitoring without a per-container change. `ecs_running` catches crashed/OOM; not stuck. Queue-depth proxy check could close this later.
- `ecs_health` is empty signal when the task def has no `healthCheck` — we explicitly emit `status=unknown` rather than lie `up`.
