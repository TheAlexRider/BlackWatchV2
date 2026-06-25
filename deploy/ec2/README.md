# EC2 host monitoring — setup (Phase A)

Flow: **reporter agent on each EC2 → SQS (via instance role) → BlackWatch polls**.
No SSH, no inbound, no stored creds. Phase A covers **SSH/sudo access attempts +
heartbeat** (with staleness alerting); snapshots/FIM/persistence come in later phases.

## 1. Create the AWS side (once)
```powershell
cd deploy\ec2
$env:REGION = "us-west-1" ; .\setup.ps1
```
Prints the **agent queue URL** and the **agent policy ARN** (`blackwatch-ec2-agent-send`),
and extends the `blackwatch-sqs-reader` user to poll the queue.

## 2. Let each EC2 send to the queue
Attach the **agent policy** to each instance's IAM role:
```bash
# find the role behind the instance's profile, then attach:
aws iam attach-role-policy --role-name <INSTANCE_ROLE> \
  --policy-arn arn:aws:iam::<ACCT>:policy/blackwatch-ec2-agent-send
```
(If an instance has no role, create one + instance profile and associate it — live, no reboot.)

## 3. Install the agent on each EC2 (run as root)
Copy the repo's `scripts/` + `deploy/` over (or just `scripts/ec2_agent.py`), then:
```bash
sudo BLACKWATCH_SQS_URL="<queue url from step 1>" AWS_REGION="us-west-1" bash deploy/ec2/install-agent.sh
```
Verify: `journalctl -u blackwatch-agent -f` should show `reported instance=i-... auth_lines=N`.

## 4. Wire BlackWatch (UI)
Settings → **Add SQS connector**:
- **Target module** = `ec2.host`
- **SQS queue URL** = the agent queue URL
- **Region** = `us-west-1`, **Profile** = `blackwatch`
→ **Test** → **Enable**.

(The `blackwatch-sqs-reader` user already has read access from step 1, mounted as the
`blackwatch` profile — same credential the CloudTrail connector uses.)

## 5. Verify
Open **/ui/hosts** — your instances appear as **reporting**. SSH into one (or run `sudo`),
and within ~1–2 min the login shows under "Recent access". Stop the agent
(`systemctl stop blackwatch-agent`) and after ~3 min you'll get a **host.agent.stale** (high) alert.
