#!/usr/bin/env python3
"""IAM page test-drive.

Seeds one synthetic event per row/section on the /iam page so you can verify
every panel renders, the counters tick, and the detail formatters work. Cleans
up by deleting only the events it created — nothing else is touched.

Why direct DB insert (not POST /ingest):
  * Skips the notification dispatcher — no Slack flood while exercising the UI.
  * Skips the rule engine — severities stay None so you see what an unscored
    event looks like in each section.
  * Skips the deterministic event_id paths in real adapters — each run uses
    fresh UUIDs so re-running always lands new rows even within one minute.

Run modes:
    python scripts/iam_test_drive.py                # seed + wait for Enter + clean
    python scripts/iam_test_drive.py --seed         # seed only, exit
    python scripts/iam_test_drive.py --clean        # delete all test-drive rows
    python scripts/iam_test_drive.py --list         # show what's currently seeded

The script is safe to run repeatedly. Every event it inserts gets the tag
'test-drive' AND target_id prefix 'iam-test-drive:', so cleanup is exact —
no chance of nuking real events.

Container vs. host:
    From inside the app container:    python /app/scripts/iam_test_drive.py
    From your host PC (Docker port):  python scripts/iam_test_drive.py
      (uses DATABASE_URL env if set, else localhost:5432)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    sys.stderr.write(
        "psycopg is required. Install it (pip install 'psycopg[binary]') or\n"
        "run this script inside the app container:\n"
        "    docker compose exec app python /app/scripts/iam_test_drive.py\n"
    )
    sys.exit(1)


DEFAULT_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://blackwatch:blackwatch@localhost:5432/blackwatch",
)

# Every test-drive event carries this in `tags` AND its target_id starts with
# this prefix. Cleanup deletes ON BOTH conditions — defense in depth so a real
# event tagged "test-drive" by accident isn't wiped.
TAG = "test-drive"
TARGET_PREFIX = "iam-test-drive:"


# ---------- Event factory ---------------------------------------------------


def _now_iso(offset_seconds: int = 0) -> str:
    """ISO timestamp slightly in the past so events appear in chronological
    order even when inserted in a tight loop."""
    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


def _make(
    *,
    action: str,
    category: str,
    outcome: str = "success",
    principal: str = "alice@example.com",
    actor_type: str | None = "user",
    source_ip: str | None = "203.0.113.42",
    target_name: str = "resource",
    target_type: str | None = None,
    extra: dict[str, Any] | None = None,
    severity: str | None = None,
    offset_seconds: int = 0,
    module: str = "aws.cloudtrail",
    region: str = "us-west-1",
) -> dict[str, Any]:
    """Build one synthetic event row as a dict matching the events table.

    Returns the dict of column → value (envelope/raw are JSON-encoded by the
    caller). target_id always starts with TARGET_PREFIX so cleanup is precise.
    """
    event_id = str(uuid.uuid4())
    event_time = _now_iso(offset_seconds)
    target_id = f"{TARGET_PREFIX}{target_name}-{event_id[:8]}"

    actor = {
        "principal": principal,
        "type": actor_type,
        "is_root": False,
        "via_role": None,
        "source_ip": source_ip,
        "user_agent": None,
    }
    target = {"id": target_id, "type": target_type or "resource", "name": target_name}
    source = {
        "module": module,
        "vendor": "aws",
        "account": "111122223333",
        "region": region,
        "transport": "webhook",
    }

    envelope = {
        "event_id": event_id,
        "schema_version": 1,
        "dedup_fingerprint": "",
        "event_time": event_time,
        "ingested_at": event_time,
        "source": source,
        "category": category,
        "action": action,
        "outcome": outcome,
        "actor": actor,
        "target": target,
        "observables": [],
        "severity": severity,
        "tags": [TAG],
        "rule_matches": [],
        "extra": extra or {},
        "raw": {},
    }

    return {
        "event_id": event_id,
        "schema_version": 1,
        "event_time": event_time,
        "ingested_at": event_time,
        "dedup_fingerprint": event_id,  # unique per row; we don't care about real dedup here
        "module": source["module"],
        "vendor": source["vendor"],
        "account": source["account"],
        "region": source["region"],
        "transport": source["transport"],
        "category": category,
        "action": action,
        "outcome": outcome,
        "actor_principal": actor["principal"],
        "actor_type": actor["type"],
        "actor_is_root": actor["is_root"],
        "actor_source_ip": actor["source_ip"],
        "target_id": target_id,
        "target_type": target["type"],
        "severity": severity,
        "tags": [TAG],
        "envelope": envelope,
        "raw": envelope,
    }


# ---------- Catalog: one event per /iam section ----------------------------


def build_catalog() -> list[dict[str, Any]]:
    """One representative event for each section + a few extras to exercise
    detail formatters (multiple SG rules, snapshot-public, IMDSv1-enabled, etc.).
    Order is roughly newest first so the UI shows them in a clean cascade.
    """
    events: list[dict[str, Any]] = []
    off = 0

    # ---- 1. Console logins (success + failed) -----------------------------
    events.append(_make(
        action="auth.console.login", category="iam", outcome="success",
        principal="alice@example.com", target_name="aws-console",
        offset_seconds=off,
    ))
    off += 10
    events.append(_make(
        action="auth.console.login", category="iam", outcome="failure",
        principal="bob@example.com", target_name="aws-console",
        source_ip="198.51.100.7", offset_seconds=off,
    ))
    off += 10

    # ---- 2. Host / VPN auth failure ---------------------------------------
    events.append(_make(
        action="host.auth.ssh.failure", category="host", outcome="failure",
        module="ec2.host", principal="root", actor_type="user",
        source_ip="45.55.123.45", target_name="web-01",
        offset_seconds=off,
    ))
    off += 10
    events.append(_make(
        action="vpn.auth.failure", category="vpn", outcome="failure",
        module="vpn.openvpn", principal="bob@example.com", actor_type="user",
        source_ip="198.51.100.7", target_name="openvpn-prod-1",
        offset_seconds=off,
    ))
    off += 10

    # ---- 3. IAM changes (users / roles / policies / keys / MFA / login) ---
    for action, target in [
        ("iam.user.create",            "iam-user/carol"),
        ("iam.role.create",            "iam-role/deploy-bot"),
        ("iam.policy.attach",          "iam-user/carol"),
        ("iam.access_key.create",      "iam-user/carol"),
        ("iam.mfa.deactivate",         "iam-user/bob"),
        ("iam.login_profile.create",   "iam-user/carol"),
    ]:
        events.append(_make(
            action=action, category="iam",
            principal="alice@example.com", target_name=target,
            extra={"affected_user": target.split("/")[-1]},
            offset_seconds=off,
        ))
        off += 5

    # ---- 4. Security group changes (ingress, instance attach, create) -----
    events.append(_make(
        action="network.sg.create", category="network",
        target_name="sg-prod-web", target_type="aws.ec2.sg",
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="network.sg.ingress.add", category="network",
        target_name="sg-prod-web", target_type="aws.ec2.sg",
        extra={
            "rules": [{"cidr": "0.0.0.0/0", "protocol": "tcp",
                       "from_port": 22, "to_port": 22}],
            "public_ingress": True,
            "public_ingress_risky_port": True,
        },
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="network.sg.instance_attach", category="network",
        target_name="i-0123456789abcdef0", target_type="aws.ec2.instance",
        extra={"instance_id": "i-0123456789abcdef0",
               "sg_ids": ["sg-prod-web", "sg-allow-internal"]},
        offset_seconds=off,
    ))
    off += 5

    # ---- 5. Storage / compute exposure ------------------------------------
    events.append(_make(
        action="s3.bucket.acl.put", category="storage",
        target_name="prod-customer-pii", target_type="aws.s3.bucket",
        extra={"public_acl": True, "before": "private", "after": "public-read"},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="s3.bucket.bpa.delete", category="storage",
        target_name="prod-backup", target_type="aws.s3.bucket",
        extra={"bpa_removed": True},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="storage.snapshot.modify", category="storage",
        target_name="snap-0abcd1234", target_type="aws.ebs.snapshot",
        extra={"snapshot_made_public": True, "group": "all"},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="compute.imds.modify", category="compute",
        target_name="i-0123456789abcdef0", target_type="aws.ec2.instance",
        extra={"imdsv1_enabled": True, "http_tokens": "optional"},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="compute.ami.modify", category="compute",
        target_name="ami-0987654321fedcba0", target_type="aws.ec2.ami",
        extra={"ami_made_public": True},
        offset_seconds=off,
    ))
    off += 5

    # ---- 6. KMS / secrets -------------------------------------------------
    events.append(_make(
        action="kms.policy.put", category="iam",
        target_name="kms-prod-encryption", target_type="aws.kms.key",
        extra={"kms_wildcard_policy": True},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="kms.rotation.disable", category="iam",
        target_name="kms-prod-encryption", target_type="aws.kms.key",
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="kms.key.delete_scheduled", category="iam",
        target_name="kms-old-secrets", target_type="aws.kms.key",
        extra={"pending_window_days": 7},
        offset_seconds=off,
    ))
    off += 5

    # ---- 7. Host posture changes ------------------------------------------
    for action, target, ex in [
        ("host.authorized_key.added", "web-01",
         {"user": "ubuntu", "fingerprint": "SHA256:eY8nP+...stub", "key_type": "ssh-ed25519"}),
        ("host.user.added", "web-01",
         {"user": "deploy", "uid": 1003, "shell": "/bin/bash"}),
        ("host.sudoers.changed", "web-01",
         {"change": "added", "user": "deploy", "rule": "ALL=(ALL) NOPASSWD: ALL"}),
        ("host.port.opened", "db-01",
         {"port": 5432, "address": "0.0.0.0", "process": "postgres"}),
        ("host.suid.added", "web-01",
         {"path": "/tmp/.x/bin/su", "owner": "root", "mode": "4755"}),
        ("host.cron.added", "web-01",
         {"user": "root", "schedule": "*/5 * * * *", "command": "/tmp/x.sh"}),
        ("host.service.added", "web-01",
         {"unit": "shady.service", "enabled": True}),
        ("host.packages.changed", "web-01",
         {"added_count": 1, "added": ["netcat"]}),
    ]:
        events.append(_make(
            action=action, category="host", module="ec2.host",
            principal="root", target_name=target, target_type="host",
            extra=ex, offset_seconds=off,
        ))
        off += 4

    # ---- 8. AssumeRole ----------------------------------------------------
    events.append(_make(
        action="auth.assume_role", category="iam",
        principal="alice@example.com",
        target_name="arn:aws:iam::111122223333:role/admin",
        target_type="aws.iam.role",
        extra={
            "from_principal": "alice@example.com",
            "to_role_arn": "arn:aws:iam::111122223333:role/admin",
            "session_name": "alice-cli",
        },
        offset_seconds=off,
    ))
    off += 5

    # ---- 9. AWS posture finding · new -------------------------------------
    events.append(_make(
        action="aws.posture.finding.new", category="finding",
        module="aws.posture", principal=None, actor_type=None, source_ip=None,
        target_name="prod-customer-pii", target_type="aws.s3.bucket",
        extra={
            "finding_id": "s3-bucket-public-read:prod-customer-pii",
            "finding_type": "s3.bucket.public_read",
            "severity": "high",
            "resource_type": "aws.s3.bucket",
        },
        severity="high",
        offset_seconds=off,
    ))
    off += 5

    # ---- 10. CloudTrail tamper · audit -----------------------------------
    events.append(_make(
        action="cloudtrail.trail.stop", category="audit",
        target_name="trail/security-audit", target_type="aws.cloudtrail.trail",
        extra={"trail_name": "security-audit"},
        offset_seconds=off,
    ))
    off += 5
    events.append(_make(
        action="cloudtrail.trail.update", category="audit",
        target_name="trail/security-audit", target_type="aws.cloudtrail.trail",
        extra={"logging_disabled": True},
        offset_seconds=off,
    ))

    return events


# ---------- DB ops ----------------------------------------------------------


_INSERT = """
INSERT INTO events (
    event_id, schema_version, event_time, ingested_at, dedup_fingerprint,
    module, vendor, account, region, transport,
    category, action, outcome,
    actor_principal, actor_type, actor_is_root, actor_source_ip,
    target_id, target_type,
    severity, tags, envelope, raw
) VALUES (
    %(event_id)s, %(schema_version)s, %(event_time)s, %(ingested_at)s, %(dedup_fingerprint)s,
    %(module)s, %(vendor)s, %(account)s, %(region)s, %(transport)s,
    %(category)s, %(action)s, %(outcome)s,
    %(actor_principal)s, %(actor_type)s, %(actor_is_root)s, %(actor_source_ip)s,
    %(target_id)s, %(target_type)s,
    %(severity)s, %(tags)s, %(envelope)s, %(raw)s
)
ON CONFLICT (event_id) DO NOTHING
"""


def seed(dsn: str) -> int:
    catalog = build_catalog()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for row in catalog:
            row = dict(row)
            row["envelope"] = Jsonb(row["envelope"])
            row["raw"] = Jsonb(row["raw"])
            cur.execute(_INSERT, row)
        conn.commit()
    return len(catalog)


def clean(dsn: str) -> int:
    """Delete ONLY events with tag='test-drive' AND target_id like 'iam-test-drive:%'.
    Both conditions must hold — no chance of nuking a real event that happens
    to have either marker alone."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM events "
            "WHERE %s = ANY(tags) AND target_id LIKE %s",
            [TAG, f"{TARGET_PREFIX}%"],
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted


def show(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT action, COUNT(*) "
            "FROM events "
            "WHERE %s = ANY(tags) AND target_id LIKE %s "
            "GROUP BY action ORDER BY action",
            [TAG, f"{TARGET_PREFIX}%"],
        )
        rows = cur.fetchall()
    if not rows:
        print("nothing seeded (no test-drive events in DB)")
        return
    print(f"{'action':40s} count")
    print("-" * 50)
    for action, n in rows:
        print(f"{action:40s} {n:>5d}")
    print("-" * 50)
    print(f"{'TOTAL':40s} {sum(n for _, n in rows):>5d}")


# ---------- Entry -----------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--dsn", default=DEFAULT_DSN,
                        help=f"Postgres DSN (default: {DEFAULT_DSN})")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seed", action="store_true",
                       help="Insert events and exit (don't wait, don't clean)")
    group.add_argument("--clean", action="store_true",
                       help="Delete only the events this script created")
    group.add_argument("--list", action="store_true",
                       help="Show currently-seeded test-drive events")
    args = parser.parse_args()

    if args.list:
        show(args.dsn)
        return 0

    if args.clean:
        n = clean(args.dsn)
        print(f"deleted {n} test-drive event(s)")
        return 0

    if args.seed:
        n = seed(args.dsn)
        print(f"seeded {n} event(s).  cleanup later with: --clean")
        return 0

    # Default: seed → prompt → clean
    n = seed(args.dsn)
    print(f"\nSeeded {n} event(s). Open these in your browser:")
    print("  /iam                — every section should now have rows + counter ticks")
    print("  /posture/findings   — one new s3 bucket public-read finding")
    print("  /events?q=test-drive — raw event view (search by tag)")
    print("\nPress Enter to clean up, or Ctrl+C to leave the seed in place.")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nleft seed in place. Run again with --clean to remove.")
        return 0
    deleted = clean(args.dsn)
    print(f"deleted {deleted} event(s). done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
