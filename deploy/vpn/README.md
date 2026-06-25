# OpenVPN agent — setup

Replaces the SSH-pull `openvpn_ssh` connector with a push agent on the OpenVPN
box (same pattern as the EC2 host agent). No inbound SSH to the VPN box, no key
management, no fail2ban interference.

Flow: **`vpn_agent.py` on the OpenVPN box → SQS (instance role) → BlackWatch
polls → existing `vpn.openvpn` adapter**.

Runs alongside the EC2 host agent (`blackwatch-agent.service`) — independent
unit, independent queue, independent IAM policy.

---

## 1. Create the AWS side (once)
```powershell
cd deploy\vpn
$env:REGION = "us-west-1" ; .\setup.ps1
```
Prints:
- **VPN queue URL** (`blackwatch-vpn-agents`)
- **Agent send policy ARN** (`blackwatch-vpn-agent-send`)
- Extends the existing `blackwatch-sqs-reader` user with read access to the new queue
  (so the BlackWatch container's `blackwatch` profile already works — no new creds).

## 2. Let the OpenVPN box send to the queue
Attach the agent send policy to the OpenVPN box's instance role (in addition to
`blackwatch-ec2-agent-send`, which it already has):
```bash
aws iam attach-role-policy --role-name <OPENVPN_INSTANCE_ROLE> \
  --policy-arn arn:aws:iam::<ACCT>:policy/blackwatch-vpn-agent-send
```

## 3. Install the agent (run as root on the OpenVPN box)
```bash
scp scripts/vpn_agent.py deploy/vpn/install-vpn-agent.sh ec2-user@<openvpn-box>:/tmp/
ssh ec2-user@<openvpn-box>
sudo BLACKWATCH_VPN_SQS_URL="<queue url from step 1>" AWS_REGION="us-west-1" \
     bash /tmp/install-vpn-agent.sh
```
Optional env overrides (defaults are correct for the current box):
- `OPENVPN_UNIT` (default `openvpn-server@server`)
- `OPENVPN_STATUS_FILE` (default `/var/log/openvpn/status.log`)
- `SERVER_NAME` (default `openvpn` — the logical id shown in the UI)
- `INTERVAL` (default `60`)

Verify: `journalctl -u blackwatch-vpn-agent -f` shows `reported server=openvpn state=active …`.

## 4. Wire BlackWatch (UI)
Settings → **Add SQS connector**:
- **Target module** = `vpn.openvpn`
- **SQS queue URL** = the VPN queue URL from step 1
- **Region** = `us-west-1`, **Profile** = `blackwatch`
→ **Test** → **Enable**.

## 5. Parallel run, then cutover
For ~24 h, leave the existing `openvpn_ssh` connector enabled too. Both feed the
same adapter; auth events dedup by deterministic event_id (journal cursor),
service-health / status-snapshot are projection-only so no duplicate storage.

After parity is confirmed (same `vpn.session.start/end`, same auth counts,
same `vpn.service.up/down` transitions):
1. UI → Settings → disable the `openvpn_ssh` connector.
2. (Optional, separate task) delete the SSH key mount + the
   `openvpn_ssh` connector code + the `infra_openvpn_host.md` SSH section.

---

## What you lose / gain vs. SSH
- **Gain**: no inbound SSH to a security-critical box; no key perm hacks; survives
  fail2ban; survives BlackWatch restarts (events spool in SQS); survives VPN
  outages (agent talks to SQS over public AWS endpoints, not the tunnel); journal
  cursor lets us reduce the lookback window without missing events later.
- **Lose**: nothing functional — the adapter consumes the same fields. The agent
  ships a slightly richer payload (`agent_version`, `host.instance_id`,
  `uptime_seconds`) that the adapter now stamps onto the `vpn.service.health`
  heartbeat extras.
