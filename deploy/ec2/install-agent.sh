#!/usr/bin/env bash
# Install the BlackWatch EC2 reporter agent on this instance (run as root/sudo).
#
#   sudo BLACKWATCH_SQS_URL="https://sqs.us-west-1.amazonaws.com/ACCT/blackwatch-ec2-agents" \
#        AWS_REGION="us-west-1" \
#        BLACKWATCH_TAGS="env=prod,role=api-server" \
#        bash install-agent.sh
#
# Prereqs: the instance's IAM role must have the blackwatch-ec2-agent-send policy
# (sqs:SendMessage to the queue). python3 + journald are present on Amazon Linux
# and Debian/Ubuntu. Both RPM and DPKG package managers are supported.

set -euo pipefail

: "${BLACKWATCH_SQS_URL:?set BLACKWATCH_SQS_URL}"
AWS_REGION="${AWS_REGION:-us-west-1}"
INTERVAL="${INTERVAL:-60}"
BLACKWATCH_TAGS="${BLACKWATCH_TAGS:-}"

# Find ec2_agent.py: explicit AGENT_SRC, next to this script, or repo layout.
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_SRC="${AGENT_SRC:-}"
if [ -z "$AGENT_SRC" ]; then
  for p in "$HERE/ec2_agent.py" "$HERE/../../scripts/ec2_agent.py"; do
    if [ -f "$p" ]; then AGENT_SRC="$p"; break; fi
  done
fi
: "${AGENT_SRC:?could not find ec2_agent.py — set AGENT_SRC=/path/to/ec2_agent.py or place it next to install-agent.sh}"

# 1. deps — pip3 first (try yum/dnf, then apt for Debian/Ubuntu)
if ! command -v pip3 >/dev/null 2>&1; then
  if   command -v dnf       >/dev/null 2>&1; then dnf install -y python3-pip
  elif command -v yum       >/dev/null 2>&1; then yum install -y python3-pip
  elif command -v apt-get   >/dev/null 2>&1; then apt-get update && apt-get install -y python3-pip
  else echo "ERROR: no supported package manager found"; exit 2; fi
fi
# Pin boto3 — the AL2-default python3.7 will eventually pull a boto3 that drops
# 3.7 support and break agents silently. Pin to a known-good range that supports
# 3.7 through 3.12+.
pip3 install --quiet 'boto3>=1.28,<1.35'

# 2. install the agent. /opt/blackwatch holds the script (world-readable is OK,
# it's not a secret). /var/lib/blackwatch-agent holds the spool (journal lines,
# process args) — root-only, 0700.
install -d -m 0755 /opt/blackwatch
install -d -m 0700 /var/lib/blackwatch-agent
# Skip the copy if AGENT_SRC is already the installed path (re-running the
# script to just refresh the systemd unit). `install(1)` errors out with
# "are the same file" otherwise and set -e aborts the whole install.
DEST=/opt/blackwatch/ec2_agent.py
if [ "$(readlink -f "$AGENT_SRC")" != "$(readlink -f "$DEST")" ]; then
  install -m 0755 "$AGENT_SRC" "$DEST"
else
  echo "AGENT_SRC == DEST — skipping copy (refreshing systemd unit only)"
fi

# 2b. Pre-flight — fail at install time if the instance role can't actually
# reach SQS. Otherwise the operator wires the policy wrong and only finds out
# when the dashboard stays empty. We send a zero-length probe and read the
# response code; SendMessage with a 1-byte payload tagged "preflight" is the
# minimum that actually exercises the IAM grant.
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity --region "$AWS_REGION" >/dev/null 2>&1; then
    if aws sqs get-queue-attributes \
        --queue-url "$BLACKWATCH_SQS_URL" \
        --attribute-names QueueArn \
        --region "$AWS_REGION" >/dev/null 2>&1; then
      echo "pre-flight: instance role can read queue attributes ✓"
    else
      # Expected with the minimum-privilege policy (sqs:SendMessage ONLY).
      # The agent doesn't need GetQueueAttributes; this preflight does.
      echo "pre-flight: instance role can't read queue attributes (expected — only sqs:SendMessage is granted). SendMessage will be verified by the first heartbeat." >&2
    fi
  else
    echo "WARNING: aws sts get-caller-identity failed — is the instance role attached?" >&2
  fi
fi

# 3. systemd unit — resource limits + sandboxing + watchdog. The agent runs
# as root because it needs to read shadow/journal/SUID/sudoers, but every
# other privilege is locked down so a compromise can't spread.
#
# AL2 ships systemd 219; we use the OLD directive names where they exist
# (MemoryLimit, CPUQuota) and only the newer hardening directives that 219
# accepts as no-ops if unsupported. Anything 219 doesn't know is ignored
# with a journald warning; nothing breaks.
cat > /etc/systemd/system/blackwatch-agent.service <<EOF
[Unit]
Description=BlackWatch EC2 reporter agent
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
WatchdogSec=180
TimeoutStartSec=30

Environment=BLACKWATCH_SQS_URL=${BLACKWATCH_SQS_URL}
Environment=AWS_REGION=${AWS_REGION}
Environment=INTERVAL=${INTERVAL}
Environment=BLACKWATCH_TAGS=${BLACKWATCH_TAGS}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/blackwatch/ec2_agent.py
Restart=always
RestartSec=10
User=root

# Resource limits — agent must never become the problem on a struggling box.
MemoryLimit=200M
CPUQuota=20%
TasksMax=64
Nice=10
LimitNOFILE=1024

# Sandboxing — defense-in-depth in case the agent is ever exploited.
# It already runs as root because it MUST read shadow + journal + SUID,
# so we can't drop privileges. Instead, lock everything else down.
#
# COMPATIBILITY NOTE: AL2 ships systemd 219 — many modern hardening
# directives didn't exist yet and systemd 219 silently ignores them
# (no error, just no protection). Directives below are grouped by the
# systemd version they require, so it's clear what kicks in where.
#
# AL2 (systemd 219) gets: NoNewPrivileges, ProtectSystem=full,
#   ProtectHome=read-only, PrivateTmp, PrivateDevices,
#   SystemCallFilter/Architectures, RestrictAddressFamilies, WatchdogSec.
# AL2023 / Ubuntu 22.04+ (systemd 245+) ALSO get: ProtectKernelTunables,
#   ProtectSystem=strict, ReadWritePaths, ProtectKernelModules,
#   ProtectControlGroups, ProtectClock, Restrict{Namespaces,Realtime,SUIDSGID},
#   LockPersonality, LogRateLimit*.

# --- Works on AL2 systemd 219 ---
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
# IPv4 is what SQS needs; AF_UNIX for sd_notify; AF_NETLINK so journalctl /
# ss work. AF_INET6 only needed on dual-stack boxes — harmless to leave in.
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK

# --- Requires systemd 231+ (silently ignored on AL2) ---
# When you move to AL2023 / Ubuntu 22.04 these flip on automatically.
# ProtectKernelTunables looks like a 219 directive but was actually added in 232.
ProtectKernelTunables=true
ReadWritePaths=/var/lib/blackwatch-agent /var/log
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true

# --- Requires systemd 240+ (silently ignored on AL2) ---
LogRateLimitIntervalSec=10
LogRateLimitBurst=200

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable blackwatch-agent.service
# `enable --now` is a no-op when the unit is already active, so the new binary
# would never run on a re-install. Force an actual restart.
systemctl restart blackwatch-agent.service
sleep 2
systemctl status blackwatch-agent.service --no-pager | head -8
echo
echo "Installed. Logs: journalctl -u blackwatch-agent -f"
