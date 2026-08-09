# OpenVPN nano — footprint reduction runbook

Host: `172.16.1.97` (us-west-1) — the `t4g.nano` (415 MB RAM) that runs OpenVPN + NAT for internal EC2s.

## Why this was done

The nano was under memory pressure (25 MB free, 156 MB in swap) and disk was at 58 % (9.2 GB / 16 GB). Audit on 2026-08-09 identified low-value RAM and disk consumers that could be cut without touching the box's real jobs (OpenVPN, NAT, BW agents, Wazuh, fail2ban, SSM).

## What was changed

### 1. Deleted `/var/log/openvpn.log` (2.8 GB)
Legacy verbose OpenVPN log written locally. **All OpenVPN logs are already shipped to CloudWatch Logs** by the CloudWatch agent (kept enabled specifically for HITRUST evidence — logs must live in a centralized store). Deleting the local file loses nothing that isn't preserved centrally.

Added a `logrotate` rule so it can never grow past 50 MB again.

### 2. Capped `systemd-journald` at 200 MB (was 1.6 GB uncapped)

**What is journald / journal logs?**
`systemd-journald` is the Linux system logger that ships with modern distros. Every service running under systemd (openvpn-server@server, blackwatch-vpn-agent, sshd, wazuh-agent, etc.) writes its stdout/stderr and any structured log messages here. The files live in `/var/log/journal/…` as binary files. You read them with `journalctl` (e.g. `journalctl -u blackwatch-vpn-agent -f`).

Journald had no size cap set, so it accumulated ~1.6 GB. Capped it at 200 MB (`SystemMaxUse=200M`, keeps ~500 MB free on disk, individual file ≤50 MB). Old entries roll off; new entries keep being written. Nothing else needs to change — every service still logs to it, we just don't hoard 3 months of history on a nano.

### 3. `yum clean all` (~600 MB)
Cached package metadata from Amazon Linux 2's yum repos. Rebuilds itself on the next `yum` operation. Harmless.

### 4. Disabled `amazon-cloudwatch-agent` (saves ~50 MB RAM)

The single biggest RAM consumer on the box was `amazon-cloudwatch-agent` — 30 MB RSS + ~23 MB in swap ≈ 53 MB total. On a 415 MB box that's meaningful headroom.

**Why keep the config:** the agent was installed and configured specifically because a prior HITRUST assessor asked where OpenVPN logs were centralized (answer at that time: CloudWatch Logs, via this agent). The agent may need to be flipped back on quickly during the next audit cycle, or before it, if we decide BlackWatch isn't yet compliance-ready to be the sole log store. So we disable the *service*, not the *config*.

**Action taken:**

```bash
sudo systemctl disable --now amazon-cloudwatch-agent
```

`disable --now` stops it immediately AND removes it from boot. The binary (`/opt/aws/amazon-cloudwatch-agent/`) and the config files (`/opt/aws/amazon-cloudwatch-agent/etc/*.json`, `*.toml`, `*.yaml`) are **untouched**. No re-registration, no re-install, no re-config needed to bring it back.

**To re-enable (takes <10 seconds):**

```bash
sudo systemctl enable --now amazon-cloudwatch-agent
sudo systemctl status amazon-cloudwatch-agent --no-pager
```

Then confirm it's shipping again by checking the CloudWatch Logs group in the AWS console — new events should appear within a minute or two.

**Trigger conditions to re-enable:**
- Upcoming HITRUST / SOC 2 audit and BlackWatch isn't yet the assessor-accepted centralized store.
- Any period where we need CloudWatch-side alarms / dashboards on OpenVPN.
- BW SQS pipeline is degraded and we want CW as a temporary belt-and-suspenders on log capture.

**Consequence while disabled:** OpenVPN logs are no longer being pushed to CloudWatch Logs. They are still captured locally in journald (`journalctl -u openvpn-server@server`) and — critically — BlackWatch still receives OpenVPN auth events and status snapshots via the `blackwatch-vpn-agent` → SQS pipeline. So we do not lose *security* visibility, only the *centralized* copy in CloudWatch. That distinction matters only for the compliance argument, not for detection.

## What was NOT touched

- `blackwatch-agent`, `blackwatch-vpn-agent` — healthy, shipping to SQS, keep as-is.
- `wazuh-agent` — kept for HITRUST compliance evidence.
- `fail2ban`, `firewalld`, `openvpn-server@server`, `amazon-ssm-agent`, `chronyd`, `rsyslog` — untouched.

## Reversal — how to undo everything

The local OpenVPN log file will regrow on its own (openvpn keeps writing to it). The rest:

```bash
# remove the openvpn logrotate rule (return to unbounded growth)
sudo rm /etc/logrotate.d/openvpn

# remove the journald size cap (return to unbounded growth)
sudo rm /etc/systemd/journald.conf.d/00-size.conf
sudo systemctl restart systemd-journald
```

`yum clean all` doesn't need reversal — the metadata rebuilds the next time yum runs.

## Verification after cleanup

```bash
df -h /                                    # expect ~4 GB used vs previous 9.2 GB
free -m                                    # expect ~50 MB more free / less swap in use
journalctl --disk-usage                    # expect ≤200 MB
ls -la /var/log/openvpn.log                # small, freshly created
systemctl status amazon-cloudwatch-agent   # inactive (dead), NOT enabled
systemctl status blackwatch-vpn-agent      # active (running)
systemctl status openvpn-server@server     # active (running)
```

## Related follow-ups (not part of this runbook)

- Amazon Linux 2 EOL was 2026-06-30 — this box is on borrowed time; plan AL2023 migration.
- OpenVPN 2.4.7 is EOL — plan upgrade to 2.6.x during the AL2023 migration.
- `errs=packages` appears on every BW host-agent tick — one collector silently failing; investigate separately.
