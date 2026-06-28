# OpenVPN agent — full reference

The canonical document for the BlackWatch OpenVPN agent: what it does,
where it lives, how to install/upgrade it, what it protects against, and
how to verify it's working.

Sister doc to [`docs/ec2-agent.md`](ec2-agent.md) — the two agents share
the same design (push-to-SQS, root-with-sandbox, watchdog, scrubbing,
spool with bounds, send backoff) but the VPN agent has two threads, cert
inventory, and OpenVPN-specific journal parsing.

Current agent version: **v0.6** (hardened: scrubbing, sandbox, watchdog,
size caps, send backoff, spool bounds)

For OpenVPN box facts you keep in your head (unit name, status file
location, PAM + Google Authenticator config, CRL fix status), see
[`vpn-info.md`](vpn-info.md).

---

## 1. What it does

Runs as a systemd service on the OpenVPN EC2 box. Two threads, one
process:

**Heartbeat thread** (every `INTERVAL` seconds, default 60):
1. `systemctl is-active openvpn-server@server` — service state.
2. Verbatim `/var/log/openvpn/status.log` (root-owned).
3. Recent `AUTH_FAILED` / `authentication succeeded` lines from the
   journal, over an overlapping window — a safety net if the follower
   missed something.
4. Snapshot every cert + CRL on disk (PKI dir + live OpenVPN dir).
5. Pushes ONE `vpn_report` JSON message to SQS.

**Follower thread** (long-running `journalctl -fu openvpn-server@server`):
1. Batches matched auth lines (≤10 lines OR 1s window).
2. Pushes each batch as a `vpn_auth_realtime` SQS message — **sub-second
   alert latency** without polling.
3. Persists `__CURSOR` so a restart resumes exactly where it left off
   (no replays, no gaps).

Both threads share the same SQS client, spool dir, and `send()` function
(with shared failure counter for backoff).

---

## 2. Architecture / pipeline

```
   ┌──────────────────────────────────┐                                 ┌─────────────────────────┐
   │  OpenVPN box                     │                                 │  BlackWatch             │
   │                                  │                                 │  (Docker / Lightsail)   │
   │  vpn_agent.py (2 threads)        │   sqs:SendMessage               │                         │
   │  ┌───────────────────────────┐   │   (instance role)               │  aws_sqs.drain()        │
   │  │ heartbeat (every 60s)     │   │                                 │   │                     │
   │  │  - systemctl state        │   │ ─────────────────────────────►  │   ▼                     │
   │  │  - status.log             │   │   queue: blackwatch-vpn-agents  │  VpnOpenVpnAdapter      │
   │  │  - auth lines (overlap)   │   │                                 │   │                     │
   │  │  - cert inventory         │   │                                 │   ▼                     │
   │  │  - sd_notify WATCHDOG=1   │   │                                 │  pipeline.ingest_payload│
   │  └───────────────────────────┘   │                                 │   │                     │
   │  ┌───────────────────────────┐   │                                 │   ▼                     │
   │  │ follower (journalctl -f)  │   │                                 │  events table +         │
   │  │  - tail journal in JSON   │   │                                 │  vpn projection         │
   │  │  - batch matched lines    │   │                                 │  /vpn page              │
   │  │  - flush + save __CURSOR  │   │                                 │                         │
   │  └───────────────────────────┘   │                                 └─────────────────────────┘
   └──────────────────────────────────┘
```

Outbound to SQS only. No inbound port opened. The VPN box's OpenVPN
service (UDP/1194 typically) is unrelated to this agent.

---

## 3. Files & paths

### On the OpenVPN box (set up by `install-vpn-agent.sh`)

| Path | Mode | Purpose |
|---|---|---|
| `/opt/blackwatch/vpn_agent.py` | `0755 root:root` | The agent script. Not a secret. |
| `/etc/systemd/system/blackwatch-vpn-agent.service` | `0644 root:root` | systemd unit. Owns env vars + sandboxing. |
| `/var/lib/blackwatch-vpn-agent/` | `0700 root:root` | Base. Locked at install. |
| `/var/lib/blackwatch-vpn-agent/spool/` | `0700 root:root` | Created on first send failure. Files `0600`. |
| `/var/lib/blackwatch-vpn-agent/spool/<ms>-<tid>.json` | `0600 root:root` | One spooled payload. JSON. |
| `/var/lib/blackwatch-vpn-agent/journal_cursor` | `0600 root:root` | Follower's last `__CURSOR`. Atomic write. |
| systemd journal (`journalctl -u blackwatch-vpn-agent`) | n/a | Agent stdout/stderr. |
| `/var/log/openvpn/status.log` | `0600 root:root` | OpenVPN's status file — agent reads. |
| `/etc/openvpn/easy-rsa/pki/` | root-only | Source-of-truth PKI dir. Agent reads ca.crt, issued/*.crt, revoked/certs_by_serial/*.crt, crl.pem. |
| `/etc/openvpn/server/` | root-only | Live OpenVPN dir. Agent reads server*.crt, ca.crt, crl.pem. |

### In the BlackWatch repo

| Path | Purpose |
|---|---|
| `scripts/vpn_agent.py` | Source-of-truth for the agent. Pushed to `/opt/blackwatch/` on the VPN box. |
| `deploy/vpn/install-vpn-agent.sh` | Idempotent installer. Sandbox + watchdog config. |
| `deploy/vpn/setup.ps1` | One-time AWS bootstrap (queue + IAM policy). |
| `deploy/vpn/blackwatch-vpn-agent-send-policy.json` | Minimal IAM policy: `sqs:SendMessage` to the VPN queue. |
| `deploy/vpn/README.md` | Quick-start. |
| `blackwatch/modules/vpn_openvpn.py` | Adapter that turns payloads into BlackWatch Events. |
| `blackwatch/vpn/projection.py` | Stateful read-model (last-seen server, connected clients, cert status). |
| `blackwatch/connectors/aws_sqs.py` | Generic SQS poller. `target_module=vpn.openvpn` routes to the adapter. |
| `docs/vpn-agent.md` | **This file.** |
| `docs/vpn-info.md` | OpenVPN box facts (unit, PAM, CRL fix, etc.). |

---

## 4. Configuration (environment variables)

All set in the systemd unit's `Environment=` lines.

### Required

| Variable | Example | Purpose |
|---|---|---|
| `BLACKWATCH_VPN_SQS_URL` | `https://sqs.us-west-1.amazonaws.com/095899260107/blackwatch-vpn-agents` | The VPN queue. Validated by regex at startup. |

### Common overrides

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | from IMDS | SQS queue region. |
| `INTERVAL` | `60` | Heartbeat tick (also `auth_lines` lookback = `INTERVAL + 120s`). |
| `OPENVPN_UNIT` | `openvpn-server@server` | systemd unit to monitor. Box's unit; not the agent's own. |
| `OPENVPN_STATUS_FILE` | `/var/log/openvpn/status.log` | OpenVPN's status file. Defined by the unit's `--status` directive. |
| `OPENVPN_PKI_DIR` | `/etc/openvpn/easy-rsa/pki` | easy-rsa source-of-truth PKI dir. |
| `OPENVPN_LIVE_DIR` | `/etc/openvpn/server` | OpenVPN's live config dir. |
| `SERVER_NAME` | `openvpn` | Logical server ID BlackWatch shows. Used in event `target.id`. |
| `SPOOL_DIR` | `/var/lib/blackwatch-vpn-agent` | Parent of `spool/` and `journal_cursor`. |
| `SPOOL_MAX_FILES` | `5000` | Hard cap on spool file count. |
| `SPOOL_MAX_BYTES` | `100*1024*1024` (100 MB) | Hard cap on spool total bytes. |
| `FOLLOWER_ENABLED` | `1` | `0` disables the realtime tail thread (heartbeat only). |
| `FOLLOWER_BATCH_MAX` | `10` | Max auth lines per follower batch before flush. |
| `FOLLOWER_BATCH_WINDOW` | `1.0` | Max seconds to wait before flushing a partial batch. |

---

## 5. What gets collected

### Heartbeat payload (`kind: vpn_report`)

Shipped every `INTERVAL`. Shape:

```jsonc
{
  "kind": "vpn_report",
  "agent_version": "0.6",
  "server": "openvpn-prod-1",                         // SERVER_NAME
  "host": { "instance_id": "i-...", "hostname": "...",
            "account": "...", "region": "us-west-1" },// from IMDS
  "uptime_seconds": 123456,
  "state": "active",                                  // systemctl is-active
  "active": true,
  "status_raw": "...",                                // verbatim status.log
  "auth_lines": ["{...journal-json...}", ...],        // scrubbed
  "certs": [
    { "kind": "ca", "name": "ca", "subject": "...",
      "issuer": "...", "not_after": "2027-...",
      "days_remaining": 450, "source": "pki" },
    { "kind": "server", "name": "server_AbC", ... "source": "pki" },
    { "kind": "client", "name": "alice", ... "source": "pki" },
    { "kind": "revoked", "name": "...", "revoked": true,
      ... "source": "pki" },
    { "kind": "crl", "name": "crl", "last_update": "...",
      "not_after": "...", "days_remaining": 12, "source": "pki" },
    // same kinds repeated with source: "live" from /etc/openvpn/server/
  ],
  "truncated": []                                     // present only when size cap kicked in
}
```

### Follower payload (`kind: vpn_auth_realtime`)

Shipped within ~1 second of the journal line landing:

```jsonc
{
  "kind": "vpn_auth_realtime",
  "agent_version": "0.6",
  "server": "openvpn-prod-1",
  "host": { ... },
  "auth_lines": ["{...one journal entry...}", ...]    // scrubbed
}
```

### What the adapter recognizes in `auth_lines`

OpenVPN with PAM + Google Authenticator produces these:

| Source line | Action emitted | Notes |
|---|---|---|
| `… TLS: Username/Password authentication succeeded for username 'alice'` | `vpn.auth.success` | Pre-MFA TLS step. |
| `… SENT CONTROL [alice]: 'AUTH_FAILED' (status=1)` | `vpn.auth.failure` | Wrong TOTP, expired cert, etc. |

Cert events derive from the `certs` snapshot in the projection — see
section 6.

---

## 6. Events emitted (BlackWatch-side)

The `VpnOpenVpnAdapter` produces these. Action names visible in `/events`:

| Action | Trigger | Notes |
|---|---|---|
| `vpn.service.health` | every heartbeat | Drives `vpn_status` read model. Projection-only (not stored as event). |
| `vpn.status.snapshot` | every heartbeat with `status_raw` | Currently-connected client set. Projection-only. |
| `vpn.cert.snapshot` | every heartbeat with `certs` | Full cert inventory. Projection-only. |
| `vpn.auth.success` | matched success line | `actor.principal=username`, `actor.source_ip=ip` (from journal). |
| `vpn.auth.failure` | matched AUTH_FAILED line | Same shape. Severity from rules. |
| `vpn.cert.expiring.warning` | days_remaining < 30 (per cert) | Per-cert. Deterministic event_id by (server, kind, name, band). |
| `vpn.cert.expiring.high` | days_remaining < 14 | Severity-band escalation. |
| `vpn.cert.expiring.critical` | days_remaining < 7 | |
| `vpn.cert.expired` | days_remaining < 0 | |
| `vpn.cert.probe.failed` | openssl couldn't read a cert | Hardware fault, perms drift. |

Projection-derived events (`blackwatch/vpn/projection.py`):

| Action | Trigger |
|---|---|
| `vpn.service.down` | heartbeat shows `active=false` after being `true` |
| `vpn.service.up` | inverse transition |
| `vpn.session.start` | client appeared in `status_raw` |
| `vpn.session.end` | client disappeared |
| `vpn.cert.drift` | live dir cert differs from PKI dir cert (renew-but-forgot-to-copy) |

---

## 7. IAM (the only AWS permission the agent needs)

`deploy/vpn/blackwatch-vpn-agent-send-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BlackWatchVpnAgentSendToQueue",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:blackwatch-vpn-agents"
    }
  ]
}
```

Same shape as the EC2 agent's — `sqs:SendMessage` to one queue. Nothing else.

The OpenVPN box's instance role can therefore hold BOTH policies (this
one + the EC2 agent's), letting both agents coexist with minimal,
disjoint privileges.

---

## 8. Security model (the hardening)

Same playbook as the EC2 agent. Refer to
[ec2-agent.md §8](ec2-agent.md#8-security-model-the-hardening) for the
shared details (systemd directives, version compat table, scrubber
patterns); this section calls out the VPN-specific bits.

### 8.1 Privilege model

Runs as **root** because it must:
- Read `/var/log/openvpn/status.log` (root:root 0600)
- Read journald for the OpenVPN unit
- Read `/etc/openvpn/easy-rsa/pki/*` (root-only)
- Read `/etc/openvpn/server/*` (root-only)
- Call `openssl x509 -noout -enddate -subject` on each cert

Can't drop privileges → sandboxed instead.

### 8.2 systemd sandboxing

Identical to the EC2 unit. Effective directives on AL2 (systemd 219):

| Directive | Effect |
|---|---|
| `NoNewPrivileges=true` | |
| `ProtectSystem=full` | |
| `ProtectHome=read-only` | |
| `PrivateTmp=true` | |
| `PrivateDevices=true` | |
| `SystemCallArchitectures=native` | |
| `SystemCallFilter=@system-service` | |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK` | |
| `WatchdogSec=180` | Heartbeat thread pings; if it hangs >3 min, SIGKILL + restart. |

Additional directives auto-activate on systemd 231+ (AL2023 / Ubuntu
22.04+) — `ProtectKernelTunables`, `ProtectKernelModules`, `ReadWritePaths`,
`ProtectControlGroups`, `ProtectClock`, `Restrict{Namespaces,Realtime,SUIDSGID}`,
`LockPersonality`,
`LogRateLimit*`. Same list as the EC2 unit.

### 8.3 Resource limits

| Directive | Limit |
|---|---|
| `MemoryLimit=200M` | OOM-killed if exceeded |
| `CPUQuota=20%` | Throttled if exceeded |
| `TasksMax=64` | Process/thread cap |
| `LimitNOFILE=1024` | Open file descriptor cap |
| `Nice=10` | De-prioritized vs. OpenVPN itself |

### 8.4 Secret scrubbing

Same patterns as the EC2 agent (`mysql -p…`, `--token=…`, `PGPASSWORD=…`,
`AKIA…`/`ASIA…`, generic `*KEY=`/`*SECRET=`/`*TOKEN=`/`*PASSWORD=`,
`Authorization: Bearer/Basic`). Applied to the `MESSAGE` field of every
journal line shipped (both heartbeat-path and follower-path). `__CURSOR`
and `__REALTIME_TIMESTAMP` are preserved so dedup at the adapter still
works.

OpenVPN's PAM plugin doesn't put passwords in clear, but TOTP codes and
client-side argument strings can leak through. The scrubber catches the
common shapes.

### 8.5 Spool + cursor file permissions

| Path | Mode |
|---|---|
| `/var/lib/blackwatch-vpn-agent/` | `0700 root:root` |
| `/var/lib/blackwatch-vpn-agent/spool/` | `0700 root:root` |
| `/var/lib/blackwatch-vpn-agent/spool/*.json` | `0600 root:root` |
| `/var/lib/blackwatch-vpn-agent/journal_cursor` | `0600 root:root` (atomic write via temp + rename) |

Spool files contain scrubbed journal lines + cert metadata. Cursor file
contains nothing sensitive but is locked anyway.

### 8.6 SQS URL allowlist

Regex-checked at startup against:
```
^https://sqs\.[a-z0-9-]+\.amazonaws\.com/\d{12}/[A-Za-z0-9_\-]{1,80}$
```
Refuses to start otherwise. Catches tampered systemd units pointing at
attacker-controlled queues. IAM policy is the real defense; this is the
fail-fast signal.

### 8.7 Payload size cap

SQS body limit: 256 KiB. Agent reserves 240 KiB. If exceeded, drops in
priority order:

1. `status_raw` (verbatim status.log — biggest field on busy servers)
2. `certs` (large on PKIs with many revoked client certs)
3. `auth_lines` (last resort — heartbeat backstop refills next tick)

What was dropped is annotated in `payload.truncated: [...]` and surfaces
as a `trunc=...` flag in the agent's per-message log line.

### 8.8 Send-failure backoff

Shared counter across both threads (heartbeat + follower):

| Consecutive failures | Extra sleep after spool |
|---|---|
| 1–3 | none (transient) |
| 4–6 | 30 s |
| 7–9 | 60 s |
| 10–12 | 90 s |
| ≥ 13 | 300 s (capped) |

Resets to zero on first successful send (from either thread).

### 8.9 Watchdog

`Type=notify` + `WatchdogSec=180`. **Heartbeat thread** pings after every
tick. The **follower thread is intentionally NOT watchdog-covered**:
auth-line quiet periods are normal (the VPN can sit idle for hours
between logins), and you don't want systemd killing the agent because
nobody connected.

The follower has its own resilience: a respawn loop that re-spawns
`journalctl -fu` with backoff on EOF/error, and clears the cursor if
it's stale (e.g. journal vacuumed).

### 8.10 Spool bounds

`SPOOL_MAX_FILES=5000`, `SPOOL_MAX_BYTES=100 MB`. Walks oldest-first,
deletes until under cap. Better to lose oldest backlog than fill `/var`.

---

## 9. Installation

### 9.1 Prerequisites

- The OpenVPN box itself, with `openvpn-server@server.service` running.
- Instance role attached, with the `blackwatch-vpn-agent-send` policy
  (section 7).
- `python3 >= 3.7`, `journald`, `openssl`. All present on AL2 by default.
- Outbound HTTPS to SQS endpoint (egress to `sqs.<region>.amazonaws.com`
  on 443).
- The journal-read sudoers grant from the earlier setup (`usermod -aG
  systemd-journal ec2-user`) — only needed if you want to inspect from
  the agent's user without sudo. The agent itself runs as root.

Note: the EC2 host agent can run on this same box at the same time —
they're separate units, separate queues, separate IAM policies. No
conflict.

### 9.2 Install steps

On your dev machine:

```powershell
$KEY = "<your .pem>"
$BOX = "ec2-user@52.9.243.84"

scp -i $KEY scripts/vpn_agent.py                ${BOX}:/tmp/
scp -i $KEY deploy/vpn/install-vpn-agent.sh     ${BOX}:/tmp/
```

On the box:

```bash
sudo BLACKWATCH_VPN_SQS_URL="https://sqs.us-west-1.amazonaws.com/<ACCT>/blackwatch-vpn-agents" \
     AWS_REGION="us-west-1" \
     INTERVAL="60" \
     OPENVPN_UNIT="openvpn-server@server" \
     OPENVPN_STATUS_FILE="/var/log/openvpn/status.log" \
     SERVER_NAME="openvpn-prod-1" \
     AGENT_SRC=/tmp/vpn_agent.py \
     bash /tmp/install-vpn-agent.sh
```

What the install script does:

1. Validates `BLACKWATCH_VPN_SQS_URL` is set.
2. Installs `python3-pip` if missing (yum/dnf/apt-get).
3. `pip3 install 'boto3>=1.28,<1.35'` — same pin as EC2 agent.
4. Creates dirs: `/opt/blackwatch` (0755) and `/var/lib/blackwatch-vpn-agent` (0700).
5. Copies the agent (skipped if `AGENT_SRC == /opt/blackwatch/vpn_agent.py`).
6. Preflight: `aws sts get-caller-identity` + `aws sqs get-queue-attributes`.
7. Writes `/etc/systemd/system/blackwatch-vpn-agent.service` with the
   full sandboxing + watchdog config.
8. `systemctl daemon-reload` → `enable` → **`restart`** (forced — not
   `enable --now`, which is a no-op when active).
9. Prints `systemctl status` first lines for sanity.

### 9.3 Upgrade / reinstall

Same as EC2 agent. Re-run with a new `AGENT_SRC` to swap the script;
re-run with `AGENT_SRC=/opt/blackwatch/vpn_agent.py` to refresh ONLY
the systemd unit (the script's same-file detection skips the copy and
proceeds with the rest).

### 9.4 Uninstall

```bash
sudo systemctl stop blackwatch-vpn-agent
sudo systemctl disable blackwatch-vpn-agent
sudo rm -f /etc/systemd/system/blackwatch-vpn-agent.service
sudo systemctl daemon-reload
sudo rm -rf /opt/blackwatch/vpn_agent.py /var/lib/blackwatch-vpn-agent
# Optional: detach the IAM policy from the instance role.
```

(If the EC2 agent is also installed, leave `/opt/blackwatch/` alone —
it holds `ec2_agent.py` too.)

---

## 10. Operational commands

### Status + logs

```bash
sudo systemctl status blackwatch-vpn-agent
sudo journalctl -u blackwatch-vpn-agent -f
sudo journalctl -u blackwatch-vpn-agent --since "10 min ago" --no-pager
```

### Per-message log line — field reference

```
[heartbeat] sent kind=vpn_report auth_lines=2
[follower] sent kind=vpn_auth_realtime auth_lines=1
[heartbeat] sent kind=vpn_report auth_lines=1 trunc=status_raw,certs
```

| Field | Meaning |
|---|---|
| `[heartbeat]` / `[follower]` | Which thread shipped this. |
| `kind=vpn_report` / `vpn_auth_realtime` | Payload type. |
| `auth_lines=N` | Number of journal entries in the payload. |
| `trunc=status_raw,certs` | Size cap dropped these fields (rare unless huge PKI). |

Failure paths print:
```
[heartbeat] send failed (#1), spooling: <reason>
[heartbeat] backing off 30s after 4 failures
```

### Force a heartbeat + exit (debug)

```bash
sudo /usr/bin/python3 /opt/blackwatch/vpn_agent.py --once
```

Runs ONE heartbeat tick (no follower thread). Useful when systemd-managed
output is hiding something.

### Restart, stop, start

```bash
sudo systemctl restart blackwatch-vpn-agent
sudo systemctl stop blackwatch-vpn-agent
sudo systemctl start blackwatch-vpn-agent
```

### Inspect spool + cursor

```bash
sudo ls -la /var/lib/blackwatch-vpn-agent/
sudo cat /var/lib/blackwatch-vpn-agent/journal_cursor    # follower's last position
sudo ls -la /var/lib/blackwatch-vpn-agent/spool/         # pending payloads
sudo cat /var/lib/blackwatch-vpn-agent/spool/<latest>.json | jq .
```

### Reset follower from "now" (forget cursor)

If the journal has been vacuumed and the cursor is stale:
```bash
sudo systemctl stop blackwatch-vpn-agent
sudo rm -f /var/lib/blackwatch-vpn-agent/journal_cursor
sudo systemctl start blackwatch-vpn-agent
# Follower now tails from end-of-journal (no replay of old auth lines).
```

The agent does this automatically when journalctl exits within 3 seconds
of spawn — assumed to mean the cursor is invalid.

---

## 11. Verifying hardening is active

```bash
# Sandboxing. systemd 219 (AL2) silently omits unrecognized properties
# from `show`; check the unit file directly if so.
sudo systemctl show blackwatch-vpn-agent \
  -p NoNewPrivileges -p ProtectSystem -p ProtectHome \
  -p PrivateTmp -p PrivateDevices \
  -p WatchdogSec -p RestrictAddressFamilies

# Expected on AL2:
#   NoNewPrivileges=yes
#   ProtectSystem=full
#   ProtectHome=read-only
#   PrivateTmp=yes
#   PrivateDevices=yes
#   WatchdogSec=3min      (may be missing from show; check unit file)
#   RestrictAddressFamilies=[unprintable]   (set, display quirk on 219)

# Read directly from the unit file (ProtectKernelTunables and friends are
# in the file but ignored on AL2 — they auto-activate on AL2023+):
sudo grep -E "^(WatchdogSec|RestrictAddressFamilies|Type|NotifyAccess)=" \
  /etc/systemd/system/blackwatch-vpn-agent.service

# Spool dir is locked.
sudo stat -c "%a %U %G" /var/lib/blackwatch-vpn-agent
# 700 root root

# Cursor file is locked.
sudo stat -c "%a %U %G" /var/lib/blackwatch-vpn-agent/journal_cursor 2>/dev/null || \
  echo "cursor file not present yet (follower hasn't saved one)"
# 600 root root  (when present)

# Watchdog alive — silence = working
sudo journalctl -u blackwatch-vpn-agent --since "10 min ago" | grep -i "watchdog timeout" \
  || echo "no watchdog timeouts (good)"
```

### Test scrubbing end-to-end

The VPN journal lines come from OpenVPN, not from arbitrary processes,
so the scrubber's MAIN exposure is the `MESSAGE` field on PAM auth
lines. Easiest verification:

```bash
# Tail the journal, scrub one line in-place to confirm
sudo journalctl -u openvpn-server@server -n 5 --output=json \
  | python3 -c "
import json, sys
sys.path.insert(0, '/opt/blackwatch')
from vpn_agent import scrub_auth_line
for line in sys.stdin:
    if not line.strip(): continue
    out = scrub_auth_line(line)
    parsed = json.loads(out)
    print(parsed.get('MESSAGE', ''))
"
```

Should print MESSAGE values with any `--token=...`, `password=...`, etc.
replaced by `***`. Real OpenVPN PAM lines won't contain secrets, but the
scrubber pipeline is exercised.

---

## 12. End-to-end pipeline

```
[on OpenVPN box]                  [AWS]                    [BlackWatch]
   vpn_agent.py heartbeat thread  
   └─ systemctl is-active                                   
   └─ read status.log                                       
   └─ journalctl --since (auth)                             
   └─ openssl x509 (cert inventory)                         
   └─ scrub() on each auth line                             
   └─ _shrink_for_sqs() cap                                 
   └─ boto3 SendMessage   ──────►   SQS queue          ───► aws_sqs.drain()
                                    blackwatch-vpn-agents     └─ json.loads
   vpn_agent.py follower thread                                └─ pipeline.ingest_payload(
   └─ journalctl -fu (tail)                                       module="vpn.openvpn", ...)
   └─ batch matched lines                                       └─ VpnOpenVpnAdapter.parse()
   └─ scrub()                                                      │ classify auth lines
   └─ save cursor                                                  │ build Events
   └─ boto3 SendMessage   ──────►   (same queue)        ──►        │ deterministic event_ids
                                                                └─ engine.evaluate()
                                                                └─ storage.insert_event() (only if new)
                                                                └─ notifier.dispatch() (only on insert)
                                                                └─ vpn.projection.project()
                                                                   └─ diff vs last status snapshot
                                                                   └─ diff vs last cert snapshot
                                                                   └─ emit derived events
                                                                      (service.down, session.start,
                                                                       cert.drift, etc.)
```

### Dedup model

Two layers:

1. **Per-line journal cursor** in event_id (`uuid5(NAMESPACE_URL,
   f"vpn-auth:{__CURSOR}")`). The heartbeat's overlapping window
   re-ships lines the follower already shipped, but both produce the
   same event_id → `ON CONFLICT DO NOTHING` at insert.
2. **Insert-gated dispatch** (pipeline v1.2+): notifications fire ONLY
   on a genuinely new row. Re-shipped lines don't double-notify.

---

## 13. Failure modes & recovery

| Symptom | Diagnosis | Recovery |
|---|---|---|
| `send failed: AccessDenied` repeating | Instance role missing the `blackwatch-vpn-agent-send` policy | Attach; verify with `aws sqs get-queue-attributes --queue-url $URL` |
| `send failed: Could not connect to the endpoint URL` | Egress to SQS blocked | Allow outbound 443 to `sqs.<region>.amazonaws.com` |
| `ERROR: BLACKWATCH_VPN_SQS_URL doesn't look like a valid SQS URL` at startup | Typo / tampered unit | Fix env in `/etc/systemd/system/blackwatch-vpn-agent.service`, `daemon-reload`, restart |
| `watchdog timeout (limit 3min)` in journal | Heartbeat tick hung >3 min (status.log read, openssl, or journalctl blocked) | systemd auto-restarts. If recurring, check `openvpn-server@server` status and disk I/O |
| `follower: spawn failed` repeating | journalctl missing or wrong unit name | Verify `OPENVPN_UNIT` env var matches `systemctl list-units` output |
| `follower: subprocess exited fast — clearing cursor` | Journal vacuumed; cursor invalid | Self-heals; ignore unless it loops |
| `trunc=status_raw,certs` every heartbeat | PKI has hundreds of revoked certs OR status.log huge | Expected; truncation recorded. To reduce: trim revoked certs in PKI |
| `/vpn` page shows server stale | Either agent down OR connector not draining | Check `systemctl status blackwatch-vpn-agent`; check connector last_run_at |
| `/vpn` shows server up but no recent auth lines | Either nobody logged in OR follower thread crashed | Trigger a test login. If still nothing, restart agent |
| No `vpn.auth.*` events in DB despite logins | Adapter rejecting payloads silently | Check app logs; the adapter's strict regex may not match this OpenVPN version's log format |

### Total data loss scenarios

- Spool dir wiped → that backlog is gone; agent recreates on next spool.
- Cursor file wiped → follower restarts from end-of-journal (no replay
  of past auth lines; heartbeat still backfills the last `INTERVAL+120s`).
- OpenVPN box terminated → that server's history gone. BW retains
  whatever events have already landed.

---

## 14. Known limitations / accepted risk

| Risk | Mitigation today | Future |
|---|---|---|
| Compromised VPN box could spoof events for another `server` name | IAM policy on instance role; only this box has it attached; adapter has no sender verification | Per-instance HMAC via SSM Parameter Store |
| Tampered agent at `/opt/blackwatch/vpn_agent.py` not detected | File `0755 root:root` | Code-signing + signature check at startup |
| Follower thread not watchdog-covered | Heartbeat thread keeps unit alive; follower has its own respawn loop | Cross-thread liveness check feeding sd_notify |
| Local journal can be tampered with by root | None — root on the box can do anything | Remote journald forwarder |
| Adapter doesn't validate SQS sender identity | IAM policy = single-tenant queue; one role can send | SNS Topic with SubscriptionFilter encoding sender ARN |
| Cert metadata leaks subject/issuer (public info) to BW | Acceptable — same data anyone with cert access can read | n/a |

### Out of scope

- Decrypting OpenVPN traffic (we don't, never will).
- Monitoring client-side state (the agent is server-side only).
- Real-time DPI / packet inspection — that's a different feature.
- Certificate ENROLLMENT — we only watch existing PKI files.

---

## 15. Quick reference card

```
INSTALL:        sudo BLACKWATCH_VPN_SQS_URL=... AWS_REGION=... AGENT_SRC=/tmp/vpn_agent.py bash /tmp/install-vpn-agent.sh
LOGS LIVE:      sudo journalctl -u blackwatch-vpn-agent -f
LOGS RECENT:    sudo journalctl -u blackwatch-vpn-agent --since "10 min ago" --no-pager
STATUS:         sudo systemctl status blackwatch-vpn-agent
FORCE HEARTBEAT:sudo /usr/bin/python3 /opt/blackwatch/vpn_agent.py --once
RESTART:        sudo systemctl restart blackwatch-vpn-agent
SPOOL DIR:      /var/lib/blackwatch-vpn-agent/spool/
CURSOR FILE:    /var/lib/blackwatch-vpn-agent/journal_cursor
UNIT FILE:      /etc/systemd/system/blackwatch-vpn-agent.service
AGENT BINARY:   /opt/blackwatch/vpn_agent.py
IAM POLICY:     blackwatch-vpn-agent-send (sqs:SendMessage to blackwatch-vpn-agents)
SQS QUEUE:      blackwatch-vpn-agents (region: us-west-1)
TARGET MODULE:  vpn.openvpn (BlackWatch SQS connector)
PIPELINE:       agent (2 threads) → SQS → aws_sqs.drain → VpnOpenVpnAdapter → pipeline → events table + vpn projection
OPENVPN UNIT:   openvpn-server@server  (the unit we monitor, not the agent)
STATUS FILE:    /var/log/openvpn/status.log
PKI DIR:        /etc/openvpn/easy-rsa/pki
LIVE DIR:       /etc/openvpn/server
```

---

*Document version: v0.6 (matches agent version). Update on any agent or
install-script change.*

---

## Related docs

- [`docs/ec2-agent.md`](ec2-agent.md) — sister doc for the EC2 agent (same hardening playbook + collectors)
- [`docs/fim.md`](fim.md) — File Integrity Monitoring. Lives inside the EC2 agent, not the VPN agent. The VPN box can also host a co-installed EC2 agent if you want FIM coverage of OpenVPN config files.
- [`vpn-info.md`](vpn-info.md) — VPN box runtime facts (unit name, PAM, CRL state)
- [`docs/EVENT_SCHEMA.md`](EVENT_SCHEMA.md) — Event envelope schema
