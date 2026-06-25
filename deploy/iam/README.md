# IAM / CloudTrail module — AWS setup (your side)

Flow: **CloudTrail → EventBridge (filter) → Lambda (forward) → SQS → BlackWatch polls SQS**.
Only high-value events are forwarded (see `eventbridge-pattern.json`), so volume —
and cost — stay tiny. Management events + EventBridge default bus + a small Lambda
+ SQS are all within AWS free tiers in practice.

## Prerequisites
- AWS CLI v2, authenticated with admin-ish creds (this **creates** infra).
- A CloudTrail trail already logging **management events** (the free first trail).

## Option A — one script (recommended)
```bash
REGION=us-east-1 bash deploy/iam/setup.sh
```
It creates the SQS queue (+ DLQ), the forwarder Lambda, the EventBridge rule, and a
least-privilege IAM user, then prints the **Queue URL** and an **access key**.

## Then wire BlackWatch (UI, no terminal)
1. Put the printed access key into an AWS profile on your PC — `~/.aws/credentials`:
   ```ini
   [blackwatch]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   ```
2. Mount it into the container — uncomment in `docker-compose.yml`:
   ```yaml
   - C:\Users\<you>\.aws:/root/.aws:ro
   ```
   then `docker compose up --build -d`.
3. In BlackWatch → **Settings → Add AWS CloudTrail (SQS) connector**:
   - **Queue URL** = the printed URL
   - **Region** = your region
   - **AWS profile** = `blackwatch`
   - **Poll interval** = 60s
4. Click **Test**. On success it verifies → click **Enable**. Done — IAM events now flow.

## Option B — manual (console)
1. **SQS**: create queue `blackwatch-cloudtrail` (+ a DLQ with maxReceiveCount 5).
2. **Lambda**: create a Python 3.12 function from `lambda_forwarder.py`, env var
   `QUEUE_URL`, and grant it `sqs:SendMessage` on the queue.
3. **EventBridge**: create a rule with the pattern in `eventbridge-pattern.json`,
   target = the Lambda.
4. **IAM user** for BlackWatch with the policy in `blackwatch-sqs-read-policy.json`
   (replace REGION/ACCOUNT_ID); create an access key.
5. Wire BlackWatch as in "Then wire BlackWatch" above.

## Verify end-to-end
Do something benign that the filter matches (e.g. create + delete a throwaway IAM
user, or just sign in to the console). Within ~1–2 min it should appear in
BlackWatch **Events** (category `iam`/`auth`) after the next poll.
