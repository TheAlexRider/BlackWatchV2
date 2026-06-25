#!/usr/bin/env python3
"""BlackWatch OpenVPN agent — push, not pull.

Runs as a systemd service ON the OpenVPN box, alongside (but independent of)
the EC2 host agent. Two threads:

  1. Heartbeat (every INTERVAL seconds):
       * `systemctl is-active <unit>` for the service state,
       * verbatim status.log (root-owned; we run as root),
       * recent AUTH_FAILED / "authentication succeeded" lines (overlap window,
         a safety net in case the follower briefly missed something),
       * pushed as one `vpn_report` SQS message.
  2. Follower (long-running `journalctl -fu <unit>`):
       * batches matched auth lines (≤BATCH_MAX lines OR BATCH_WINDOW seconds),
       * pushes each batch as a `vpn_auth_realtime` SQS message —
         sub-second alert latency without polling.

Persists the last shipped __CURSOR so a restart resumes exactly where it left
off (no replays, no gaps). Spools to disk and replays if SQS is unreachable.

Replaces the SSH-pull `openvpn_ssh` connector. BlackWatch's existing SQS
connector (target_module=vpn.openvpn) drains both message kinds; the
VpnOpenVpnAdapter is shape-tolerant — fields present produce events, fields
absent produce nothing.

Config via environment (set in the systemd unit):
    BLACKWATCH_VPN_SQS_URL  SQS queue URL                         (REQUIRED)
    AWS_REGION              queue region                          (default from IMDS)
    INTERVAL                heartbeat seconds                     (default 60)
    OPENVPN_UNIT            systemd unit name                     (default openvpn-server@server)
    OPENVPN_STATUS_FILE     status.log path                       (default /var/log/openvpn/status.log)
    SERVER_NAME             logical server id BlackWatch shows    (default "openvpn")
    SPOOL_DIR               local buffer dir                      (default /var/lib/blackwatch-vpn-agent)
    FOLLOWER_ENABLED        "1"/"0" — disable the realtime tail   (default 1)
    FOLLOWER_BATCH_MAX      max lines per batch                   (default 10)
    FOLLOWER_BATCH_WINDOW   max seconds before flushing           (default 1.0)

Requires: python3, boto3, journald, root (to read status.log + journal).
"""

from __future__ import annotations  # AL2's python3 is 3.7 — keeps annotations lazy.

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_VERSION = "0.6"  # hardened: scrubbing, sandbox, watchdog, size caps, send backoff, spool bounds
IMDS = "http://169.254.169.254"

SQS_URL = os.environ.get("BLACKWATCH_VPN_SQS_URL", "")
INTERVAL = int(os.environ.get("INTERVAL", "60"))
UNIT = os.environ.get("OPENVPN_UNIT", "openvpn-server@server")
STATUS_FILE = os.environ.get("OPENVPN_STATUS_FILE", "/var/log/openvpn/status.log")
SERVER_NAME = os.environ.get("SERVER_NAME", "openvpn")
BASE_DIR = Path(os.environ.get("SPOOL_DIR", "/var/lib/blackwatch-vpn-agent"))
SPOOL_DIR = BASE_DIR / "spool"
CURSOR_FILE = BASE_DIR / "journal_cursor"
FOLLOWER_ENABLED = os.environ.get("FOLLOWER_ENABLED", "1") != "0"
FOLLOWER_BATCH_MAX = int(os.environ.get("FOLLOWER_BATCH_MAX", "10"))
FOLLOWER_BATCH_WINDOW = float(os.environ.get("FOLLOWER_BATCH_WINDOW", "1.0"))
FOLLOWER_RESTART_BACKOFF = 5.0  # seconds between journalctl restarts on EOF/error

# Spool caps. A box that loses SQS for days must NEVER fill /var — silent
# monitoring loss is bad, full-disk outage is worse.
SPOOL_MAX_FILES = int(os.environ.get("SPOOL_MAX_FILES", "5000"))
SPOOL_MAX_BYTES = int(os.environ.get("SPOOL_MAX_BYTES", str(100 * 1024 * 1024)))

# SQS body limit is 262_144 bytes; leave headroom for framing + JSON escaping.
SQS_BODY_MAX_BYTES = 240_000

# Allowed SQS URL pattern. If BLACKWATCH_VPN_SQS_URL doesn't match, the agent
# refuses to start — defends against a tampered systemd unit pointing at an
# attacker-controlled queue. The IAM policy is the real defense; this catches
# the misconfig in seconds instead of silently spooling rejected sends.
_SQS_URL_RE = re.compile(
    r"^https://sqs\.[a-z0-9-]+\.amazonaws\.com/\d{12}/[A-Za-z0-9_\-]{1,80}$"
)


# ---------- Secret scrubbing -----------------------------------------------
#
# OpenVPN's PAM plugin never writes passwords in clear, but the journal
# MESSAGE field can carry user-controlled tokens (TOTP codes, client
# identifiers). We apply the same scrubber the EC2 agent uses so any
# accidental secret in a journal line is redacted before it leaves the box.

_SCRUB_PATTERNS = [
    (re.compile(r"(-p)([^\s]+)"), r"\1***"),
    (re.compile(r"(--password\s*=\s*|--passwd\s*=\s*|--pass\s*=\s*)\S+"), r"\1***"),
    (re.compile(r"(--token\s*=\s*|--secret\s*=\s*|--api[-_]?key\s*=\s*|--key\s*=\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"\b((?:[A-Z_]*)(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)(?:[A-Z_]*))\s*=\s*\S+"), r"\1=***"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), r"\1****REDACTED****"),
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE), r"\1***"),
]


def scrub(s: str | None) -> str | None:
    if not s:
        return s
    out = s
    for pat, repl in _SCRUB_PATTERNS:
        out = pat.sub(repl, out)
    return out


def scrub_auth_line(raw_line: str) -> str:
    """Apply the scrubber to the MESSAGE field of a journalctl-json line.
    Preserves __CURSOR / __REALTIME_TIMESTAMP so downstream dedup still works.
    Bad JSON passes through unchanged."""
    try:
        obj = json.loads(raw_line)
    except (ValueError, TypeError):
        return raw_line
    msg = obj.get("MESSAGE")
    if isinstance(msg, str):
        obj["MESSAGE"] = scrub(msg)
    elif isinstance(msg, list):
        try:
            obj["MESSAGE"] = scrub(bytes(msg).decode("utf-8", "replace"))
        except Exception:
            pass
    return json.dumps(obj, separators=(",", ":"))


# ---------- Watchdog --------------------------------------------------------
#
# systemd `WatchdogSec` requires the unit to write `WATCHDOG=1` to the
# notify socket within the interval, else the agent gets SIGKILL'd and
# restarted. We ping after every successful heartbeat tick. If a tick hangs
# for 3 min, systemd restarts and the resulting gap surfaces as a
# vpn.service.down transition in BlackWatch.

def _sd_notify(state: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return  # not running under systemd notify
    try:
        import socket
        target = "\0" + addr[1:] if addr.startswith("@") else addr
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.sendto(state.encode("utf-8"), target)
        finally:
            s.close()
    except Exception as exc:
        print(f"sd_notify failed: {exc}", file=sys.stderr)

# Cert inventory paths. There are TWO places certs / CRL can live:
#
#   PKI dir         — easy-rsa's source of truth. CA cert, every issued cert,
#                     revoked certs, the master CRL. Renewals happen here.
#   Live dir        — what OpenVPN actually reads on startup. The server cert
#                     and CRL get copied here from the PKI. If they're stale
#                     (operator renewed in PKI but forgot to copy), OpenVPN is
#                     enforcing yesterday's state — and that's a real outage
#                     waiting to happen. We monitor both so the mismatch shows.
OPENVPN_PKI_DIR = Path(os.environ.get(
    "OPENVPN_PKI_DIR", "/etc/openvpn/easy-rsa/pki"))
OPENVPN_LIVE_DIR = Path(os.environ.get(
    "OPENVPN_LIVE_DIR", "/etc/openvpn/server"))

# Only these two journal substrings warrant shipping. Anything else is chatter.
_AUTH_NEEDLES = ("AUTH_FAILED", "authentication succeeded")


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


_host_identity_cache: dict | None = None


def host_identity() -> dict:
    """Cached because IMDS calls aren't free and identity doesn't change at runtime."""
    global _host_identity_cache
    if _host_identity_cache is not None:
        return _host_identity_cache
    try:
        token = _imds_token()
        doc = json.loads(_imds("/latest/dynamic/instance-identity/document", token))
        _host_identity_cache = {
            "instance_id": doc.get("instanceId"),
            "hostname": os.uname().nodename,
            "account": doc.get("accountId"),
            "region": doc.get("region"),
        }
    except Exception:
        _host_identity_cache = {
            "instance_id": os.uname().nodename, "hostname": os.uname().nodename,
            "account": None, "region": os.environ.get("AWS_REGION"),
        }
    return _host_identity_cache


def uptime_seconds() -> int:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        return 0


def systemctl_state() -> str:
    """Return systemctl is-active output ("active" / "inactive" / "failed" / "unknown").
    Note: `is-active` exits non-zero when the service isn't active — that's
    normal; we still want stdout."""
    try:
        out = subprocess.run(
            ["systemctl", "is-active", UNIT],
            capture_output=True, text=True, timeout=10,
        )
        state = (out.stdout or "").strip()
        return state or "unknown"
    except Exception:
        return "unknown"


def read_status_file() -> str | None:
    """Verbatim contents of the OpenVPN status file (the adapter parses it)."""
    try:
        return Path(STATUS_FILE).read_text(errors="ignore")
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"status read failed: {exc}", file=sys.stderr)
        return None


def read_auth_lines(lookback_seconds: int) -> list[str]:
    """Heartbeat-only safety net: ship recent matched auth lines on each tick.
    The follower already gets these in real time; heartbeat re-ships them with
    an overlapping window so we self-heal if the follower thread is briefly
    down. Downstream dedups by deterministic event_id (journal cursor).

    --since uses @<unix-timestamp> — AL2's systemd 219 doesn't parse the "UTC"
    suffix, and bare timestamps are interpreted in the box's local timezone
    (fragile if it ever moves off UTC). @epoch is unambiguous."""
    since_ts = int((datetime.now(timezone.utc)
                    - timedelta(seconds=lookback_seconds)).timestamp())
    cmd = (
        f"journalctl -u {UNIT} --since @{since_ts} --output=json --no-pager "
        f"| grep -E 'AUTH_FAILED|authentication succeeded' || true"
    )
    try:
        out = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, timeout=20,
        )
        # Scrub the MESSAGE field in every matched JSON line so any accidental
        # token / password fragment is redacted before leaving the box.
        return [scrub_auth_line(ln) for ln in out.stdout.splitlines() if ln.strip()]
    except Exception as exc:
        print(f"heartbeat journalctl failed: {exc}", file=sys.stderr)
        return []


# ---------- Cert inventory --------------------------------------------------
#
# Reads the OpenVPN PKI directory once per heartbeat. Uses `openssl` (already
# on the box — that's how easy-rsa works) so this agent stays a pure-Python
# script with no third-party deps. Each cert / CRL becomes one dict that the
# BlackWatch adapter on the other side knows how to render.

_OPENSSL_TS_FORMATS = ("%b %d %H:%M:%S %Y %Z", "%b %d %H:%M:%S %Y")


def _parse_openssl_ts(value: str) -> datetime | None:
    value = value.strip()
    for fmt in _OPENSSL_TS_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _days_until(when: datetime | None) -> float | None:
    if when is None:
        return None
    return round((when - datetime.now(timezone.utc)).total_seconds() / 86400, 1)


def _read_cert_file(path: Path, kind: str) -> dict | None:
    """Run `openssl x509 -enddate -subject` against one cert. Returns a dict
    ready to ship in the heartbeat. Errors are captured into the dict — they
    never raise (one bad cert mustn't kill the whole snapshot)."""
    base = {"kind": kind, "name": path.stem, "path": str(path)}
    try:
        out = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-subject", "-issuer", "-in", str(path)],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except subprocess.CalledProcessError as exc:
        return {**base, "error": (exc.stderr or "openssl failed").strip()}
    except Exception as exc:
        return {**base, "error": f"{type(exc).__name__}: {exc}"}

    subject = issuer = None
    not_after = None
    for line in out.stdout.splitlines():
        if line.startswith("notAfter="):
            not_after = _parse_openssl_ts(line.split("=", 1)[1])
        elif line.startswith("subject="):
            subject = line.split("=", 1)[1].strip()
        elif line.startswith("issuer="):
            issuer = line.split("=", 1)[1].strip()

    return {
        **base,
        "subject": subject,
        "issuer": issuer,
        "not_after": not_after.isoformat() if not_after else None,
        "days_remaining": _days_until(not_after),
    }


def _read_crl_file(path: Path) -> dict | None:
    base = {"kind": "crl", "name": path.stem, "path": str(path)}
    try:
        out = subprocess.run(
            ["openssl", "crl", "-noout", "-lastupdate", "-nextupdate", "-in", str(path)],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except subprocess.CalledProcessError as exc:
        return {**base, "error": (exc.stderr or "openssl failed").strip()}
    except Exception as exc:
        return {**base, "error": f"{type(exc).__name__}: {exc}"}

    last_update = next_update = None
    for line in out.stdout.splitlines():
        if line.startswith("lastUpdate="):
            last_update = _parse_openssl_ts(line.split("=", 1)[1])
        elif line.startswith("nextUpdate="):
            next_update = _parse_openssl_ts(line.split("=", 1)[1])
    return {
        **base,
        "last_update": last_update.isoformat() if last_update else None,
        "not_after": next_update.isoformat() if next_update else None,
        "days_remaining": _days_until(next_update),
    }


def read_certs() -> list[dict]:
    """Snapshot every cert + every CRL on disk. We scan TWO roots:

      - PKI dir (easy-rsa source of truth) → CA, issued (server + clients),
        revoked, master CRL. `source` = 'pki'.
      - Live OpenVPN dir → the server cert OpenVPN starts up with, plus the
        CRL OpenVPN enforces. `source` = 'live'. Stale entries here are the
        renew-but-forgot-to-copy bug.

    Each returned dict carries `source` so the UI can render them side-by-side
    and the operator can spot mismatches at a glance.
    """
    out: list[dict] = []

    # --- PKI dir (easy-rsa source of truth) ----------------------------------
    if OPENVPN_PKI_DIR.exists():
        ca = OPENVPN_PKI_DIR / "ca.crt"
        if ca.exists():
            cert = _read_cert_file(ca, "ca")
            if cert:
                cert["source"] = "pki"
                out.append(cert)

        issued_dir = OPENVPN_PKI_DIR / "issued"
        if issued_dir.exists():
            for crt in sorted(issued_dir.glob("*.crt")):
                kind = "server" if crt.stem.lower().startswith("server") else "client"
                cert = _read_cert_file(crt, kind)
                if cert:
                    cert["source"] = "pki"
                    out.append(cert)

        revoked_dir = OPENVPN_PKI_DIR / "revoked" / "certs_by_serial"
        if revoked_dir.exists():
            for crt in sorted(revoked_dir.glob("*.crt")):
                cert = _read_cert_file(crt, "revoked")
                if cert:
                    cert["revoked"] = True
                    cert["source"] = "pki"
                    out.append(cert)

        pki_crl = OPENVPN_PKI_DIR / "crl.pem"
        if pki_crl.exists():
            crl = _read_crl_file(pki_crl)
            if crl:
                crl["source"] = "pki"
                out.append(crl)

    # --- Live OpenVPN dir (what OpenVPN actually serves) --------------------
    if OPENVPN_LIVE_DIR.exists():
        # The live server cert — name matches the PKI one (server_<token>.crt).
        # There's usually exactly one; if multiple, we ship them all.
        for crt in sorted(OPENVPN_LIVE_DIR.glob("server*.crt")):
            cert = _read_cert_file(crt, "server")
            if cert:
                cert["source"] = "live"
                out.append(cert)

        # The live CA — usually a stale duplicate of the PKI's, but worth
        # showing because OpenVPN reads THIS one for client validation.
        live_ca = OPENVPN_LIVE_DIR / "ca.crt"
        if live_ca.exists():
            cert = _read_cert_file(live_ca, "ca")
            if cert:
                cert["source"] = "live"
                out.append(cert)

        # The live CRL — what OpenVPN enforces. If PKI's CRL is newer than
        # this one, the operator forgot to copy after a revoke.
        live_crl = OPENVPN_LIVE_DIR / "crl.pem"
        if live_crl.exists():
            crl = _read_crl_file(live_crl)
            if crl:
                crl["source"] = "live"
                out.append(crl)

    return out


# ---------- SQS send + spool (shared by both threads) -----------------------
#
# Lock guards the spool dir during read-and-replay; concurrent writes are
# safe because spool filenames embed a millisecond timestamp + thread id.

_spool_lock = threading.Lock()
_send_client = None
_client_lock = threading.Lock()


def _sqs():
    """Lazily build a shared boto3 client. boto3 SQS clients are thread-safe."""
    global _send_client
    if _send_client is not None:
        return _send_client
    with _client_lock:
        if _send_client is None:
            import boto3
            region = os.environ.get("AWS_REGION") or host_identity().get("region")
            _send_client = boto3.client("sqs", region_name=region)
    return _send_client


def _spool(payload: dict) -> None:
    # Lock base + spool dirs to 0700 so journal lines + cursor file aren't
    # readable by non-root. Write with explicit 0600, umask-independent.
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SPOOL_DIR.parent, 0o700)
        os.chmod(SPOOL_DIR, 0o700)
    except Exception:
        pass
    fname = f"{int(time.time()*1000)}-{threading.get_ident()}.json"
    path = SPOOL_DIR / fname
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
    """Drop oldest spool files when over caps. A box that loses SQS for days
    must NEVER fill /var — silent monitoring loss is bad, full-disk outage
    is worse. Cap by file count first (cheap), then by byte total."""
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
        for f in files:
            try:
                total += f.stat().st_size
            except Exception:
                continue
        if total > SPOOL_MAX_BYTES:
            # Walk oldest-first, dropping until under cap.
            running = total
            for f in files:
                if running <= SPOOL_MAX_BYTES:
                    break
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    running -= sz
                except Exception:
                    pass
    except Exception as exc:
        print(f"spool cap enforcement failed: {exc}", file=sys.stderr)


def _flush_spool(client) -> None:
    with _spool_lock:
        if not SPOOL_DIR.exists():
            return
        for f in sorted(SPOOL_DIR.glob("*.json")):
            try:
                client.send_message(QueueUrl=SQS_URL, MessageBody=f.read_text())
                f.unlink()
            except Exception:
                return  # still unreachable; keep the rest for later


def _shrink_for_sqs(payload: dict, max_bytes: int = SQS_BODY_MAX_BYTES) -> dict:
    """If a payload would exceed SQS's 256 KiB limit, drop the biggest
    dispensable fields in priority order until it fits.

    Order: status_raw → certs → auth_lines. Heartbeat metadata (host, state,
    active) always ships so /vpn keeps showing the box is alive. Whatever
    was dropped is recorded in payload.truncated so /vpn surfaces the loss
    instead of pretending all is well."""
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload

    truncated: list[str] = []
    # 1. status_raw — verbatim status.log; biggest field on busy servers.
    if "status_raw" in payload and payload["status_raw"]:
        payload["status_raw"] = None
        truncated.append("status_raw")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            payload["truncated"] = truncated
            return payload

    # 2. certs — large on PKIs with many revoked client certs.
    if "certs" in payload:
        payload.pop("certs")
        truncated.append("certs")
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            payload["truncated"] = truncated
            return payload

    # 3. auth_lines — last resort; we lose this window's auth signal but
    # the next tick will pick up new lines (and the follower thread ships
    # them out-of-band in real time anyway).
    if "auth_lines" in payload:
        payload.pop("auth_lines")
        truncated.append("auth_lines")

    payload["truncated"] = truncated
    return payload


# Consecutive send failures (shared across heartbeat + follower threads).
_send_failures = 0
_send_failures_lock = threading.Lock()
_BACKOFF_MAX_SECS = 300


def send(payload: dict, label: str) -> None:
    """Push one payload to SQS, with backoff on repeated failures.

    Without backoff, a permanently-broken URL (or revoked IAM) would have
    every send fail + spool every tick. Within hours the spool's file cap
    kicks in and we start losing the oldest data. Backoff lets us batch
    longer between attempts without spamming SQS / our own logs."""
    global _send_failures

    payload = _shrink_for_sqs(payload)

    try:
        client = _sqs()
        _flush_spool(client)
        client.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(payload))
        with _send_failures_lock:
            _send_failures = 0
        flags = []
        if payload.get("truncated"):
            flags.append("trunc=" + ",".join(payload["truncated"]))
        print(f"[{label}] sent kind={payload.get('kind')} "
              f"auth_lines={len(payload.get('auth_lines') or [])}"
              f"{' ' + ' '.join(flags) if flags else ''}")
    except Exception as exc:
        with _send_failures_lock:
            _send_failures += 1
            fails = _send_failures
        print(f"[{label}] send failed (#{fails}), spooling: {exc}", file=sys.stderr)
        try:
            _spool(payload)
        except Exception as spool_exc:
            print(f"[{label}] spool also failed: {spool_exc}", file=sys.stderr)
        if fails >= 4:
            backoff = min(_BACKOFF_MAX_SECS, 30 * ((fails - 3 + 2) // 3))
            print(f"[{label}] backing off {backoff}s after {fails} failures", file=sys.stderr)
            time.sleep(backoff)


# ---------- Heartbeat thread ------------------------------------------------

def build_heartbeat_report() -> dict:
    state = systemctl_state()
    return {
        "kind": "vpn_report",
        "agent_version": AGENT_VERSION,
        "server": SERVER_NAME,
        "host": host_identity(),
        "uptime_seconds": uptime_seconds(),
        "state": state,
        "active": state == "active",
        "status_raw": read_status_file(),
        "auth_lines": read_auth_lines(INTERVAL + 120),
        "certs": read_certs(),
    }


def heartbeat_loop(once: bool) -> None:
    while True:
        send(build_heartbeat_report(), label="heartbeat")
        # Watchdog ping: tells systemd we're alive AND making progress.
        # If a tick hangs (subprocess stuck, journalctl blocked) systemd
        # SIGKILLs us within WatchdogSec and the unit auto-restarts.
        # The follower thread is intentionally NOT covered — auth-line
        # quiet periods are normal and shouldn't trip the watchdog.
        _sd_notify("WATCHDOG=1")
        if once:
            return
        time.sleep(INTERVAL)


# ---------- Follower thread (sub-second realtime auth) ----------------------

def _load_cursor() -> str | None:
    try:
        text = CURSOR_FILE.read_text().strip()
        return text or None
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"follower: cursor read failed: {exc}", file=sys.stderr)
        return None


def _save_cursor(cursor: str) -> None:
    try:
        CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(CURSOR_FILE.parent, 0o700)
        except Exception:
            pass
        # Atomic-ish: write to a temp + rename, so a crash mid-write doesn't
        # leave a half-written cursor. 0600 so non-root users on the box
        # can't read journald cursors (low-impact but defense-in-depth).
        tmp = CURSOR_FILE.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(cursor)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise
        tmp.replace(CURSOR_FILE)
    except Exception as exc:
        print(f"follower: cursor save failed: {exc}", file=sys.stderr)


def _flush_follower_batch(batch: list[str], cursor: str | None) -> None:
    if not batch:
        return
    payload = {
        "kind": "vpn_auth_realtime",
        "agent_version": AGENT_VERSION,
        "server": SERVER_NAME,
        "host": host_identity(),
        # Scrub MESSAGE in every line — same redaction the heartbeat path
        # applies. Keeps the follower's sub-second alert latency.
        "auth_lines": [scrub_auth_line(ln) for ln in batch],
    }
    send(payload, label="follower")
    if cursor:
        _save_cursor(cursor)


def _spawn_journalctl(cursor: str | None) -> subprocess.Popen:
    cmd = ["journalctl", "-fu", UNIT, "--output=json", "--no-pager"]
    if cursor:
        cmd += ["--after-cursor", cursor]
    else:
        # First-ever start: tail only new entries (don't replay the whole journal).
        cmd += ["--lines", "0"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def follower_loop() -> None:
    """Long-running journal tail. Resumes from the last saved __CURSOR;
    re-spawns journalctl with backoff on EOF/error. Cursor advances over noise
    too so we don't re-read past chatter on restart."""
    while True:
        cursor = _load_cursor()
        print(f"follower: starting (cursor={cursor[:24] + '…' if cursor else 'none'})")
        proc: subprocess.Popen | None = None
        try:
            proc = _spawn_journalctl(cursor)
        except Exception as exc:
            print(f"follower: spawn failed: {exc}", file=sys.stderr)
            # If the cursor is corrupt/invalid, clear it so the next try starts fresh.
            if cursor:
                try:
                    CURSOR_FILE.unlink()
                except Exception:
                    pass
            time.sleep(FOLLOWER_RESTART_BACKOFF)
            continue

        start_t = time.time()
        batch: list[str] = []
        last_flush = time.time()
        last_cursor = cursor

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                # Cheap pre-filter; only parse JSON when it might be relevant or
                # we need to advance the cursor.
                is_auth = any(n in line for n in _AUTH_NEEDLES)
                ent = None
                if is_auth or len(batch) > 0:
                    try:
                        ent = json.loads(line)
                    except Exception:
                        ent = None
                if ent and ent.get("__CURSOR"):
                    last_cursor = ent["__CURSOR"]
                if is_auth:
                    batch.append(line)

                now = time.time()
                if batch and (
                    len(batch) >= FOLLOWER_BATCH_MAX
                    or (now - last_flush) >= FOLLOWER_BATCH_WINDOW
                ):
                    _flush_follower_batch(batch, last_cursor)
                    batch = []
                    last_flush = now
        except Exception as exc:
            print(f"follower: read loop crashed: {exc}", file=sys.stderr)
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
            # Flush any pending lines before restarting.
            _flush_follower_batch(batch, last_cursor)

        # If journalctl exited near-immediately, the cursor is probably stale
        # (e.g. journal was vacuumed). Clear it so the next attempt starts fresh
        # at end-of-journal rather than retrying the same invalid cursor.
        if time.time() - start_t < 3 and cursor:
            print("follower: subprocess exited fast — clearing cursor", file=sys.stderr)
            try:
                CURSOR_FILE.unlink()
            except Exception:
                pass

        time.sleep(FOLLOWER_RESTART_BACKOFF)


def main() -> None:
    if not SQS_URL:
        print("ERROR: set BLACKWATCH_VPN_SQS_URL", file=sys.stderr)
        sys.exit(2)
    # Fail fast on tampered / typo'd URL. IAM policy is the real control
    # (sqs:SendMessage scoped to one queue ARN), but rejecting an obviously
    # bogus URL here surfaces operator error in seconds.
    if not _SQS_URL_RE.match(SQS_URL):
        print(
            f"ERROR: BLACKWATCH_VPN_SQS_URL doesn't look like a valid SQS URL: {SQS_URL}\n"
            "       expected https://sqs.<region>.amazonaws.com/<account>/<queue-name>",
            file=sys.stderr,
        )
        sys.exit(2)

    once = "--once" in sys.argv
    print(f"BlackWatch VPN agent v{AGENT_VERSION} -> {SQS_URL}")
    print(f"  server={SERVER_NAME} unit={UNIT} heartbeat={INTERVAL}s "
          f"follower={'on' if (FOLLOWER_ENABLED and not once) else 'off'}")

    # Tell systemd we're ready (no-op outside Type=notify).
    _sd_notify("READY=1")

    if FOLLOWER_ENABLED and not once:
        t = threading.Thread(target=follower_loop, name="follower", daemon=True)
        t.start()

    heartbeat_loop(once)


if __name__ == "__main__":
    main()
