# S3 access log connector (`aws_s3_access_logs`)

Pulls S3 Server Access Logs from a central log bucket, parses each request, and emits `s3.object.access` events into the pipeline. Feeds intel enrichment + UEBA baselines automatically.

## What it captures

Per S3 request (GET, PUT, DELETE, etc. against any logged bucket): requester ARN, remote IP, operation, HTTP status, bytes sent, user agent, TLS version. Object key is trimmed to the first path segment by default (PHI-safe).

## Event actions emitted

- `s3.object.access` — every logged request. **Projection-only** (see [pipeline.py](../blackwatch/pipeline.py)) — feeds intel + UEBA but not stored/notified by default. Anomaly derivations (first-seen source IP, first-seen ASN, threat-feed hit) fire as separate events and ARE stored.
- `s3.object.access.anonymous` — Requester field is `-`. Always stored, always alertable. On a private-bucket fleet this should be zero.

## Rules that match these events

- `s3-object-access-anonymous` — anonymous request → high.
- `s3-object-access-from-known-bad-ip` — intel-feed match on source IP → high.
- `s3-object-access-from-tor` — source IP is a Tor exit → critical.
- `iam.anomaly.first_seen_source_ip` / `first_seen_source_country` / `first_seen_source_asn` — auto-emitted by UEBA after warm-up on the requester principal.

## Prerequisites (one-time, AWS side)

1. **Central log bucket** exists and is receiving Server Access Logs from every source bucket you want to monitor. See earlier setup: `longhealth-security-s3-access-logs` in us-west-1, receives from 34 source buckets under `logs/<bucket>/…`, 3-day lifecycle expiration.
2. **BW EC2 instance role** has `s3:ListBucket` + `s3:GetObject` on the log bucket only. See [docs/iam-policies/README.md](iam-policies/README.md).
3. **Nothing else** — the connector uses boto3's default credential chain, which picks up the instance role via IMDS with no explicit key handoff.

## Adding the connector in BlackWatch UI

Settings → Connectors → Add connector → type `aws_s3_access_logs`, config:

```json
{
  "bucket": "longhealth-security-s3-access-logs",
  "aws_region": "us-west-1",
  "interval_seconds": 300,
  "overlap_seconds": 900,
  "max_files_per_run": 200,
  "prefix": ""
}
```

Enable → Run now. On success, the connector marks itself `verified` and the scheduler starts polling every `interval_seconds`.

## Config options

| Field | Default | Meaning |
|---|---|---|
| `bucket` | required | The central log bucket to poll. |
| `aws_region` | `us-west-1` | Region the bucket lives in. |
| `aws_profile` | none | Optional profile name if not using instance role. |
| `interval_seconds` | `300` | Poll cadence. 5 min is a good default — AWS delivers access logs in batches every few minutes anyway. |
| `overlap_seconds` | `900` | Time-cursor overlap so files landing late still get processed. Dedupe handles the rest. |
| `max_files_per_run` | `200` | Cap per tick so a burst of source-bucket traffic doesn't stall the tick loop. Unprocessed files are picked up on the next run. |
| `prefix` | `""` | Restrict to a subset of source buckets (e.g. `logs/prod-`). Empty = all. |

## Volume + storage cost inside BW

Raw `s3.object.access` events are projection-only: they enter the pipeline, feed intel + UEBA, then get **dropped**. The events table grows only on:

- `s3.object.access.anonymous` (rare)
- Derived UEBA anomalies (`iam.anomaly.first_seen_*`)
- Rule-match matches on the above

For a private-bucket fleet this is bounded — typically a few dozen anomaly events per day during warm-up, near-zero once baselines are established.

If you want **full storage of raw access events** for compliance evidence, remove `"s3.object.access"` from `_PROJECTION_ONLY_ACTIONS` in [blackwatch/pipeline.py](../blackwatch/pipeline.py). Expect the events table to grow proportional to your S3 request volume.

## Deterministic event IDs / dedupe

Event IDs are `uuid5("s3access:<source_bucket>:<request_id>:<line_no>")`. Re-processing the same log file (e.g. during the overlap window) produces identical IDs; `storage.insert_event` uses `ON CONFLICT (event_id) DO NOTHING`, so duplicates just skip on insert.

## Key redaction

By default the target ID keeps only the first path segment of the object key (`patient/…`). To preserve full keys for specific buckets (e.g. for canary detection later), add the source-bucket name to `_KEY_KEEP_FULL_FOR_BUCKETS` in [blackwatch/modules/aws_s3_access.py](../blackwatch/modules/aws_s3_access.py). Weigh against PHI-in-events-table risk.

## Troubleshooting

- **Connector `verified=false` after first run** — check `last_error` on the connector row. Most common: IAM policy missing / attached to wrong role, or bucket name typo.
- **No events flowing** — S3 delivers access logs on a delay of minutes to hours. Confirm log files are landing: `aws s3 ls s3://longhealth-security-s3-access-logs/logs/ --recursive --summarize | tail`. If empty, the source-side logging config is the issue, not BW.
- **`AccessDenied` on GetObject but `ListBucket` works** — bucket policy or object ACL is blocking read. Server access logs are written with a canonical grant that the log-bucket owner can read; if that got overridden the bucket policy needs updating.
- **Too many events** — enable projection-only mode (default) or narrow via `prefix` to only the sensitive buckets.
