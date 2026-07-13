# Threat Hunter — plan

**Status:** Design. Not implemented.
**Position in BW:** Second tier alongside the ingest pipeline. This is the on-demand
investigation surface. It does NOT replace the pipeline — the pipeline stays as
the always-on detector; the hunter answers the questions the pipeline raises.

## What it is

A read-only tool in BW that runs CloudWatch Logs Insights queries against any
configured AWS log group, on operator demand. Given an indicator (IP, user,
ARN, request ID, hostname), it fans out queries across every configured source
in parallel and answers "where else has this appeared?"

Zero ingest pipeline. Zero persisted log content. Every hunt is a fresh
CloudWatch query.

## Why

Building a per-source ingest pipeline (Lambda → SQS → BW → Postgres) makes
sense for **ambient detection** — bursts, first-seen, scanner UA, rules. It
does not make sense for **investigation**, where the operator wants full
fidelity across every log source AWS holds.

CloudWatch already collects everything: CloudTrail, API Gateway access logs,
RDS logs, VPC Flow Logs, Lambda logs, ECS task logs, ALB access logs, EKS,
custom app logs. Instead of building an ingest path for each, BW queries
CloudWatch directly and displays the answer.

## Design principles

1. **Read-only against AWS.** No writes, no put-*, no state mutations.
2. **Never persist log content.** Query results render in the operator's
   browser, then disappear. Cache only aggregate counts, not lines.
3. **PHI-safe by construction.** Because BW never persists lines, log groups
   containing patient/physician identifiers (API Gateway paths, application
   audit logs) are safe to query. AWS is the BAA-covered custodian; BW is a
   transparent proxy.
4. **Cost guardrails first.** Every query shows estimated GB scanned before
   execution. Hard cap on time range. Rate-limit per operator.
5. **One source of truth for hunter config.** `hunter_sources` table lists
   every queryable log group. Adding a new source is an SQL insert.

## Cost model

- CloudWatch Logs API requests (StartQuery, GetQueryResults, DescribeLogGroups,
  FilterLogEvents) — **no per-request charge**.
- Logs Insights query execution — **$0.005 per GB scanned**.
- CloudWatch Live Tail (deferred, phase 3) — **$0.01 per minute per session**.

A targeted single-IP query over 24h against one log group typically scans
under 100MB → sub-cent. Reckless "scan 30 days across every log group" hits
$1-10 per query. Guardrails below.

## What is NOT in scope

- No detection rule engine — that's the pipeline.
- No alerting — the hunter is human-driven only.
- No stateful correlation (first-seen, burst counters) — that lives in
  Postgres via the pipeline.
- No writes to AWS — no log group creation, no query saving to AWS. Save
  queries in BW's own DB if needed.

## Architecture

```
operator
   │
   ▼
BW /hunter (Next.js)
   │  POST /hunter/query { ioc_type, ioc_value, hours, sources[] }
   ▼
BW FastAPI (blackwatch/hunter/)
   │  fan-out per source
   ▼
boto3.client("logs")  ── StartQuery ──► CloudWatch Logs Insights
                       ◄── GetQueryResults (poll every 500ms)
   │
   ▼ aggregate + render
operator's browser
```

No Lambda. No SQS. No Kinesis. No new Postgres tables for log content.
One table for hunter source config + one for saved queries.

## Schema

```sql
-- 028_hunter.sql

CREATE TABLE hunter_sources (
  id             text PRIMARY KEY,          -- 'aws.rds', 'aws.api_gw', 'aws.cloudtrail'
  display_name   text NOT NULL,
  log_group_name text NOT NULL,             -- CloudWatch log group ARN or name
  region         text NOT NULL,
  account_id     text NOT NULL,
  aws_profile    text,                       -- optional; falls back to instance role
  ioc_field_map  jsonb NOT NULL,             -- {"ip": "$.remoteAddr", "user": "$.principal", ...}
  default_fields text[] NOT NULL,            -- fields to project by default in Insights query
  enabled        boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE hunter_saved_queries (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  description    text,
  ioc_type       text NOT NULL,              -- 'ip', 'user', 'arn', 'request_id', 'hostname'
  ioc_value      text NOT NULL,
  sources        text[] NOT NULL,            -- references hunter_sources.id
  hours          int NOT NULL DEFAULT 24,
  created_by     text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
```

## API

### `POST /hunter/query`

```json
{
  "ioc_type":  "ip",
  "ioc_value": "52.9.243.84",
  "sources":   ["aws.api_gw", "aws.rds", "aws.cloudtrail"],
  "hours":     24
}
```

Response (streams as each source completes; consider SSE):

```json
{
  "ioc": { "type": "ip", "value": "52.9.243.84" },
  "range_hours": 24,
  "started_at": "2026-07-12T14:22:00Z",
  "completed_at": "2026-07-12T14:22:08Z",
  "estimated_gb_scanned": 0.12,
  "cost_estimate_usd": 0.0006,
  "results": [
    {
      "source": "aws.api_gw",
      "matches": 63,
      "first_seen": "2026-07-11T09:00:00Z",
      "last_seen":  "2026-07-12T14:20:11Z",
      "sample_lines": [ /* up to 20 raw log lines */ ]
    },
    {
      "source": "aws.rds",
      "matches": 42,
      "first_seen": "...",
      "last_seen":  "...",
      "sample_lines": [ ... ]
    },
    {
      "source": "aws.cloudtrail",
      "matches": 0
    }
  ]
}
```

### `GET /hunter/sources`

Returns enabled sources for the UI dropdown.

### `POST /hunter/estimate`

Runs `DescribeLogGroups` to estimate `storedBytes` × time-range ratio, returns
projected GB scanned. Displayed before the operator hits "hunt."

### `GET/POST /hunter/saved`

CRUD for `hunter_saved_queries`.

## Guardrails

1. **Time range cap** — default 24h, hard max 7 days. Configurable per source
   (some may be tighter).
2. **Pre-flight cost estimate** — every query shows projected GB scanned +
   dollar cost before execution. Operator must confirm if > $0.10.
3. **Per-operator rate limit** — 30 queries/min, 500/day. Enforced in FastAPI
   middleware.
4. **Identical-query cache** — 60s TTL on `(ioc_value, sources, hours)` tuple.
   Operators re-run the same pivot constantly during an investigation.
5. **Sample line cap** — return at most 20 raw lines per source per query. Full
   result set stays in CloudWatch; operator can click "expand" to fetch a
   second page (a new StartQuery with `limit`).
6. **No wildcards on ioc_value** — exact match only. Wildcards blow up scan
   cost and are rarely what an operator wants for pivoting.

## UX

### `/hunter` page

Two-column layout:

**Left (input):**
- IOC type dropdown: IP / user / ARN / request ID / hostname / access key
- IOC value input
- Time range (1h / 6h / 24h / 3d / 7d)
- Sources checklist (defaults: all enabled)
- "Estimate cost" button → shows GB + $ before you commit
- "Hunt" button

**Right (results):**
- One card per source, laid out in a grid
- Card shows: source name, match count, first/last seen relative time,
  "expand" to see raw lines
- Empty sources shown greyed with "0 matches"
- Top summary bar: "IOC seen in 3 of 8 sources. First: 6 days ago. Last: 2 min ago."

### Pivot buttons everywhere else in BW

Every rendered IP / user / ARN / request ID / hostname across BW becomes a
clickable pivot chip. Click → opens `/hunter?ioc_type=ip&ioc_value=X&hours=24`
in a new tab, all sources pre-selected.

Places to add pivot chips (phase 2):
- `/events` — actor.source_ip, actor.principal, observables[]
- `/api-gw` — Source IPs table, Failures table
- `/rds` — session view, connection log
- `/iam` — event actors
- `/hosts` — host IP, VPN client IP
- `/vpn` — client IPs
- `/rules` — recent matches
- Alert details panel — every extractable IOC in the event payload

## Sources to configure first

Ordered by expected hunter value:

1. **aws.api_gw** — HTTP API v2 access logs (`/aws/gateway/prod.web-api-server`)
2. **aws.cloudtrail** — control plane events (`/aws/cloudtrail`)
3. **aws.rds** — RDS Postgres error + slow query logs
4. **aws.iam** — IAM API activity (subset of CloudTrail, filtered)
5. **aws.vpc_flow** — VPC Flow Logs (NEW — not currently ingested)
6. **aws.alb** — ALB access logs (NEW if any ALB exists)
7. **aws.lambda** — Lambda invocation logs (per function or aggregated)
8. **aws.ecs** — ECS task logs (customer workload)

Note: **aws.vpc_flow** and **aws.alb** would be brand-new visibility for BW.
No pipeline work needed — they exist in CloudWatch already, we just add rows
to `hunter_sources`.

## Cross-account (deferred, phase 2)

If BW ever hunts across multiple AWS accounts:

1. Enable CloudWatch cross-account observability with the security account as
   monitoring account. AWS docs: "Monitoring account setup".
2. Or, add an `assume_role_arn` column to `hunter_sources` and let the hunter
   `sts:AssumeRole` per query. More flexible, more moving parts.

Current setup (single account, `095899260107`) doesn't need this.

## Live Tail (deferred, phase 3)

CloudWatch supports `StartLiveTail` for streaming log events matching a filter.
Use case: "watch this IP right now while I look at the dashboard."

- Streams events over WebSocket-like connection.
- Bills at $0.01/minute per session.
- Needs UI infra: WebSocket route in FastAPI, streaming component in Next.js.
- Auto-terminate after 15 minutes idle.

Skip in phase 1. Insights query with 60s refresh covers 90% of the value.

## HIPAA / PHI story

This is the important part.

**API Gateway path.** The pipeline can't ingest `$context.path` because it
contains patient/physician UUIDs. But CloudWatch already holds the full access
log with paths (AWS is BAA-covered). The hunter can query and display them
because BW never persists — operator sees on screen, browser tab closes,
gone. No storage in BW's Postgres, no logging by BW.

**App-layer audit log.** LongHealth's application probably already ships an
audit log to CloudWatch with per-endpoint / per-identity events. The hunter
unlocks that visibility without requiring the app team to duplicate anything
to BW. Add the log group to `hunter_sources`, done.

**What still needs care:**
- Cache TTLs (60s query cache) — sample lines held in memory during that
  window. Consider `hunter_query_cache` in Redis with encryption at rest, or
  just skip caching for PHI-containing sources.
- Access logs of the hunter itself — record `who queried what IOC when` in
  Postgres, without the log-line contents. Compliance-reviewable audit trail.

## Rollout plan

**Phase 1 (~1-2 days work):**
1. `028_hunter.sql` — schema + seed `hunter_sources` with API GW + CloudTrail
2. `blackwatch/hunter/client.py` — boto3 wrapper, StartQuery + poll +
   parse results. Handle Insights query timeout / cancel.
3. `blackwatch/hunter/service.py` — fan-out, cost estimation, rate limiting,
   cache
4. `blackwatch/api.py` — `/hunter/query`, `/hunter/estimate`, `/hunter/sources`
5. `blackwatch-ui/app/hunter/page.tsx` — two-column layout, source cards
6. `blackwatch-ui/lib/api.ts` — `fetchHunterSources`, `runHunterQuery`
7. Add hunter icon to SideNav
8. Test with API GW + CloudTrail as the two first sources

**Phase 2:**
- Pivot chips wired into all existing pages
- Saved queries CRUD + shareable links
- CloudTrail, RDS, IAM, VPC Flow Logs added to `hunter_sources`
- Server-Sent Events for streaming results (cards populate as each source
  finishes rather than one big response)

**Phase 3:**
- Live Tail integration
- Cross-account via AssumeRole
- Hunter audit log

## Open questions

- Should the hunter respect the same session model as the rest of BW (single
  operator), or do we need multi-user with per-user rate limits?
- Insights query language ergonomics — do we hand-craft the `fields | filter`
  per source in `ioc_field_map`, or generate from a small DSL?
- Do we want the hunter to be able to correlate results across sources
  (e.g., "IP X hit API GW at 14:22:03 AND appeared in CloudTrail at 14:22:07
  — same session?") — or is that phase 4?
- Should BW-ingested events themselves be a "hunter source" (query Postgres
  the same way we query CloudWatch)? Consistency win, but potentially
  confusing.

## Relation to existing modules

- **Pipeline modules** (aws_api_gw, aws_rds, aws_iam, aws_cloudtrail) — remain
  as-is. They emit persisted events for detection.
- **Hunter** — parallel surface. Same underlying CloudWatch log groups as
  the pipeline subscribes to, but queries directly instead of consuming a
  subscription-filtered stream.
- **Rules** — unchanged. Detection still fires from pipeline events.
- **Notifications** — unchanged. Hunter is human-driven, doesn't page anyone.

The two tiers complement each other: pipeline fires the alert, operator opens
the hunter to pivot and confirm.
