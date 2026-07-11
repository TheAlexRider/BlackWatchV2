# API Gateway monitoring — reference (Phase 0: access log format)

The canonical document for BlackWatch's API Gateway monitoring module.
Sister doc to [`docs/rds.md`](rds.md) and [`docs/ecs.md`](ecs.md) — same
"CloudWatch log group → forwarder Lambda → SQS → BW connector → adapter →
rules" shape, adapted for API Gateway HTTP APIs.

**This document currently covers Phase 0 only:** the access log format
change. Phase 1 (ingest pipeline, adapter, `/api-gw` UI) will be added
as it lands.

Target API: `prod.web-api-server` (API ID `auusekzkil`, region
`us-west-1`, log group `/aws/gateway/prod.web-api-server`).

---

## 1. Why the log format matters

API Gateway HTTP APIs write one access-log line per request in whatever
JSON format you configure per-stage. The format is the **only** hook
BlackWatch has into your traffic — there is no packet capture, no
sidecar. Whatever fields the log line carries are what BW gets.

Fewer fields = smaller cost, less detection surface.
More fields = more detection, more cost, more compliance surface (PHI).

For a HIPAA-covered entity, the **field list is a security control**,
not just a data-modelling choice — anything logged at the API Gateway
layer is written to CloudWatch, which then becomes PHI-in-scope if it
holds patient-identifying data. Keep identity attribution OUT of this
log source.

---

## 2. What was there before

Original stage access log format (`$default` stage of `auusekzkil`):

```json
{
  "requestId":    "$context.requestId",
  "ip":           "$context.identity.sourceIp",
  "requestTime":  "$context.requestTime",
  "httpMethod":   "$context.httpMethod",
  "routeKey":     "$context.routeKey",
  "status":       "$context.status",
  "protocol":     "$context.protocol",
  "responseLength": "$context.responseLength"
}
```

**What that gave us:**
- Which endpoint was hit, when, by which source IP, and what status
  came back.

**What it missed:**
- No user agent → couldn't fingerprint scanners / bots.
- No latency → couldn't baseline "unusual response time" or "slow read
  spike".
- No request-body size → couldn't detect bulk-write or scraping payloads.
- No integration-side outcome → couldn't tell an API Gateway-level 502
  (backend timeout) from a backend-returned 502 (real app error).
- No error metadata → couldn't triage what failed.
- No high-resolution timestamp → couldn't correlate cleanly across
  services with sub-second precision.

**Bottom line:** enough for a status-code dashboard, not enough for
security detection.

---

## 3. What we're doing

New stage access log format (still `$default`, still same log group):

```json
{
  "requestId":         "$context.requestId",
  "requestTime":       "$context.requestTime",
  "requestTimeEpoch":  "$context.requestTimeEpoch",
  "ip":                "$context.identity.sourceIp",
  "userAgent":         "$context.identity.userAgent",
  "httpMethod":        "$context.httpMethod",
  "routeKey":          "$context.routeKey",
  "status":            "$context.status",
  "protocol":          "$context.protocol",
  "responseLength":    "$context.responseLength",
  "responseLatency":   "$context.responseLatency",
  "integrationStatus": "$context.integrationStatus",
  "errorMessage":      "$context.error.message",
  "errorResponseType": "$context.error.responseType"
}
```

**Same 8 fields as before, plus 6 new ones. Pure superset. No fields removed.**

> **Gotcha:** `$context.requestLength` is REST API v1 only — HTTP API v2 rejects
> it with `BadRequestException: The following context variables are not
> supported`. We drop it and rely on `responseLength` (bulk-read detection,
> which matters more for PHI exfil than bulk-write detection anyway).

### Per-field justification

| Field | Why it's in | What we detect with it |
|---|---|---|
| `requestId` | Correlation key. | Ties an API line to an app-layer log if we ever add app-layer ingest. |
| `requestTime` | Human-readable timestamp. | Displayed on `/api-gw` UI. |
| `requestTimeEpoch` **NEW** | Millisecond-resolution timestamp. | Precise burst-window math (`>N failures / 5 min`) without string-parsing. |
| `ip` | Real client IP (post-proxy). | Every source-IP-based rule: burst, spray, new-source, geo-anomaly, VPN detection. |
| `userAgent` **NEW** | Client identification. | Scanner detection (`sqlmap`, `nikto`, `nuclei`, `dirbuster`, generic bots). Also "known-good UA" allowlisting for internal services. |
| `httpMethod` | Verb of the request. | Sensitive-endpoint rules that only fire on `POST`/`DELETE` (not `GET`). |
| `routeKey` | Route template (e.g. `POST /api/v1/patients/{id}`). | Aggregation key. Never contains actual UUIDs — safe to log even under strict PHI rules. |
| `status` | HTTP status code. | Every rule keys off this: 401/403 for auth failure, 4xx for client errors, 5xx for outages, 429 for throttled. |
| `protocol` | HTTP version. | Useful only for weird bot detection (still on HTTP/1.0? probably a scanner). |
| `responseLength` | Bytes returned. | Bulk-read / data-exfil detection. `GET /patients` returning 500 KB vs the usual 5 KB is a signal. |
| `responseLatency` **NEW** | End-to-end request latency in ms. | Baseline anomalies. Latency spike often precedes an outage. |
| `integrationStatus` **NEW** | HTTP status the backend integration returned. | Distinguishes API Gateway-level failure (auth rejected, throttled, timeout) from backend failure (Lambda 500). Different rules for each. |
| `errorMessage` **NEW** | API Gateway-side error string when the request failed at the gateway. | Triage failed auth attempts, throttling events, integration errors. |
| `errorResponseType` **NEW** | API Gateway error class (e.g. `UNAUTHORIZED`, `THROTTLED`, `ACCESS_DENIED`, `INTEGRATION_TIMEOUT`). | Enum-typed source of truth for auth-failure classification without string-matching. |

### What we deliberately do NOT log

For HIPAA-safety: identity fields carrying PHI-adjacent identifiers stay
OUT of API Gateway access logs. These are added later at the
application-audit-log layer, which is already HIPAA-scoped.

| Field | Why not |
|---|---|
| `path` (`$context.path`) | Contains the actual URL with UUIDs substituted (e.g. `/api/v1/patients/9c1a…`). The UUID is a patient identifier — PHI. `routeKey` gives us the same routing info without the UUID. |
| `x-physician-uuid` (request header) | Direct physician identifier. PHI-adjacent. |
| `x-patient-physician-uuid` (request header) | Patient identifier. PHI. |
| `x-patient-provider-uuid` (request header) | Patient identifier. PHI. |
| `x-provider-patient-identity-uuid` (request header) | Patient identifier. PHI. |
| `x-connection-id` (request header) | Session-linked, may tie to a patient session. PHI-adjacent. |
| `x-organization-uuid` (request header) | Org identity. Not strictly PHI, but combined with the above becomes PHI. Excluded for consistency. |
| Request body | Contains full patient records on write endpoints. Never log. |
| Response body | Contains full patient records on read endpoints. Never log. |
| `Authorization` header | JWT / API key. Sensitive credential. Never log. |

Per-physician / per-patient anomaly detection lives at the **app-layer
audit log**, not here. That log store is already HIPAA-scoped, has BAA
coverage, encrypted-at-rest, tight access control, and short retention.
BW will ingest a copy of *that* stream in a later phase, gated on the
same HIPAA controls.

---

## 4. Applying the format change

Metadata-only change on the API Gateway stage. **No downtime, no
deploy, no re-provisioning.** The new format takes effect on
subsequent requests within a few seconds. Existing log lines already
in CloudWatch stay untouched.

### PowerShell (from the operator's PC)

The AWS CLI's shorthand `Key=Value,Key=Value` parser breaks on the commas
inside the JSON format string. Pass a JSON file via `file://` instead:

```powershell
$logFormat = '{"requestId":"$context.requestId","requestTime":"$context.requestTime","requestTimeEpoch":"$context.requestTimeEpoch","ip":"$context.identity.sourceIp","userAgent":"$context.identity.userAgent","httpMethod":"$context.httpMethod","routeKey":"$context.routeKey","status":"$context.status","protocol":"$context.protocol","responseLength":"$context.responseLength","responseLatency":"$context.responseLatency","integrationStatus":"$context.integrationStatus","errorMessage":"$context.error.message","errorResponseType":"$context.error.responseType"}'

$settings = [PSCustomObject]@{
    DestinationArn = "arn:aws:logs:us-west-1:095899260107:log-group:/aws/gateway/prod.web-api-server"
    Format = $logFormat
} | ConvertTo-Json -Compress

$settingsPath = Join-Path $env:TEMP "bw-apigw-log-settings.json"
$settings | Out-File -Encoding ascii -FilePath $settingsPath

aws apigatewayv2 update-stage --api-id auusekzkil --stage-name '$default' --region us-west-1 --access-log-settings "file://$settingsPath"

Remove-Item $settingsPath
```

### Also apply a retention policy

CloudWatch is the ephemeral log store; BW is the durable one. Cap retention:

```powershell
aws logs put-retention-policy --log-group-name /aws/gateway/prod.web-api-server --retention-in-days 14 --region us-west-1
```

Fourteen days is enough for BW to drain via subscription filter (Phase 1)
and enough for on-call to hand-query recent activity. Longer-term
archive lives in the BW database, or in S3 export if compliance
requires 6-year retention.

### Verify the change

Wait 30 seconds (or send a request through the API), then tail the log group:

```powershell
aws logs tail /aws/gateway/prod.web-api-server --since 2m --region us-west-1
```

Confirm the new fields are populated. `errorMessage` will be `-` for
successful requests; that's expected — it's only set when the request
failed at the API Gateway layer.

### Rollback

Same command, old format string:

```powershell
$oldFormat = '{ "requestId":"$context.requestId", "ip": "$context.identity.sourceIp", "requestTime":"$context.requestTime", "httpMethod":"$context.httpMethod","routeKey":"$context.routeKey", "status":"$context.status","protocol":"$context.protocol", "responseLength":"$context.responseLength" }'

aws apigatewayv2 update-stage --api-id auusekzkil --stage-name '$default' --region us-west-1 --access-log-settings "DestinationArn=arn:aws:logs:us-west-1:095899260107:log-group:/aws/gateway/prod.web-api-server,Format=$oldFormat"
```

Instant revert. Any lines already written with the new format stay as they are.

---

## 5. Cost impact

Rough estimate — depends on real request volume.

Log line size grows from ~200 bytes to ~350 bytes (7 new fields, mostly
short values). At LongHealth's expected 500k–5M requests/day:

| Line item | Estimated $/mo added |
|---|---|
| CloudWatch Logs ingestion (added 75 MB – 750 MB/day) | $1 – $11 |
| CloudWatch Logs storage (14-day retention) | $0.10 – $0.60 |
| BW ingest pipeline (Lambda + SQS + processing) — Phase 1 | $5 – $10 |
| **Total** | **~$8 – $22 / month** |

For context: GuardDuty on the same API surface would run ~$300–500/month
and give you correlation, not detection tailored to your domain.

---

## 6. Phase 1 — what shipped

### Detection decision (locked)

**No PHI in CloudWatch, ever.** We ship without `$context.path` and without
identity headers. Trade-off: no per-endpoint / per-user detection at the
API Gateway layer. What we CAN detect from source IP + method + status +
UA + latency + response size:

- Credential stuffing / spraying (auth burst per source IP)
- Scanner recon (UA signature matching)
- New client IP (first-seen tracking, like the RDS Proxy source panel)
- 5xx bursts localized to one client (fuzzing / targeted probing)

What we CAN'T detect at this layer, deferred to the app-layer audit log
in a later phase:

- Per-endpoint enumeration (`GET /patients/1`, `/patients/2`, …)
- Sensitive-endpoint access (`POST /admin/*`)
- Per-physician / per-patient anomaly

### Pipeline

```
API Gateway (auusekzkil, $default stage)
  → CloudWatch Logs group /aws/gateway/prod.web-api-server
  → Subscription filter (empty pattern = all events)
  → bw-rds-forwarder Lambda (extended in Phase 1 to route by log group)
  → SQS queue bw-api-gw-logs
  → BW connector aws_api_gw_sqs (60s poll)
  → BW adapter aws.api_gw
  → Emitted events: api.request (projection-only),
                    api.auth.failure, api.error, api.scanner_ua
  → Projection updates api_sources; derives
                    api.source.new, api.auth.burst, api.error.burst
  → Rules in rules/aws_api_gw.yaml assign severity + notification tags
  → UI at /api-gw renders alerts, sources, failures
```

### Files added

Backend:
- `blackwatch/sql/027_api_gw.sql` — `api_sources` table
- `blackwatch/modules/aws_api_gw.py` — JSON access-log parser
- `blackwatch/connectors/aws_api_gw_sqs.py` — SQS drain
- `blackwatch/connectors/models.py` — `AwsApiGwSqsConfig`
- `blackwatch/connectors/runner.py` — dispatch branch
- `blackwatch/api_gateway/projection.py` — source tracking + burst detection
- `blackwatch/pipeline.py` — projection wired; `api.request` marked PROJECTION_ONLY
- `blackwatch/storage.py` — `upsert_api_source`, `list_api_sources`, `api_gw_summary`
- `blackwatch/api.py` — 4 endpoints under `/api-gw/*`
- `rules/aws_api_gw.yaml` — 6 rules
- `blackwatch/modules/registry.py` — adapter registered

Lambda:
- `deploy/rds/bw_log_forwarder.py` — extended to classify + route to
  `bw-api-gw-logs` when log group is under `/aws/gateway/*`; RDS path
  unchanged

Frontend:
- `blackwatch-ui/lib/types.ts` — API Gateway types
- `blackwatch-ui/lib/api.ts` — 4 new fetchers
- `blackwatch-ui/components/layout/SideNav.tsx` — "API Gateway" nav link
- `blackwatch-ui/app/api-gw/page.tsx` — alerts + sources + failures view

### Operator setup (AWS side)

1. `aws sqs create-queue --queue-name bw-api-gw-logs --region us-west-1`
2. Zip and update the Lambda code:
   `aws lambda update-function-code --function-name bw-rds-forwarder --zip-file fileb://forwarder.zip`
3. Set the new env var:
   `aws lambda update-function-configuration --function-name bw-rds-forwarder
    --environment "Variables={QUEUE_URL=…bw-rds-logs,API_GW_QUEUE_URL=…bw-api-gw-logs}"`
4. Grant the Lambda role `sqs:SendMessage` on `bw-api-gw-logs`
5. Attach subscription filter on `/aws/gateway/prod.web-api-server` → the Lambda
6. Add the BW connector row from `/connectors` UI (type: `aws_api_gw_sqs`,
   queue URL, region `us-west-1`)

## 7. What's still deferred (not shipped)

- **App-layer audit log ingest** — for per-endpoint / per-identity
  detection without PHI in CloudWatch. Depends on the backend exposing a
  structured audit stream.
- **`api.auth.spray`** — many distinct routeKey templates failing from
  one IP. Blocked by `routeKey=ANY /{proxy+}` catch-all; would need
  Option C (real routes on the API Gateway) or Option B (backend audit).
- **Per-endpoint baselines / enumeration detection** — same block.
- **Sensitive-endpoint allowlist** — same block.
