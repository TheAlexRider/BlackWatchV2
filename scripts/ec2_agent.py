#!/usr/bin/env python3
"""BlackWatch EC2 reporter agent — production-grade.

Runs as a systemd service on each EC2. Every INTERVAL seconds it:
  * runs whichever collectors are *due* (each has its own cadence — fast ones
    every minute, heavy ones every 10 min),
  * reads new sshd + sudo lines from the journal,
  * builds a heartbeat + (when something changed) a state snapshot,
  * pushes ONE JSON message to SQS using the instance role,
  * spools to disk and replays if SQS is unreachable (bounded — see SPOOL_*).

Distro-portable: RPM (Amazon Linux / RHEL / Fedora / CentOS) and DPKG
(Debian / Ubuntu) are both supported for the packages collector.

Config via environment (set in the systemd unit):
    BLACKWATCH_SQS_URL    SQS queue URL                           (REQUIRED)
    AWS_REGION            queue region                            (default from IMDS)
    INTERVAL              tick seconds                            (default 60)
    SPOOL_DIR             local buffer dir                        (default /var/lib/blackwatch-agent)
    SPOOL_MAX_FILES       cap on spool file count                 (default 5000)
    SPOOL_MAX_BYTES       cap on spool total bytes                (default 100*1024*1024)
    BLACKWATCH_TAGS       k=v,k=v tags promoted onto every event  (e.g. env=prod,role=api)

Heavy-collector intervals can be overridden:
    COLLECT_PORTS_SEC, COLLECT_PROCESSES_SEC, COLLECT_DISK_SEC,
    COLLECT_USERS_SEC, COLLECT_AUTHORIZED_KEYS_SEC, COLLECT_SUDOERS_SEC,
    COLLECT_CRITICAL_FILES_SEC, COLLECT_CRON_SEC,
    COLLECT_PACKAGES_SEC, COLLECT_SYSTEMD_UNITS_SEC, COLLECT_SUID_SEC,
    COLLECT_KERNEL_MODULES_SEC

Requires: python3, boto3, journald, root (to read shadow / FIM / journal).
"""

from __future__ import annotations  # AL2's python3 is 3.7 — keeps annotations lazy.

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_VERSION = "1.5"  # FIM Part 3: auditd whodata — actor attribution on real-time events
IMDS = "http://169.254.169.254"

SQS_URL = os.environ.get("BLACKWATCH_SQS_URL", "")
INTERVAL = int(os.environ.get("INTERVAL", "60"))
SPOOL_DIR = Path(os.environ.get("SPOOL_DIR", "/var/lib/blackwatch-agent")) / "spool"
SPOOL_MAX_FILES = int(os.environ.get("SPOOL_MAX_FILES", "5000"))
SPOOL_MAX_BYTES = int(os.environ.get("SPOOL_MAX_BYTES", str(100 * 1024 * 1024)))

# FIM (File Integrity Monitoring) — periodic-baseline mode in Part 1. Part 2
# will add real-time inotify; Part 3 will add auditd whodata. All three share
# the same local SQLite baseline at /var/lib/blackwatch-agent/fim/baseline.db.
# Singleton initialized in main(); build_report() drains queued changes.
_FIM_ENGINE = None  # type: ignore[var-annotated]
FIM_SCAN_SEC = int(os.environ.get("COLLECT_FIM_SEC", str(6 * 60 * 60)))   # 6h
FIM_DISABLED = os.environ.get("BLACKWATCH_FIM_DISABLED", "").lower() in ("1", "true", "yes")

# SQS message body limit is 262_144 bytes (256 KiB). We leave headroom for the
# attributes / framing overhead and any growth from JSON-encoding strings.
SQS_BODY_MAX_BYTES = 240_000

# Allowed SQS URL pattern. If BLACKWATCH_SQS_URL doesn't match, the agent
# refuses to start — defends against a tampered systemd unit pointing at an
# attacker-controlled queue. The IAM policy already restricts SendMessage to
# our queue ARN; this catches the misconfig early instead of silently
# spooling rejected sends.
_SQS_URL_RE = re.compile(
    r"^https://sqs\.[a-z0-9-]+\.amazonaws\.com/\d{12}/[A-Za-z0-9_\-]{1,80}$"
)

# ---------- BLACKWATCH_TAGS=env=prod,role=api parsing ----------------------

def _parse_tags(s: str) -> dict:
    out: dict = {}
    for piece in (s or "").split(","):
        piece = piece.strip()
        if "=" in piece:
            k, v = piece.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                out[k] = v
    return out


TAGS = _parse_tags(os.environ.get("BLACKWATCH_TAGS", ""))

# ---------- Secret scrubbing -----------------------------------------------
#
# Process args, sudo COMMAND= lines, and journald sshd entries occasionally
# carry credentials in the clear (`mysql -ppassword`, `--token=abc`, `KEY=...`).
# We pattern-match the well-known shapes and replace the secret portion with
# `***`. The agent runs on root-trusted boxes; the goal is to keep secrets
# out of BlackWatch and onward (Slack, email, the events table) — defense
# against an *over-collection* footgun, not against an attacker on the box.

_SCRUB_PATTERNS = [
    # MySQL: `-pSECRET` or `--password=SECRET` (also `MYSQL_PWD=...`)
    (re.compile(r"(-p)([^\s]+)"), r"\1***"),
    (re.compile(r"(--password\s*=\s*|--passwd\s*=\s*|--pass\s*=\s*)\S+"), r"\1***"),
    (re.compile(r"(MYSQL_PWD\s*=\s*)\S+"), r"\1***"),
    # Postgres: `PGPASSWORD=...`
    (re.compile(r"(PGPASSWORD\s*=\s*)\S+"), r"\1***"),
    # Generic --token / --secret / --apikey / --api-key
    (re.compile(r"(--token\s*=\s*|--secret\s*=\s*|--api[-_]?key\s*=\s*|--key\s*=\s*)\S+", re.IGNORECASE), r"\1***"),
    # KEY= / SECRET= / TOKEN= when CLEARLY uppercase env-style assignments
    (re.compile(r"\b((?:[A-Z_]*)(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)(?:[A-Z_]*))\s*=\s*\S+"), r"\1=***"),
    # AWS access key id (AKIA / ASIA + 16 alnum) — always replace
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), r"\1****REDACTED****"),
    # AWS secret key shape: 40-char base64/url-safe right after the access key
    # is harder to false-positive on; only redact when adjacent to a known
    # marker like `aws_secret_access_key=...`.
    (re.compile(r"(aws_secret_access_key\s*=\s*)[A-Za-z0-9/+=]{20,}"), r"\1***"),
    # Bearer / Basic in headers
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE), r"\1***"),
]


def scrub(s: str | None) -> str | None:
    """Apply the secret-redaction patterns. None / empty stay as-is."""
    if not s:
        return s
    out = s
    for pat, repl in _SCRUB_PATTERNS:
        out = pat.sub(repl, out)
    return out


# ---------- Watchdog --------------------------------------------------------
#
# systemd's watchdog requires the unit to write WATCHDOG=1 to the notify
# socket within WatchdogSec, else systemd kills + restarts. We ping it at
# the end of each successful tick. If a collector hangs, the next ping is
# late, systemd restarts, and the collector-stall projection fires.
#
# Implementation: write "WATCHDOG=1\n" to the path in $NOTIFY_SOCKET (unix
# datagram socket). Pure stdlib — no python-systemd dependency required.

def _sd_notify(state: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return  # WatchdogSec not configured / not running under systemd
    try:
        import socket
        # Abstract namespace addresses start with '\0'.
        target = "\0" + addr[1:] if addr.startswith("@") else addr
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.sendto(state.encode("utf-8"), target)
        finally:
            s.close()
    except Exception as exc:
        # Watchdog failures must NEVER kill the agent. Worst case systemd
        # restarts us, which is exactly what watchdog is for.
        print(f"sd_notify failed: {exc}", file=sys.stderr)


# ---------- IMDS / identity (cached: never changes at runtime) -------------

_host_identity_cache: dict | None = None


def _imds_token() -> str:
    req = urllib.request.Request(
        f"{IMDS}/latest/api/token", method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read().decode()


def _imds(path: str, token: str) -> str:
    req = urllib.request.Request(f"{IMDS}{path}", headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read().decode()


def host_identity() -> dict:
    global _host_identity_cache
    if _host_identity_cache is not None:
        return _host_identity_cache
    try:
        token = _imds_token()
        doc = json.loads(_imds("/latest/dynamic/instance-identity/document", token))
        ident = {
            "instance_id": doc.get("instanceId"),
            "hostname": os.uname().nodename,
            "account": doc.get("accountId"),
            "region": doc.get("region"),
        }
    except Exception:
        ident = {
            "instance_id": os.uname().nodename, "hostname": os.uname().nodename,
            "account": None, "region": os.environ.get("AWS_REGION"),
        }
    if TAGS:
        ident["tags"] = TAGS
    _host_identity_cache = ident
    return _host_identity_cache


def uptime_seconds() -> int:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        return 0


# ---------- Distro detection (RPM vs DPKG) --------------------------------

_distro_family_cache: str | None = None


def distro_family() -> str:
    """Return 'rpm' / 'dpkg' / 'unknown'. Result is cached."""
    global _distro_family_cache
    if _distro_family_cache is not None:
        return _distro_family_cache
    fam = "unknown"
    # The /etc/os-release ID_LIKE field is the canonical signal, with fallback to
    # binary presence (some minimal containers don't ship os-release).
    try:
        if Path("/etc/os-release").is_file():
            kv = {}
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip().strip('"')
            id_str = kv.get("ID", "").lower()
            like_str = kv.get("ID_LIKE", "").lower()
            blob = f"{id_str} {like_str}"
            if any(x in blob for x in ("rhel", "fedora", "centos", "amzn", "rocky", "almalinux")):
                fam = "rpm"
            elif any(x in blob for x in ("debian", "ubuntu")):
                fam = "dpkg"
    except Exception:
        pass
    if fam == "unknown":
        if shutil.which("rpm"):
            fam = "rpm"
        elif shutil.which("dpkg-query"):
            fam = "dpkg"
    _distro_family_cache = fam
    return fam


# ---------- Journal reader (now uses @<unix-epoch> for portable --since) ---

def read_auth_events(lookback_seconds: int) -> list[str]:
    """journalctl sshd + sudo lines as JSON, over an overlapping window
    (BlackWatch dedups by journal cursor).

    --since uses the @<unix-timestamp> format because AL2's systemd 219 doesn't
    parse "YYYY-MM-DD HH:MM:SS UTC" (rejects the timezone suffix), and bare
    timestamps without a suffix are interpreted in the box's local timezone
    (which would silently drift if the box ever moves off UTC). @epoch is
    unambiguous everywhere systemd >= 210."""
    since_ts = int((datetime.now(timezone.utc)
                    - timedelta(seconds=lookback_seconds)).timestamp())
    try:
        out = subprocess.run(
            ["journalctl", "-t", "sshd", "-t", "sudo", "--since", f"@{since_ts}",
             "--output=json", "--no-pager"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            print(f"journalctl exit={out.returncode}: {out.stderr[:200]}", file=sys.stderr)
        # Scrub MESSAGE in-place so sudo COMMAND= lines don't ship secrets.
        # We touch only MESSAGE; __CURSOR / __REALTIME_TIMESTAMP stay
        # intact so the adapter's dedup keys still work.
        out_lines = []
        for ln in out.stdout.splitlines():
            if not ln.strip():
                continue
            try:
                obj = json.loads(ln)
            except (ValueError, TypeError):
                out_lines.append(ln)
                continue
            msg = obj.get("MESSAGE")
            if isinstance(msg, str):
                obj["MESSAGE"] = scrub(msg)
            elif isinstance(msg, list):
                try:
                    obj["MESSAGE"] = scrub(bytes(msg).decode("utf-8", "replace"))
                except Exception:
                    pass
            out_lines.append(json.dumps(obj, separators=(",", ":")))
        return out_lines
    except Exception as exc:
        print(f"journalctl failed: {exc}", file=sys.stderr)
        return []


# ---------- Snapshot collectors -------------------------------------------

def snapshot_ports():
    """Listening sockets with the binding process name (ss -tlnp).
    Falls back to ss -tln if -p fails (rare). Process info comes as e.g.
    `users:(("sshd",pid=1234,fd=3))` — we pluck out the comm string."""
    try:
        out = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode != 0:
        try:
            out = subprocess.run(["ss", "-tln"], capture_output=True, text=True, timeout=10)
        except Exception:
            return None
        if out.returncode != 0:
            return None
    rows = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 4:
            continue
        local = parts[3]
        port = local.rsplit(":", 1)[-1]
        addr = local.rsplit(":", 1)[0].strip("[]")
        process = None
        if len(parts) >= 6 and "users:" in parts[5]:
            # users:(("sshd",pid=1234,fd=3),...)
            try:
                # Match the first comm in quotes — robust to multi-process bindings.
                quoted = parts[5].split('"')
                if len(quoted) >= 2:
                    process = quoted[1]
            except Exception:
                pass
        rows.append({"proto": "tcp", "address": addr, "port": port, "process": process})
    return rows


def snapshot_users():
    try:
        out = subprocess.run(["getent", "passwd"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    users = []
    for line in out.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 7:
            users.append({"name": parts[0], "uid": parts[2], "shell": parts[6]})
    return users


def snapshot_authorized_keys() -> list:
    keys = []
    candidates = []
    home = Path("/home")
    if home.exists():
        candidates.extend(home.iterdir())
    if Path("/root/.ssh/authorized_keys").is_file():
        candidates.append(Path("/root"))
    for user_dir in candidates:
        ak = user_dir / ".ssh" / "authorized_keys"
        if not ak.is_file():
            continue
        try:
            content = ak.read_text(errors="ignore")
        except Exception:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fp = hashlib.sha256(line.encode()).hexdigest()[:16]
            # Extract key type (ssh-rsa / ssh-ed25519 / ecdsa-*) without the
            # key body or comment — type is useful for posture (weak algos)
            # but the body would leak partial pubkey material.
            parts = line.split(None, 2)
            key_type = parts[0] if parts and parts[0].startswith(("ssh-", "ecdsa-", "sk-")) else None
            keys.append({"user": user_dir.name, "fingerprint": fp, "type": key_type})
    return keys


def snapshot_sudoers() -> dict:
    paths = [Path("/etc/sudoers")]
    sd = Path("/etc/sudoers.d")
    if sd.is_dir():
        paths.extend(sorted(sd.iterdir()))
    out = {}
    for p in paths:
        if p.is_file():
            try:
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                pass
    return out


_CRITICAL_FILES = [
    "/etc/passwd", "/etc/group", "/etc/shadow", "/etc/gshadow",
    "/etc/ssh/sshd_config", "/etc/hosts", "/etc/resolv.conf",
    "/etc/pam.d/sshd", "/etc/pam.d/sudo", "/etc/pam.d/openvpn",
    "/etc/crontab",
]


def snapshot_critical_files() -> dict:
    out = {}
    for p in _CRITICAL_FILES:
        path = Path(p)
        if path.is_file():
            try:
                out[p] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                pass
    return out


def snapshot_cron() -> dict:
    out = {}
    candidates = [Path("/etc/crontab")]
    for d in ("/etc/cron.d", "/etc/cron.hourly", "/etc/cron.daily",
              "/etc/cron.weekly", "/etc/cron.monthly"):
        dp = Path(d)
        if dp.is_dir():
            candidates.extend(sorted(dp.iterdir()))
    spool = Path("/var/spool/cron")
    if spool.is_dir():
        try:
            candidates.extend(sorted(spool.iterdir()))
        except Exception:
            pass
    for p in candidates:
        if p.is_file():
            try:
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                pass
    return out


def snapshot_systemd_units():
    try:
        out = subprocess.run(
            ["systemctl", "list-unit-files", "--state=enabled", "--no-legend",
             "--no-pager", "--type=service,timer"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    units = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts:
            units.append(parts[0])
    return sorted(set(units))


def snapshot_suid():
    # Scope to common system paths; avoid /proc, /sys, mounted volumes.
    try:
        out = subprocess.run(
            ["find", "/usr", "/opt", "/bin", "/sbin", "-xdev",
             "-perm", "-4000", "-type", "f", "-print"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    # find prints to stderr for permission-denied subdirs but still returns
    # useful output; accept partial results (don't gate on returncode).
    return sorted(line for line in out.stdout.splitlines() if line.strip())


def snapshot_packages():
    """Distro-portable. rpm -qa on RHEL family, dpkg-query on Debian family."""
    fam = distro_family()
    if fam == "rpm":
        try:
            out = subprocess.run(
                ["rpm", "-qa", "--queryformat", "%{NAME}\n"],
                capture_output=True, text=True, timeout=20,
            )
        except Exception:
            return None
        # Gate on returncode AND non-empty output — catches the BDB-corruption case
        # (rpm errors to stderr, exits non-zero, may produce empty stdout) so we
        # don't ship a misleading "no packages" snapshot.
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return sorted({line.strip() for line in out.stdout.splitlines() if line.strip()})
    elif fam == "dpkg":
        try:
            out = subprocess.run(
                ["dpkg-query", "-W", "-f=${Package}\n"],
                capture_output=True, text=True, timeout=20,
            )
        except Exception:
            return None
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return sorted({line.strip() for line in out.stdout.splitlines() if line.strip()})
    return None


def snapshot_processes():
    """Visibility-only — kernel threads excluded, args truncated."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "user,pid,comm,args"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    lines = out.stdout.splitlines()
    if lines and lines[0].lstrip().upper().startswith("USER"):
        lines = lines[1:]
    procs = []
    for line in lines:
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        user, pid, comm = parts[0], parts[1], parts[2]
        args = parts[3] if len(parts) > 3 else comm
        a = args.strip()
        if (comm.startswith("[") and comm.endswith("]")) or \
           (a.startswith("[") and a.endswith("]")):
            continue   # kernel thread
        # Scrub before truncating — scrubbing replaces known-bad fragments
        # with `***` which doesn't change length much, but doing it after
        # truncation could leave a half-hidden secret (e.g. "-ppassword12"
        # truncated to "-pp" then scrub no-ops).
        procs.append({
            "user": user, "pid": pid, "comm": comm,
            "args": (scrub(args) or "")[:240],
        })
    return procs or None


def snapshot_disk():
    """Per-mount fill levels via `df -P` — POSIX format keeps the columns sane.
    Skips tmpfs/devtmpfs/overlay (containers' fake mounts)."""
    try:
        out = subprocess.run(["df", "-P", "-T"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    rows = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        fs_type = parts[1]
        if fs_type in ("tmpfs", "devtmpfs", "overlay", "squashfs", "aufs", "ramfs"):
            continue
        try:
            total = int(parts[2])
            used = int(parts[3])
            mount = parts[6]
            used_pct = int(round(used * 100 / total)) if total > 0 else 0
            rows.append({"mount": mount, "fs_type": fs_type, "total": total,
                         "used": used, "used_pct": used_pct})
        except (ValueError, ZeroDivisionError):
            continue
    return rows or None


def snapshot_kernel_modules():
    """Loaded kernel modules (`lsmod`). Sorted list of module names — diff
    catches both legit module loads on package install AND rootkit primitives."""
    try:
        out = subprocess.run(["lsmod"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    mods = []
    for line in out.stdout.splitlines()[1:]:  # header
        parts = line.split()
        if parts:
            mods.append(parts[0])
    return sorted(set(mods)) or None


# ---------- Lightweight always-on metrics + health checks --------------------
#
# These all run EVERY tick (cheap: /proc reads + one subprocess each). They
# are *not* in the Collector machinery because their values change every tick
# (so they wouldn't affect the snapshot change-hash anyway) and because the
# projection needs them on every heartbeat to do baseline tracking + transition
# detection. They live on the heartbeat itself.

def snapshot_memory():
    """Current memory usage. Cheap — /proc/meminfo read only."""
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            try:
                info[k.strip()] = int(v.strip().split()[0])  # kB
            except ValueError:
                pass
    except Exception:
        return None
    total = info.get("MemTotal", 0)
    if total <= 0:
        return None
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = total - avail
    return {
        "total_kb": total,
        "available_kb": avail,
        "used_kb": used,
        "used_pct": int(round(used * 100 / total)),
    }


def snapshot_cpu():
    """1/5/15-min load average + CPU count, plus load normalized by CPU count
    (1.0 = fully utilized; >1.0 = oversubscribed). Cheap — two /proc reads."""
    try:
        parts = Path("/proc/loadavg").read_text().strip().split()
        load_1, load_5, load_15 = float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return None
    try:
        cpu_count = sum(
            1 for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("processor")
        ) or 1
    except Exception:
        cpu_count = 1
    return {
        "load_1min": load_1, "load_5min": load_5, "load_15min": load_15,
        "cpu_count": cpu_count,
        "load_norm_1min": round(load_1 / cpu_count, 3),
        "load_norm_5min": round(load_5 / cpu_count, 3),
    }


def snapshot_active_sessions():
    """Currently logged-in interactive sessions via `who(1)`. Source IP is
    extracted from the trailing `(...)` for SSH-originated logins.

    Tries `who --ips` first (coreutils 8.16+ — bypasses sshd's reverse-DNS
    `UseDNS=yes` and gives us the raw IP) and falls back to plain `who` for
    boxes where `--ips` isn't supported. Without `--ips` you often see a
    hostname like `76-231-24-13.lightspeed.sntcca.sbcglobal.net` instead of
    the IP, which is less useful for correlation.

    Lightweight; usually 0–5 entries on a typical box."""
    out = None
    for args in (["who", "--ips"], ["who"]):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                out = r
                break
        except Exception:
            continue
    if out is None:
        return []
    sessions = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        user, tty = parts[0], parts[1]
        src = None
        if "(" in line and ")" in line:
            # `who` style: "ec2-user pts/0 2026-06-05 12:00 (203.0.113.5)"
            candidate = line[line.rfind("(") + 1: line.rfind(")")]
            if candidate and candidate not in (":0", "tmux", "screen"):
                src = candidate
        elif len(parts) >= 5:
            # `who --ips` style: trailing token is the raw IP, no parens.
            tail = parts[-1]
            # An IPv4/IPv6 token won't have ':' that looks like time (HH:MM has
            # exactly one colon; IPv6 has ≥2; IPv4 has none). And rules out
            # `:0` / `tmux` / `screen`.
            if (tail not in (":0", "tmux", "screen")
                    and (tail.count(":") != 1)
                    and any(ch.isdigit() for ch in tail)):
                src = tail
        # Trim the source out of the login-time display so it doesn't appear twice.
        login_tokens = parts[2:5]
        if login_tokens and login_tokens[-1].startswith("("):
            login_tokens = login_tokens[:-1]
        login_time = " ".join(login_tokens).strip()
        sessions.append({
            "user": user, "tty": tty, "login": login_time, "source": src,
        })
    return sessions


def detect_oom_events(lookback_seconds: int) -> list[dict]:
    """Recent OOM-killer activity from the kernel ring buffer (journalctl -k).
    Each match becomes one host.oom_kill event downstream; cursor-based dedup
    means re-reads of overlapping windows don't duplicate."""
    since_ts = int((datetime.now(timezone.utc)
                    - timedelta(seconds=lookback_seconds)).timestamp())
    try:
        out = subprocess.run(
            ["journalctl", "-k", "--since", f"@{since_ts}",
             "--output=json", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return []
    if out.returncode != 0:
        return []
    events: list[dict] = []
    for line in out.stdout.splitlines():
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        msg = entry.get("MESSAGE", "")
        if isinstance(msg, list):
            try:
                msg = bytes(msg).decode("utf-8", "replace")
            except Exception:
                continue
        low = (msg or "").lower()
        # The three canonical patterns the kernel uses for OOM-related events.
        if not ("oom-kill" in low or "out of memory" in low
                or low.startswith("killed process") or " killed process " in low):
            continue
        events.append({
            "cursor": entry.get("__CURSOR"),
            "ts": entry.get("__REALTIME_TIMESTAMP"),
            "message": (msg or "")[:240],
        })
    return events


def detect_rpm_db_corruption() -> dict | None:
    """rpm's BerkeleyDB era left lock files (`__db.001` etc.) when processes
    die mid-transaction. Their presence WITHOUT a live rpm/yum/dnf process
    means the DB is stuck — every subsequent rpm call will fail until rebuilt.
    Returns None when healthy, a small dict when stuck."""
    if distro_family() != "rpm":
        return None
    db_dir = Path("/var/lib/rpm")
    if not db_dir.is_dir():
        return None
    lock_files = sorted(str(p) for p in db_dir.glob("__db.*"))
    if not lock_files:
        return None
    # If rpm/yum/dnf is currently doing something, the locks are legitimate.
    try:
        ps = subprocess.run(
            ["pgrep", "-f", r"(^|/)(rpm|yum|dnf)( |$)"],
            capture_output=True, text=True, timeout=5,
        )
        if ps.returncode == 0 and ps.stdout.strip():
            return None
    except Exception:
        pass
    return {"lock_files": lock_files, "lock_count": len(lock_files)}


# ---------- Staggered collector runner -------------------------------------
#
# Each collector has its own cadence. Heavy ones (SUID find, package query,
# kernel modules) run every 10 min by default. FIM-relevant collectors stay
# tight (every 2 min). Fast ones every minute. All overridable via env.
# `diffable=False` excludes processes from the change-hash so a busy process
# table doesn't force the snapshot to ship on every tick.

class Collector:
    __slots__ = ("name", "fn", "interval", "diffable",
                 "next_run", "value", "error", "last_success_at")

    def __init__(self, name: str, fn, interval: int, diffable: bool = True):
        self.name = name
        self.fn = fn
        self.interval = interval
        self.diffable = diffable
        self.next_run = 0.0     # epoch seconds — 0 = always run on first tick
        self.value = None
        self.error: str | None = None
        self.last_success_at = 0.0  # epoch seconds of last successful collection

    def maybe_run(self, now: float) -> None:
        if now < self.next_run:
            return
        try:
            new_value = self.fn()
            if new_value is not None:
                # Success — refresh cached value, clear any stale error, mark time.
                self.value = new_value
                self.error = None
                self.last_success_at = now
            else:
                # Collector explicitly returned None this tick. Always record
                # the failure (don't gate on "have we ever succeeded?") so a
                # collector that worked once and is now broken still surfaces
                # in the UI. The cached value (if any) is left in place so the
                # snapshot UI doesn't suddenly go empty on a transient failure.
                self.error = "returned None"
        except Exception as exc:
            self.error = str(exc)[:160]
        self.next_run = now + self.interval

    def is_stalled(self, now: float) -> bool:
        """A collector is 'stalled' when it has succeeded before but not within
        3× its interval. Never-tried-yet (last_success_at == 0) is NOT stalled —
        that's just agent startup. This lets the projection emit a clean
        host.collector.stalled event the first time a collector breaks, instead
        of waiting for someone to notice 'why is `packages` showing 0?'."""
        if self.last_success_at == 0:
            return False
        return (now - self.last_success_at) > (3 * self.interval)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


COLLECTORS: list[Collector] = [
    # Fast — every minute.
    Collector("ports",           snapshot_ports,           _env_int("COLLECT_PORTS_SEC", 60)),
    Collector("processes",       snapshot_processes,       _env_int("COLLECT_PROCESSES_SEC", 60), diffable=False),
    Collector("disk",            snapshot_disk,            _env_int("COLLECT_DISK_SEC", 60)),
    # FIM-tier — every 2 min. Sudoers / SSHD config / cron changes are
    # security-relevant; faster detection is worth the extra hashing cost.
    Collector("users",           snapshot_users,           _env_int("COLLECT_USERS_SEC", 120)),
    Collector("authorized_keys", snapshot_authorized_keys, _env_int("COLLECT_AUTHORIZED_KEYS_SEC", 120)),
    Collector("sudoers",         snapshot_sudoers,         _env_int("COLLECT_SUDOERS_SEC", 120)),
    Collector("critical_files",  snapshot_critical_files,  _env_int("COLLECT_CRITICAL_FILES_SEC", 120)),
    Collector("cron",            snapshot_cron,            _env_int("COLLECT_CRON_SEC", 120)),
    # Heavy — every 10 min. SUID find is I/O-heavy; package queries can hit
    # rpm DB lock contention; kernel modules are stable.
    Collector("packages",        snapshot_packages,        _env_int("COLLECT_PACKAGES_SEC", 600)),
    Collector("systemd_units",   snapshot_systemd_units,   _env_int("COLLECT_SYSTEMD_UNITS_SEC", 600)),
    Collector("suid",            snapshot_suid,            _env_int("COLLECT_SUID_SEC", 600)),
    Collector("kernel_modules",  snapshot_kernel_modules,  _env_int("COLLECT_KERNEL_MODULES_SEC", 600)),
]


def run_due_collectors(now: float) -> None:
    for c in COLLECTORS:
        c.maybe_run(now)


def build_snapshots_and_hash() -> tuple[dict, str]:
    """Build the current snapshots payload. The hash covers only collectors
    marked `diffable=True` — processes are visibility-only and would otherwise
    force the snapshot to ship every tick."""
    snapshots: dict = {}
    hash_blob: dict = {}
    for c in COLLECTORS:
        if c.value is None:
            continue
        snapshots[c.name] = c.value
        if c.diffable:
            hash_blob[c.name] = c.value
    snap_hash = hashlib.sha256(json.dumps(hash_blob, sort_keys=True).encode()).hexdigest()
    return snapshots, snap_hash


def collector_errors() -> dict:
    return {c.name: c.error for c in COLLECTORS if c.error}


def stalled_collectors(now: float) -> list[str]:
    return [c.name for c in COLLECTORS if c.is_stalled(now)]


# ---------- Report assembly + smart-ship -----------------------------------

_last_snapshot_hash: str | None = None
_last_full_send_at: float = 0.0
_FULL_RESYNC_SECONDS = 3600


def build_report() -> dict:
    """One tick. Returns a JSON-serializable dict to ship to SQS."""
    global _last_snapshot_hash, _last_full_send_at

    tick_start = time.perf_counter()
    now = time.time()
    run_due_collectors(now)
    snapshots, snap_hash = build_snapshots_and_hash()

    include_snaps = (
        snap_hash != _last_snapshot_hash
        or (now - _last_full_send_at) > _FULL_RESYNC_SECONDS
    )

    report: dict = {
        "kind": "ec2_report",
        "host": host_identity(),
        "agent_version": AGENT_VERSION,
        "uptime_seconds": uptime_seconds(),
        "auth_events": read_auth_events(INTERVAL + 120),
        # v1.1: always-on light metrics + health checks. Projection compares
        # against rolling baseline / previous state to decide transitions.
        "memory": snapshot_memory(),
        "cpu": snapshot_cpu(),
        "active_sessions": snapshot_active_sessions(),
        "rpm_db_corrupted": detect_rpm_db_corruption(),
        "stalled_collectors": stalled_collectors(now),
        "oom_events": detect_oom_events(INTERVAL + 120),
    }
    if include_snaps and snapshots:
        report["snapshots"] = snapshots
        _last_snapshot_hash = snap_hash
        if (now - _last_full_send_at) > _FULL_RESYNC_SECONDS:
            _last_full_send_at = now

    # FIM Part 1: drain any baseline-scan-detected changes since last tick.
    # The scanner thread queues changes asynchronously; we ship whatever is
    # pending. Coverage rides on every tick so the UI never goes "no data".
    if _FIM_ENGINE is not None:
        fim_changes = _FIM_ENGINE.drain_changes()
        if fim_changes:
            report["fim_changes"] = fim_changes
        report["fim_coverage"] = _FIM_ENGINE.coverage()

    errs = collector_errors()
    if errs:
        report["collector_errors"] = errs

    report["tick_duration_ms"] = int((time.perf_counter() - tick_start) * 1000)
    return report


# ---------- SQS send + bounded disk spool ----------------------------------

def _sqs():
    import boto3
    region = os.environ.get("AWS_REGION") or host_identity().get("region")
    return boto3.client("sqs", region_name=region)


def _spool(payload: dict) -> None:
    # Make sure the spool directory exists AND is private. The parent
    # /var/lib/blackwatch-agent and its `spool/` sub both get 0700 so
    # journal content and process args aren't readable by non-root users
    # who happen to land on the box.
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SPOOL_DIR.parent, 0o700)
        os.chmod(SPOOL_DIR, 0o700)
    except Exception:
        pass
    path = SPOOL_DIR / f"{int(time.time() * 1000)}.json"
    # umask-independent write: open file with explicit 0600.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload))
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    _enforce_spool_caps()


def _enforce_spool_caps() -> None:
    """Drop oldest spool files when over the configured caps. A box that loses
    SQS connectivity for days must NEVER fill /var — silent monitoring loss is
    bad, full-disk incident is worse."""
    try:
        files = sorted(SPOOL_DIR.glob("*.json"))
        if len(files) > SPOOL_MAX_FILES:
            for f in files[: len(files) - SPOOL_MAX_FILES]:
                try:
                    f.unlink()
                except Exception:
                    pass
            files = sorted(SPOOL_DIR.glob("*.json"))
        total = 0
        for f in reversed(files):  # newest first; drop oldest until under cap
            try:
                total += f.stat().st_size
            except Exception:
                continue
        if total > SPOOL_MAX_BYTES:
            running = 0
            for f in reversed(files):
                try:
                    running += f.stat().st_size
                except Exception:
                    continue
                if running > SPOOL_MAX_BYTES:
                    try:
                        f.unlink()
                    except Exception:
                        pass
    except Exception as exc:
        print(f"spool cap enforcement failed: {exc}", file=sys.stderr)


def _flush_spool(client) -> None:
    if not SPOOL_DIR.exists():
        return
    for f in sorted(SPOOL_DIR.glob("*.json")):
        try:
            client.send_message(QueueUrl=SQS_URL, MessageBody=f.read_text())
            f.unlink()
        except Exception:
            return  # still unreachable; keep the rest for later


def _shrink_for_sqs(payload: dict, max_bytes: int = SQS_BODY_MAX_BYTES) -> dict:
    """If the serialized payload would exceed SQS's 256 KiB limit, drop the
    biggest dispensable fields (in decreasing-cost order) until it fits. We
    keep the heartbeat shape intact — auth_events, OOM events, and the host
    identity always ship. The first thing to go is the optional snapshots
    dict; then we trim oversized lists in it.

    The point is to NEVER let an over-sized box silently fail to report.
    The truncation is annotated in `payload.truncated` so the adapter / UI
    can show 'snapshots dropped' instead of pretending everything is fine.
    """
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload

    truncated: list[str] = []
    # 1. The hottest field by size on most boxes is `snapshots.suid`
    #    (find -perm -4000 on a box with many packages installed).
    snaps = payload.get("snapshots")
    if isinstance(snaps, dict):
        for cand in ("suid", "systemd_units", "packages", "kernel_modules", "cron"):
            if cand in snaps:
                snaps.pop(cand, None)
                truncated.append(f"snapshots.{cand}")
                if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
                    payload["truncated"] = truncated
                    return payload

    # 2. processes is large + visibility-only — drop next.
    if isinstance(snaps, dict) and "processes" in snaps:
        snaps.pop("processes", None)
        truncated.append("snapshots.processes")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            payload["truncated"] = truncated
            return payload

    # 3. Drop the whole snapshots block.
    if "snapshots" in payload:
        payload.pop("snapshots")
        truncated.append("snapshots")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            payload["truncated"] = truncated
            return payload

    # 4. FIM Part 1: if a baseline scan picked up a huge wave of changes (e.g.
    # post-yum-update touching 500 binaries), the change list might be the
    # biggest thing left. Halve it iteratively; each batch becomes its own
    # tick on the next pass. The local SQLite baseline still has the after-
    # state, so a dropped change won't re-fire next scan.
    fim_changes = payload.get("fim_changes")
    if isinstance(fim_changes, list) and len(fim_changes) > 0:
        # Halve until it fits or we hit 1.
        while fim_changes and \
                len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > max_bytes:
            half = max(1, len(fim_changes) // 2)
            fim_changes[:] = fim_changes[:half]
            payload["fim_changes"] = fim_changes
        truncated.append(f"fim_changes(kept={len(fim_changes)})")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            payload["truncated"] = truncated
            return payload

    # 5. Drop auth_events (last resort — we lose authn signal but keep the
    # heartbeat alive). Followers replay would re-fetch on next tick.
    if "auth_events" in payload:
        payload.pop("auth_events")
        truncated.append("auth_events")

    payload["truncated"] = truncated
    return payload


# Consecutive send failures, capped backoff. Reset on first success.
_send_failures = 0
_BACKOFF_MAX_SECS = 300


def send(payload: dict) -> None:
    """Push one payload to SQS. On failure: spool, count, back off.

    Backoff: failures 1-3 = no extra sleep (transient), 4-6 = 30s, 7-9 = 60s,
    capped at 5 min. Without this a permanently-broken URL (or revoked IAM)
    causes the agent to burn the spool's 5000-file cap inside a couple hours.
    """
    global _send_failures

    payload = _shrink_for_sqs(payload)

    try:
        client = _sqs()
        _flush_spool(client)
        client.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(payload))
        _send_failures = 0
        mem = payload.get("memory") or {}
        cpu = payload.get("cpu") or {}
        flags = []
        if payload.get("oom_events"): flags.append(f"oom={len(payload['oom_events'])}")
        if payload.get("rpm_db_corrupted"): flags.append("rpmdb=BAD")
        if payload.get("stalled_collectors"): flags.append("stalled=" + ",".join(payload["stalled_collectors"]))
        if payload.get("collector_errors"): flags.append("errs=" + ",".join(payload["collector_errors"]))
        if payload.get("truncated"): flags.append("trunc=" + ",".join(payload["truncated"]))
        print(f"reported instance={payload['host'].get('instance_id')} "
              f"auth_lines={len(payload.get('auth_events') or [])} "
              f"snaps={'yes' if 'snapshots' in payload else 'no'} "
              f"tick_ms={payload.get('tick_duration_ms')} "
              f"mem={mem.get('used_pct')}% load={cpu.get('load_norm_1min')} "
              f"sess={len(payload.get('active_sessions') or [])}"
              f"{' ' + ' '.join(flags) if flags else ''}")
    except Exception as exc:
        _send_failures += 1
        print(f"send failed (#{_send_failures}), spooling: {exc}", file=sys.stderr)
        try:
            _spool(payload)
        except Exception as spool_exc:
            print(f"spool also failed: {spool_exc}", file=sys.stderr)
        if _send_failures >= 4:
            backoff = min(_BACKOFF_MAX_SECS, 30 * ((_send_failures - 3 + 2) // 3))
            print(f"backing off {backoff}s after {_send_failures} failures", file=sys.stderr)
            time.sleep(backoff)


def main() -> None:
    if not SQS_URL:
        print("ERROR: set BLACKWATCH_SQS_URL", file=sys.stderr)
        sys.exit(2)
    # Fail fast on tampered / typo'd URL. The IAM policy is the real control
    # (sqs:SendMessage scoped to one queue ARN), but rejecting an obviously
    # bogus URL here is cheap and surfaces operator error immediately.
    if not _SQS_URL_RE.match(SQS_URL):
        print(
            f"ERROR: BLACKWATCH_SQS_URL doesn't look like a valid SQS URL: {SQS_URL}\n"
            "       expected https://sqs.<region>.amazonaws.com/<account>/<queue-name>",
            file=sys.stderr,
        )
        sys.exit(2)

    once = "--once" in sys.argv
    print(f"BlackWatch EC2 agent v{AGENT_VERSION} -> {SQS_URL} (every {INTERVAL}s)")
    print(f"  distro={distro_family()} tags={TAGS or '-'}")

    # FIM Part 1: kick off the periodic-baseline scanner. The thread starts
    # its first scan 15s after engine start, then every COLLECT_FIM_SEC.
    # BLACKWATCH_FIM_DISABLED=1 is a kill switch for boxes where the scan
    # cost isn't acceptable yet. Import here so the agent still works if
    # someone copies it without fim_engine.py (rare but possible).
    if not FIM_DISABLED:
        try:
            global _FIM_ENGINE
            from fim_engine import FimEngine  # type: ignore[import-not-found]
            _FIM_ENGINE = FimEngine(scan_interval_sec=FIM_SCAN_SEC)
            _FIM_ENGINE.start()
            print(f"  fim=enabled scan_every={FIM_SCAN_SEC}s "
                  f"paths_configured={_FIM_ENGINE.coverage()['paths_configured']}")
        except Exception as exc:
            print(f"  fim=startup_failed reason={exc!r}", file=sys.stderr)
            _FIM_ENGINE = None
    else:
        print("  fim=disabled (BLACKWATCH_FIM_DISABLED set)")

    # Tell systemd we're alive (no-op outside systemd / outside Type=notify).
    _sd_notify("READY=1")
    while True:
        send(build_report())
        # Ping the watchdog. If WatchdogSec is set, systemd kills+restarts us
        # when we miss this. Successful send → fresh ping; failed send still
        # pings because we're functioning, just temporarily blocked.
        _sd_notify("WATCHDOG=1")
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
