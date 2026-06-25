#!/usr/bin/env bash
# Install the BlackWatch OpenVPN agent on the VPN box (run as root/sudo).
#
#   sudo BLACKWATCH_VPN_SQS_URL="https://sqs.us-west-1.amazonaws.com/ACCT/blackwatch-vpn-agents" \
#        AWS_REGION="us-west-1" bash install-vpn-agent.sh
#
# Prereqs: the instance's IAM role must have the blackwatch-vpn-agent-send
# policy (sqs:SendMessage to the VPN queue). python3 + journald + openssl
# are present on Amazon Linux. Runs alongside the EC2 host agent — no conflict
# (different unit, different queue, different IAM grant).
#
# Idempotent: safe to re-run. Detects "AGENT_SRC == installed path" and skips
# the copy so you can refresh the systemd unit without re-pushing the script.

set -euo pipefail

: "${BLACKWATCH_VPN_SQS_URL:?set BLACKWATCH_VPN_SQS_URL}"
AWS_REGION="${AWS_REGION:-us-west-1}"
INTERVAL="${INTERVAL:-60}"
OPENVPN_UNIT="${OPENVPN_UNIT:-openvpn-server@server}"
OPENVPN_STATUS_FILE="${OPENVPN_STATUS_FILE:-/var/log/openvpn/status.log}"
SERVER_NAME="${SERVER_NAME:-openvpn}"

# Find vpn_agent.py: explicit AGENT_SRC, next to this script, or repo layout.
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_SRC="${AGENT_SRC:-}"
if [ -z "$AGENT_SRC" ]; then
  for p in "$HERE/vpn_agent.py" "$HERE/../../scripts/vpn_agent.py"; do
    if [ -f "$p" ]; then AGENT_SRC="$p"; break; fi
  done
fi
: "${AGENT_SRC:?could not find vpn_agent.py — set AGENT_SRC=/path/to/vpn_agent.py or place it next to install-vpn-agent.sh}"

# 1. deps — pip3 first (yum/dnf), then a pinned boto3 in the same range the
# EC2 agent uses (works on AL2's python 3.7 through 3.12+).
if ! command -v pip3 >/dev/null 2>&1; then
  if   command -v dnf       >/dev/null 2>&1; then dnf install -y python3-pip
  elif command -v yum       >/dev/null 2>&1; then yum install -y python3-pip
  elif command -v apt-get   >/dev/null 2>&1; then apt-get update && apt-get install -y python3-pip
  else echo "ERROR: no supported package manager found"; exit 2; fi
fi
pip3 install --quiet 'boto3>=1.28,<1.35'

# 2. install the agent. /opt/blackwatch holds the script (not a secret).
# /var/lib/blackwatch-vpn-agent holds the spool (journal lines, possibly
# user identifiers) — root-only, 0700.
install -d -m 0755 /opt/blackwatch
install -d -m 0700 /var/lib/blackwatch-vpn-agent

DEST=/opt/blackwatch/vpn_agent.py
if [ "$(readlink -f "$AGENT_SRC")" != "$(readlink -f "$DEST")" ]; then
  install -m 0755 "$AGENT_SRC" "$DEST"
else
  echo "AGENT_SRC == DEST — skipping copy (refreshing systemd unit only)"
fi

# 2b. Pre-flight — fail loudly at install time if the instance role can't
# reach SQS. Saves the operator from wiring everything up and then wondering
# why the dashboard stays empty for an hour.
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity --region "$AWS_REGION" >/dev/null 2>&1; then
    if aws sqs get-queue-attributes \
        --queue-url "$BLACKWATCH_VPN_SQS_URL" \
        --attribute-names QueueArn \
        --region "$AWS_REGION" >/dev/null 2>&1; then
      echo "pre-flight: instance role can read VPN queue attributes ✓"
    else
      # Expected with the minimum-privilege policy (sqs:SendMessage ONLY).
      # The agent doesn't need GetQueueAttributes; this preflight does.
      echo "pre-flight: instance role can't read queue attributes (expected — only sqs:SendMessage is granted). SendMessage will be verified by the first heartbeat." >&2
    fi
  else
    echo "WARNING: aws sts get-caller-identity failed — is the instance role attached?" >&2
  fi
fi

# 3. systemd unit. Type=notify + WatchdogSec for hang detection. Sandboxing
# directives are split by systemd version: AL2 (systemd 219) silently ignores
# anything 231+; AL2023 / Ubuntu 22.04+ apply everything.
#
# The agent runs as root because it must:
#  - read /var/log/openvpn/status.log (root:root 0600)
#  - read journald for the openvpn-server@server unit
#  - read /etc/openvpn/easy-rsa/pki/* (root-only)
#
# Same as the EC2 agent — privileges can't drop. Sandbox aggressively instead.
cat > /etc/systemd/system/blackwatch-vpn-agent.service <<EOF
[Unit]
Description=BlackWatch OpenVPN agent
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
WatchdogSec=180
TimeoutStartSec=30

Environment=BLACKWATCH_VPN_SQS_URL=${BLACKWATCH_VPN_SQS_URL}
Environment=AWS_REGION=${AWS_REGION}
Environment=INTERVAL=${INTERVAL}
Environment=OPENVPN_UNIT=${OPENVPN_UNIT}
Environment=OPENVPN_STATUS_FILE=${OPENVPN_STATUS_FILE}
Environment=SERVER_NAME=${SERVER_NAME}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/blackwatch/vpn_agent.py
Restart=always
RestartSec=10
User=root

# Resource limits — agent must never become the problem on the VPN box.
MemoryLimit=200M
CPUQuota=20%
TasksMax=64
Nice=10
LimitNOFILE=1024

# --- Sandboxing — works on AL2 systemd 219 ---
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK

# --- Requires systemd 231+ (silently ignored on AL2; auto-enable on AL2023+) ---
# ProtectKernelTunables looks like a 219 directive but was actually added in 232.
ProtectKernelTunables=true
ReadWritePaths=/var/lib/blackwatch-vpn-agent /var/log
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
systemctl enable blackwatch-vpn-agent.service
# `enable --now` is a no-op when the unit is already active, so the new code
# would never run on a re-install. Force an actual restart.
systemctl restart blackwatch-vpn-agent.service
sleep 2
systemctl status blackwatch-vpn-agent.service --no-pager | head -8
echo
echo "Installed. Logs: journalctl -u blackwatch-vpn-agent -f"
