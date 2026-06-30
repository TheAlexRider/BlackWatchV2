# ECS service probe — full reference

The canonical document for BlackWatch's ECS service-monitoring module: what
it does, how the per-VPC probe agent runs in Fargate, how status flows
through to the UI + alerts, and how to set up / troubleshoot it.

Sister doc to [`docs/ec2-agent.md`](ec2-agent.md) and [`docs/vpn-agent.md`](vpn-agent.md).
Same push-to-SQS + IAM-auth pattern; ECS-specific differences are the
per-VPC Fargate runner and the SSM-based targets list.

Current probe version: **v1.0** (boto3 SQS+SSM, deterministic IDs, disk
cache fallback, per-failure CloudWatch logging).

---

## 1. What it does

For each VPC you enrol (typically `dev` + `prod`):

1. A single Fargate task (`blackwatch-ecs-probe-<vpc>`) runs in that
   VPC's cluster, reading its target list from SSM Parameter Store.
2. Every `INTERVAL_SECONDS` (default 60) it runs `http_alive` and `tcp`
   checks **in parallel** against every probeable service.
3. Builds one `ecs_probe_report` payload and `SendMessage`s it to a
   per-VPC SQS queue (`bw-ecs-probe-reports-<vpc>`).
4. BlackWatch's `aws_ecs_probe_sqs` connector drains that queue on its
   own schedule, mirrors the SSM target list into the `probe_targets`
   table, and feeds each report through the `ecs.probe` adapter +
   projection (hysteresis, transitions, archive logic).
5. The Services page renders the live picture; the projection emits
   `service.down` / `service.up` / `service.degraded` / `probe.agent.stale`
   transition events that flow through the notification rules.

Outbound from the probe is **IAM-authed AWS API calls only** — no HTTP
to BlackWatch, no bearer tokens, no IP allowlist. The probe doesn't open
any inbound port.

### Probe tiers

| Tier | What it does | Status semantics |
|---|---|---|
| `http_alive` | `GET <url>`. Any HTTP response (2xx/3xx/4xx) = up. 5xx = degraded. Network failure = unknown. | The probe only marks DOWN-style states (`degraded`) when the service *answered improperly*. |
| `tcp` | Open a TCP socket, close. Connected = up. Anything else = **unknown** (we can't distinguish service-down from SG-block from wrong-port). | TCP never reports `down` — only `up` or `unknown`. |
| `ecs_running` | No port to probe. Probe skips. Listed in BW inventory as `unknown` with `aws_desired`/`aws_running` visible. | Future: covered by the `aws_ecs_health` BW-side connector. |

The `unknown` state matters: it's BlackWatch saying "we can't tell" — as
opposed to "this is broken." TCP refused, DNS lookup failed, SG dropped
the packet — these are all indistinguishable from raw TCP, so we don't
fake confidence.

---

## 2. Architecture / pipeline

```
   ┌────────────────────────────────────┐                              ┌─────────────────────────┐
   │  Per-VPC VPC (dev or prod)         │                              │  BlackWatch             │
   │                                    │                              │  (Docker / Lightsail)   │
   │  Fargate task: blackwatch-         │                              │                         │
   │    ecs-probe-<vpc>                 │                              │                         │
   │                                    │                              │                         │
   │  ecs_probe.py (asyncio)            │                              │                         │
   │  ┌───────────────────────────┐     │   ssm:GetParameter           │  aws_ecs_probe_sqs      │
   │  │ every TARGETS_REFRESH_SEC │ ──► │   /blackwatch/ecs-probe/     │   .drain():             │
   │  │  - re-pull targets list   │     │   <vpc>/targets              │                         │
   │  │  - disk-cache fallback    │     │                              │   1. ssm:GetParameter   │
   │  └───────────────────────────┘     │                              │      same SSM key       │
   │  ┌───────────────────────────┐     │                              │      -> upsert          │
   │  │ every INTERVAL_SECONDS    │     │                              │      probe_targets      │
   │  │  - run all checks async   │     │                              │      with tags + sev    │
   │  │  - assemble report        │     │   sqs:SendMessage            │                         │
   │  │  - SendMessage to queue   │ ──► │   bw-ecs-probe-reports-<vpc> │   2. ReceiveMessage     │
   │  │  - log per-failure to     │     │                              │      ingest_payload     │
   │  │    CloudWatch stderr      │     │                              │      target_module=     │
   │  └───────────────────────────┘     │                              │      ecs.probe          │
   │                                    │                              │                         │
   │  Task role:                        │                              │   3. ecs.probe adapter  │
   │   sqs:SendMessage on OWN queue     │                              │      -> service.probe   │
   │   ssm:GetParameter on OWN param    │                              │      .result events     │
   │                                    │                              │                         │
   └────────────────────────────────────┘                              │   4. projection:        │
                                                                       │      hysteresis,        │
   ┌────────────────────────────────────┐                              │      transitions,       │
   │  Your laptop (admin AWS creds)     │                              │      service_status     │
   │                                    │     ssm:PutParameter         │                         │
   │  scripts/ecs_discover.py           │ ──────────────────────────►  │                         │
   │   --emit-ssm                       │                              │   5. /api/services      │
   │  (walks ECS DescribeServices,      │                              │      Services page      │
   │   resolves Cloud Map DNS,          │                              │                         │
   │   writes JSON to SSM)              │                              └─────────────────────────┘
   └────────────────────────────────────┘
```

Why this shape:
- **SQS** is the durable buffer. If BlackWatch is down, reports queue up;
  when BW recovers, the connector drains them. No on-probe spool needed.
- **SSM** is the targets channel. One operator-owned source of truth.
  Update SSM → next probe refresh (within `TARGETS_REFRESH_SEC`) picks
  it up. No probe redeploy.
- **IAM** is the auth boundary. Per-VPC task role scoped to **exactly
  one queue ARN + one parameter ARN**. A popped dev probe can't even
  read prod's target list, let alone write to prod's queue.

---

## 3. Files & paths

### In the BlackWatch repo

| Path | Purpose |
|---|---|
| `scripts/ecs_probe.py` | The probe agent itself. Copied into the Docker image by `setup.ps1`. |
| `scripts/ecs_discover.py` | One-shot CLI: walks ECS, builds the target list, writes to SSM. Run from your laptop. |
| `deploy/ecs/Dockerfile` | Minimal Alpine + boto3 image. |
| `deploy/ecs/setup.ps1` | Per-VPC bootstrap: queue, SSM placeholder, IAM, ECR image, task def, service. Idempotent. |
| `deploy/ecs/trust-policy.json` | `ecs-tasks.amazonaws.com` AssumeRole trust. |
| `deploy/ecs/blackwatch-ecs-probe-policy.json` | Templated IAM policy. `__QUEUE_ARN__` + `__SSM_PARAM_ARN__` substituted per VPC. |
| `blackwatch/modules/ecs_probe.py` | Adapter that turns `ecs_probe_report` payloads into `probe.agent.heartbeat` + `service.probe.result` events. |
| `blackwatch/services/projection.py` | Hysteresis + transition logic. Emits `service.{up,down,degraded}` and `probe.agent.{first_seen,recovered}`. Also tracks `down_since` for archive. |
| `blackwatch/services/staleness.py` | Periodic check: if a probe agent hasn't reported in `STALE_AFTER_SECONDS` (default 180), emit `probe.agent.stale`. |
| `blackwatch/connectors/aws_ecs_probe_sqs.py` | SQS drain + SSM sync. One BW connector per VPC. |
| `blackwatch/sql/010_services.sql` | `probe_targets` + `service_status` + `probe_agent_status` schemas. |
| `blackwatch/sql/019_service_down_since.sql` | Adds `service_status.down_since` for archive timing. |
| `rules/ecs.yaml` | Notification routing rules (notify:critical/high/medium tiers). |
| `blackwatch-ui/app/services/page.tsx` | Services page. Per-VPC tables, Archive panel, sort + counts. |
| `docs/ecs.md` | **This file.** |

### On AWS (created by `setup.ps1`)

| Resource | Naming | Notes |
|---|---|---|
| SQS queue | `bw-ecs-probe-reports-<vpc>` | SSE-SQS encryption (not KMS — KMS-encrypted SQS blocks cross-region writes). 24h MessageRetentionPeriod. |
| SSM parameter | `/blackwatch/ecs-probe/<vpc>/targets` | Advanced tier (8KB max). Holds the JSON list of probeable services. |
| ECR repo | `blackwatch-ecs-probe` | Shared across VPCs — one image, parameterised by env vars. |
| ECS task definition | `blackwatch-ecs-probe-<vpc>` | Fargate, 256 CPU / 512 MB. |
| ECS service | `blackwatch-ecs-probe-<vpc>` | desiredCount=1, `assignPublicIp=ENABLED` (needs IGW egress to reach SQS+SSM regional endpoints). |
| IAM role | `blackwatch-ecs-probe-task-<vpc>` | **Per-VPC** task role. Scoped to one queue + one param. |
| IAM role | `blackwatch-ecs-probe-exec` | Shared. Just `AmazonECSTaskExecutionRolePolicy` for image pulls. |
| IAM policy | `blackwatch-ecs-probe-<vpc>` | Per-VPC. Re-created each `setup.ps1` run so ARN changes propagate. |
| CloudWatch log group | `/blackwatch/ecs-probe/<vpc>` | Probe stdout/stderr. |

### On the BlackWatch Lightsail box

| Item | Notes |
|---|---|
| AWS profile | `blackwatch` — mapped to access keys for IAM user `blackwatch-sqs-reader` (from the IAM module setup). |
| IAM perms needed | `sqs:ReceiveMessage` + `sqs:DeleteMessage` + `sqs:DeleteMessageBatch` + `sqs:GetQueueAttributes` on each probe queue ARN; `ssm:GetParameter` on each targets parameter ARN. Both granted via managed policy `bw-read-ecs-probe-queues`. |
| Connectors | One per VPC: `aws_ecs_probe_sqs` type, name `ECS probe reports (<vpc>)`. |

---

## 4. Configuration

### Probe task env (set by `setup.ps1` on the task definition)

| Variable | Example | Purpose |
|---|---|---|
| `PROBE_VPC` | `dev` | Label this probe reports under. Also used to derive deterministic target IDs. **Required**. |
| `SQS_QUEUE_URL` | `https://sqs.us-west-1.amazonaws.com/095899260107/bw-ecs-probe-reports-dev` | The probe's per-VPC report queue. **Required**. |
| `SSM_PARAM_NAME` | `/blackwatch/ecs-probe/dev/targets` | The probe's per-VPC targets parameter. **Required**. |
| `AWS_DEFAULT_REGION` | `us-west-1` | Region for SQS + SSM. |
| `INTERVAL_SECONDS` | `60` | Probe cycle interval. |
| `TARGETS_REFRESH_SEC` | `300` | How often to re-pull SSM. Lower = faster reaction to discovery, more SSM calls. |
| `DEFAULT_TIMEOUT_SEC` | `5` | Per-check timeout fallback (each target can override via `config.timeout_seconds`). |
| `TARGETS_CACHE_PATH` | `/tmp/bw-probe/targets.json` | Disk cache fallback used if SSM is unreachable on cold start. |
| `AGENT_VERSION` | `1.0` | Reported in heartbeat. |

### Discovery script flags

```
python -m scripts.ecs_discover \
  --cluster <cluster>:<vpc>  [--cluster ... ]  \
  --region us-west-1 \
  [--emit-ssm]
```

| Flag | Purpose |
|---|---|
| `--cluster CLUSTER:VPC` | Repeatable. Maps an ECS cluster to a VPC label. |
| `--region` | AWS region of the clusters. |
| `--emit-ssm` | Without this flag the script prints what it *would* write. With it, the targets list is committed to `/blackwatch/ecs-probe/<vpc>/targets`. |

### Connector config (stored in BW's `connectors` table)

```json
{
  "queue_url": "https://sqs.us-west-1.amazonaws.com/095899260107/bw-ecs-probe-reports-dev",
  "aws_region": "us-west-1",
  "aws_profile": "blackwatch",
  "vpc": "dev",
  "ssm_targets_param": null,
  "interval_seconds": 60,
  "wait_seconds": 10,
  "max_batches": 5
}
```

`ssm_targets_param` defaults to `/blackwatch/ecs-probe/<vpc>/targets` if
null. The connector overrides each message body's `vpc` field with
`cfg.vpc` before ingest — even a compromised probe with queue-write
access can't forge a report for a different VPC.

---

## 5. Setup — first time, per VPC

### One-time prep (laptop, admin AWS creds)

1. **Grant the BW reader user perms** to receive from the new queues
   and read the new SSM params. One-off, managed policy approach:

   ```powershell
   '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["sqs:ReceiveMessage","sqs:DeleteMessage","sqs:DeleteMessageBatch","sqs:GetQueueAttributes"],"Resource":["arn:aws:sqs:us-west-1:<acct>:bw-ecs-probe-reports-dev","arn:aws:sqs:us-west-1:<acct>:bw-ecs-probe-reports-prod"]},{"Effect":"Allow","Action":["ssm:GetParameter"],"Resource":["arn:aws:ssm:us-west-1:<acct>:parameter/blackwatch/ecs-probe/dev/targets","arn:aws:ssm:us-west-1:<acct>:parameter/blackwatch/ecs-probe/prod/targets"]}]}' | Out-File -FilePath "$env:TEMP\bw-ecs-readers.json" -Encoding ascii; aws iam create-policy --policy-name bw-read-ecs-probe-queues --policy-document "file://$env:TEMP/bw-ecs-readers.json" --query Policy.Arn --output text | % { aws iam attach-user-policy --user-name blackwatch-sqs-reader --policy-arn $_ }
   ```

### Per-VPC bootstrap (laptop, run twice — once for dev, once for prod)

1. **Discover** subnets, security groups, and the target list. First
   without `--emit-ssm` so you can review:

   ```powershell
   python -m scripts.ecs_discover --cluster development-cluster:dev --cluster production-cluster:prod --region us-west-1
   ```

2. **Run `setup.ps1`** with the env block discovery printed:

   ```powershell
   $env:VPC="dev"; $env:VPC_REGION="us-west-1"; $env:CLUSTER="development-cluster"; $env:SUBNET_IDS="subnet-...,..."; $env:SECURITY_GROUP_IDS="sg-...,..."; .\deploy\ecs\setup.ps1
   ```

   This creates the queue, the SSM placeholder, the IAM role, builds + pushes
   the probe image, registers the task def, and creates the ECS service.

3. **Populate the targets list** in SSM:

   ```powershell
   python -m scripts.ecs_discover --cluster development-cluster:dev --cluster production-cluster:prod --region us-west-1 --emit-ssm
   ```

4. **On the BlackWatch box**, register the per-VPC connector (once per VPC):

   ```bash
   docker compose exec app python -c "from blackwatch import db, storage; import uuid; db.init_pool(); storage.upsert_connector(str(uuid.uuid4()), 'ECS probe reports (dev)', 'aws_ecs_probe_sqs', {'queue_url': 'https://sqs.us-west-1.amazonaws.com/<acct>/bw-ecs-probe-reports-dev', 'aws_region': 'us-west-1', 'aws_profile': 'blackwatch', 'vpc': 'dev', 'interval_seconds': 60, 'wait_seconds': 10, 'max_batches': 5})"
   ```

5. In the BW UI's Connectors page, click **Test** on the new connector — it
   should turn green / `verified: true`. Then click **Enable**. The scheduler
   picks it up on the next 10s tick.

After both VPCs are wired, the Services page should populate within ~2
probe cycles (~2 minutes).

---

## 6. Operational tasks

### Refreshing the targets list (e.g. after adding/removing ECS services)

Discovery is idempotent — same `(vpc, name)` produces the same UUID via
`uuid5(NAMESPACE_URL, "bw-ecs-probe::<vpc>::<name>")`, so re-running
doesn't reset history.

```powershell
python -m scripts.ecs_discover --cluster development-cluster:dev --cluster production-cluster:prod --region us-west-1 --emit-ssm
```

Probe picks up new targets within `TARGETS_REFRESH_SEC` (default 5 min).
BW's connector picks up new tags within `interval_seconds` (default 60s).
No restart needed.

### Updating the probe code

Probe code lives in an ECR image, baked at `setup.ps1` time. To roll out
new probe code:

```powershell
$env:VPC="dev"; $env:VPC_REGION="us-west-1"; $env:CLUSTER="development-cluster"; $env:SUBNET_IDS="...,..."; $env:SECURITY_GROUP_IDS="...,..."; .\deploy\ecs\setup.ps1
$env:VPC="prod"; ... ; .\deploy\ecs\setup.ps1
```

`setup.ps1` rebuilds + pushes the image and forces a new deployment on
the ECS service. Each takes ~30s (Docker layer cache makes incremental
builds fast).

### Updating BlackWatch-side code

Standard pull + rebuild on Lightsail:

```bash
cd /opt/blackwatch && git pull && docker compose up -d --build app blackwatch-ui
```

Note: rebuilding **just** `app` is not enough when UI code changes —
`blackwatch-ui` is a separate container.

### Tailing probe logs

From the laptop (not from Lightsail — Lightsail's instance role is in a
different AWS account):

```powershell
aws logs tail /blackwatch/ecs-probe/dev --follow --region us-west-1
```

Every cycle shows one line per non-up result:

```
  unknown rabbitmq-lb (tcp): [Errno 111] Connection refused
  degraded auth-api (http_alive): HTTP 503
reported vpc=dev results=26 up=24 down=0 degraded=1
```

---

## 7. How status flows

### Per-target lifecycle

1. **Discovery** writes `(name, tier, config, tags{env,role,aws_desired,aws_running}, enabled)` to SSM.
2. **Connector** syncs that to `probe_targets` row with re-derived severity.
3. **Probe** reads SSM, runs check, sends report to SQS.
4. **Adapter** turns each report result into a `service.probe.result` event.
5. **Projection** applies hysteresis:
   - `up`: `consecutive_success` += 1; `consecutive_fails` = 0
   - `down`/`degraded`: `consecutive_fails` += 1; `consecutive_success` = 0
   - `unknown`: both counters reset to 0 (unknown is indeterminate)
6. **Effective status** flips when:
   - `up` after `UP_THRESHOLD` (1) consecutive successes
   - `down`/`degraded` after `DOWN_THRESHOLD` (2) consecutive failures
   - `unknown` immediately (no hysteresis — unknown IS the confidence level)
7. **Transition** emits `service.{up,down,degraded}` event with rich `extra.message`.
8. **`down_since`** is set on the UP→DOWN edge, cleared on DOWN→UP. Used by the archive predicate.

### Effective status priority on the API side

When the API renders a row:
- `enabled=false` + `aws_desired=0` → `disabled` (sent to Archive)
- `enabled=false` + `aws_desired>0` → `unknown` (lives in VPC table, latency/fails dashed)
- `enabled=true` → whatever the projection wrote (`up`/`down`/`degraded`/`unknown`)

### Archive predicate

A row is archived if **any** of:
- `status == "disabled"` (operator-stopped service)
- `status in ("down","degraded")` and `down_since >= 7 days`
- `tags.aws_desired == "0"` (safety fallback before next sync)

Archived rows show in a single collapsible panel at the bottom of the
Services page (not per-VPC). Unarchive happens automatically when the
service comes back up.

### Sort order in each VPC table

```
DOWN  →  degraded  →  unknown (yellow)  →  up  →  (disabled lives in archive)
```

within each status, by tier alpha, then name alpha.

---

## 8. Notifications

### Routing tags

Rules in `rules/ecs.yaml` are tagged with `notify:critical` / `notify:high` /
`notify:medium`. Those tags determine which Slack/Discord/Teams channel
the event lands in.

| Action | Default rule | Notify tier |
|---|---|---|
| `service.down` (prod) | `service-down-prod-critical` | `notify:critical` |
| `service.down` (non-prod) | `service-down` | `notify:high` |
| `service.degraded` | `service-degraded` | `notify:medium` |
| `service.up` | `service-up` | (informational — no notify tag) |
| `probe.agent.stale` | `probe-agent-stale` | `notify:critical` |
| `probe.agent.recovered` | `probe-agent-recovered` | (informational) |
| `probe.agent.first_seen` | `probe-agent-first-seen` | (informational) |

### Friendly message format

Every transition event sets `extra.message` so notifications read as
English, not action names:

| Event | Slack/Discord text |
|---|---|
| `service.down` | `🚨 prod: ai-gateway-api went DOWN (HTTP timeout) on api _(severity: critical)_` |
| `service.degraded` | `🟡 dev: web-backend is degraded (HTTP 503) on api _(severity: medium)_` |
| `service.up` | `🔔 prod: ai-gateway-api recovered (UP)` |
| `probe.agent.stale` | `🚨 prod: probe agent went silent — no reports for 6 min (whole VPC's probe-based monitoring is offline)` |

The "on `role`" suffix is from the channel template, which appends
target context. The headline is constructed by `_friendly_service_message`
in `blackwatch/services/projection.py`.

### Customising

- **Re-tier:** edit `rules/ecs.yaml` (rebuild app: `docker compose up -d --build app`).
- **Suppress one service:** add a per-target suppression to `rules/suppression.yaml`.
- **Change wording:** edit `_friendly_service_message` in the projection.
- **Per-channel template:** /notifications → pick a different preset (friendly / detailed / compact) or write a custom Jinja template.

---

## 9. IAM model

Minimum-privilege design — every actor gets exactly what it needs.

### Probe task role (`blackwatch-ecs-probe-task-<vpc>`)

```json
{
  "Statement": [
    {"Effect":"Allow","Action":"sqs:SendMessage","Resource":"<own-queue-arn>"},
    {"Effect":"Allow","Action":"ssm:GetParameter","Resource":"<own-param-arn>"}
  ]
}
```

Two verbs, two ARNs. Dev probe can't read prod's targets; prod probe
can't write to dev's queue. **No** `ecs:Describe*` — the probe doesn't
enumerate the cluster (that recon surface was a deliberate cut; we
chose env-var-style targets over self-discovery).

### BlackWatch reader user (`blackwatch-sqs-reader`)

Managed policy `bw-read-ecs-probe-queues`:
- `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:DeleteMessageBatch`, `sqs:GetQueueAttributes` on both probe queue ARNs
- `ssm:GetParameter` on both targets parameter ARNs

Shares the user with the IAM module's CloudTrail-reader inline policy
(`read-cloudtrail-queues`). Two policies on one user, no conflict.

### Discovery (laptop)

Uses your admin AWS creds. Needs:
- `ecs:ListServices`, `ecs:DescribeServices`, `ecs:DescribeTaskDefinition`
- `ec2:DescribeSubnets`, `ec2:DescribeSecurityGroups`
- `servicediscovery:GetService`, `servicediscovery:GetNamespace`
- `ssm:PutParameter` for `/blackwatch/ecs-probe/*`

All standard read-only ECS perms except the SSM write.

---

## 10. Troubleshooting

### "26 services in dev but I have 31 in AWS"

`ecs_running` tier services (no exposed port) are included in BW
inventory as **unknown** (yellow). The discovery summary reports them in
the breakdown:

```
dev: 31 services [ecs_running=5, http_alive=19, tcp=7]
```

### "All services showing DOWN with ~5ms latency"

DNS failure pattern. Probably means:
- Service has no Cloud Map registration → bare hostname in the target
  config → DNS resolution fails. Re-run discovery; it should mark these
  `enabled=false` and they'll show as `unknown` (yellow) instead.
- The probe's VPC isn't associated with the relevant private hosted zone.

Check what URL/host the probe is hitting:

```powershell
aws ssm get-parameter --name /blackwatch/ecs-probe/dev/targets --region us-west-1 --query "Parameter.Value" --output text | python -c "import json,sys; ts=json.load(sys.stdin); [print(t['name'],'->',t['config']) for t in ts]"
```

Expected hostnames have a dot (`web-backend.dev.local`). Bare names
(`web-backend`) are the symptom.

### "rabbitmq-lb stays unknown (TCP refused)"

Three possibilities, listed by likelihood:
1. Probe's SG doesn't have egress to the rabbitmq SG on that port.
2. RabbitMQ isn't listening on that port (e.g., TLS port 5671 when only
   5672 is active).
3. The probe is in a public subnet but the rabbitmq LB only allows
   traffic from specific private subnets.

Check probe stderr in CloudWatch — the error string narrows it down:
`Connection refused` = nothing listening, `timed out` = packet dropped
(SG/NACL), `Name or service not known` = DNS.

### "SSM parameter too large (>8KB)"

You've crossed the SSM Advanced tier ceiling. Options:
- Drop unused tags (`tags.env` already stripped — see `_ssm_payload`).
- Move to S3 (no size limit, same IAM-controlled storage model). See
  the `s3_targets_*` fields on `AwsEcsProbeSqsConfig` for the migration
  shape (currently unset; switching to S3 is a code change, not a
  config change).
- Split into multiple parameters per VPC.

Today's payload sits around 7KB for ~30 services. ~2x headroom.

### "Probe agent showing stale immediately after deploy"

`probe.agent.stale` fires after `STALE_AFTER_SECONDS` (default 180) of
no heartbeat. New probes report on first cycle — if it's stale
immediately, the task probably isn't running. Check:

```powershell
aws ecs describe-services --cluster development-cluster --services blackwatch-ecs-probe-dev --region us-west-1 --query "services[].{running:runningCount,desired:desiredCount,events:events[0:3].message}" --output table
```

Common causes: image pull failure (check ECR), IAM trust policy missing
ECS, subnet has no IGW route (need `assignPublicIp=ENABLED` AND a
public subnet).

### "Connector verify-on-test fails"

The BW reader user is missing perms on the queue or the param. The exact
error text tells you which:
- `AccessDenied ... ReceiveMessage` → missing SQS perms
- `AccessDenied ... GetParameter` → missing SSM perms

Re-run the IAM policy snippet from step 5.1.

### "Services keep flapping between up and down"

Hysteresis is set to `DOWN_THRESHOLD=2`, `UP_THRESHOLD=1`. If a service
genuinely takes >2 cycles (2 minutes) to recover from probes, the
projection will see legitimate transitions. To reduce flapping:
- Increase `DOWN_THRESHOLD` in `blackwatch/services/projection.py`
  (catches more flaps but slower to fire real-down).
- Tune the target's `timeout_seconds` in the SSM payload — if requests
  are timing out near the limit, raise it.

---

## 11. What's intentionally NOT included

- **Probe self-discovery via `ecs:Describe*`** — deliberately not done.
  Read-only ECS perms expose service names, images, env vars, network
  topology — too much recon surface for a process that lives inside a
  VPC. Targets come from operator-driven discovery + SSM instead.
- **Auto-recovery of disabled services** — once `enabled=false` is
  written (by discovery), the probe skips. If you fix the underlying
  issue (add Cloud Map registration, bring `desiredCount` back to >0),
  re-run discovery — it'll re-detect probeable and flip enabled back.
- **HTTP body content checks** — probe only checks that the service
  *answers*. If you need response-content validation, build a custom
  health endpoint and aim the probe at it; the probe accepts any
  non-5xx response as up.
- **TLS validation** — TCP probes are raw sockets. They'll succeed
  against a TLS port even if the cert is expired. The cert-expiry
  module (`cert_probe`) is the right tool for that.
