# ECS service probe — setup

Two-piece monitoring for ECS Fargate services with **zero changes to monitored
containers**. Built around the constraint that:

- 5 of your services already have `healthCheck` blocks in their task defs (AWS
  reports HEALTHY/UNHEALTHY/UNKNOWN) — we read what AWS knows.
- The other ~20 don't, and you don't want to add health checks one-by-one —
  we probe them ourselves from inside the VPC.

## How it splits

| Part | What | Where | How |
|---|---|---|---|
| **A. AWS-side reader** | Reads `containers[].healthStatus` for `ecs_health` tier; reads smoothed `runningCount` for `ecs_running` tier | BlackWatch (Lightsail) | New connector type `aws_ecs_health` per VPC |
| **B. In-VPC probe agent** | HTTP GET / + TCP open from inside the VPC | One Fargate task per VPC | This setup script |

Both pieces feed events through the **same** `ecs.probe` adapter and projection,
so downstream rules / notifications / UI are a single code path.

## What gets monitored without per-container work

- **HTTP services**: `GET /` — any response (200, 30x, 401, 403, 404) = up. No
  `/health` endpoint needed.
- **TCP services / databases**: open a socket. Up if it accepts.
- **Services with healthCheck already configured**: AWS healthStatus, via Part A.
- **Workers** (no port, no healthCheck): smoothed `runningCount` via Part A.
  Survives Fargate Spot interruptions.

## 1. BlackWatch side — set up tokens and add the AWS reader

In your BlackWatch container's env, generate a per-VPC token and wire both maps:

```bash
# Choose a strong random token per VPC, e.g.
TOKEN_DEV=$(openssl rand -hex 24)
TOKEN_PROD=$(openssl rand -hex 24)

# BLACKWATCH_TOKENS: token -> module (so /ingest accepts the probe agent's reports)
BLACKWATCH_TOKENS="devtoken:generic,${TOKEN_DEV}:ecs.probe,${TOKEN_PROD}:ecs.probe"

# BLACKWATCH_PROBE_VPCS: token -> VPC label (so /api/probes/targets returns the
# right target list — the agent can't accidentally probe another VPC)
BLACKWATCH_PROBE_VPCS="${TOKEN_DEV}:dev,${TOKEN_PROD}:prod"
```

Restart BlackWatch to apply, then in the UI go to **Settings → Add ECS health
connector** and create one per VPC (region + profile + vpc label).

## 2. Probe targets — paste the bulk import

In the UI, go to **Services → Manage targets → Bulk import (YAML)** and paste
your full list. Example for the dev VPC:

```yaml
# ones AWS already has an opinion on (healthCheck in task def) — read by Part A
- name: internal-api-server
  vpc: dev
  tier: ecs_health
  config: {cluster: dev-cluster, service: internal-api-server}
  severity_when_down: critical
  tags: {env: dev, role: api}

- name: document-llm-api
  vpc: dev
  tier: ecs_health
  config: {cluster: dev-cluster, service: document-llm-api}
  severity_when_down: high
  tags: {env: dev}

# HTTP probe from the in-VPC agent (no /health required — GET /)
- name: ai-gateway-api
  vpc: dev
  tier: http_alive
  config: {url: "http://ai-gateway-api.internal/", timeout_seconds: 5}
  severity_when_down: high
  tags: {env: dev, role: api}

- name: chromadb
  vpc: dev
  tier: http_alive
  config: {url: "http://chromadb.internal:8000/api/v1/heartbeat", timeout_seconds: 5}
  severity_when_down: high
  tags: {env: dev}

# TCP probe (databases — no HTTP)
- name: database-logs
  vpc: dev
  tier: tcp
  config: {host: database-logs.internal, port: 5432, timeout_seconds: 3}
  severity_when_down: high
  tags: {env: dev}

# Workers — smoothed runningCount (read by Part A, no in-VPC probe needed)
- name: ai-gateway-worker-text
  vpc: dev
  tier: ecs_running
  config: {cluster: dev-cluster, service: ai-gateway-worker-text}
  severity_when_down: medium
  tags: {env: dev, role: worker}
```

## 3. Deploy the probe agent (per VPC)

```powershell
$env:VPC = "dev"
$env:VPC_REGION = "us-west-1"
$env:BLACKWATCH_URL = "https://blackwatch.example.com"
$env:BLACKWATCH_TOKEN = "<paste the TOKEN_DEV from step 1>"
$env:SUBNET_IDS = "subnet-aaa,subnet-bbb"          # private subnets in this VPC
$env:SECURITY_GROUP_IDS = "sg-xxx"                 # outbound 443 to internet + intra-VPC
$env:CLUSTER = "dev-cluster"

cd deploy\ecs
.\setup.ps1
```

This creates:
- ECR repo `blackwatch-ecs-probe` (shared across VPCs)
- IAM task role `blackwatch-ecs-probe-task` with read-only ECS+ELB perms
- ECS task definition `blackwatch-ecs-probe-{vpc}`
- ECS service `blackwatch-ecs-probe-{vpc}` running 1 Fargate task

Repeat for `prod`.

## 4. Verify

Within ~60 s the new VPC agent registers — visit **`/ui/services`** and you should see:

- The per-VPC agent in the top card (● reporting)
- One row per target with current status (up / down / degraded / unknown)
- Tags column reflecting your bulk import (`env=dev`, `role=api`, etc.)

Watch logs while the first cycle runs:
```
aws logs tail /blackwatch/ecs-probe/dev --follow --region us-west-1
```
Expect `reported vpc=dev results=N up=M down=0 degraded=0`.

## What this gives you vs. doesn't

✓ Zero container changes
✓ Zero AWS-native alarm cost
✓ Single per-VPC agent, all services covered through one config point
✓ Hysteresis (2 consecutive bad probes to declare down, 1 good to recover)
✓ Per-target severity + tag-based rule routing (prod down = critical)

✗ Stuck-but-running workers (no port, no healthCheck) are still invisible. The
  only way to fix that is a queue-depth proxy check or a container-side change.
