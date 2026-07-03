# RDS module — full reference

The canonical document for BlackWatch's RDS module: what it monitors,
how the log-forwarder pipeline is wired, how "who's connected right now"
gets computed, and how to set it up / troubleshoot it.

Sister doc to [`docs/vpn-agent.md`](vpn-agent.md), [`docs/ec2-agent.md`](ec2-agent.md),
and [`docs/ecs.md`](ecs.md). Same architectural principle: **AWS collects
raw data, BlackWatch is the ONE place where detection and routing happen.**

Current version: **v1.0** (Postgres + RDS Proxy log parsers, session projection,
pgaudit-aware).

---

## 1. What it does

For each RDS Postgres instance (and any RDS Proxy in front of it) you
enrol:

1. RDS engine → CloudWatch Log group (already flowing — this is how AWS
   ships DB logs by default).
2. A **CloudWatch Logs subscription filter** on each log group ships every
   log line to one Lambda (`bw-rds-forwarder`).
3. The Lambda decompresses the batch and puts one SQS message per batch
   on the `bw-rds-logs` queue. **Zero business logic in the Lambda** —
   it's a pipe.
4. BlackWatch's `aws_rds_sqs` connector drains the queue and feeds each
   batch through the `aws.rds` adapter which parses Postgres +
   RDS Proxy log lines into normalized events.
5. Events run through the standard pipeline — rule engine scores them,
   projection maintains state, notifications route via the same
   `notify:*` tag system the other modules use.

### What we surface

- **Every successful connection** (`rds.session.start`) with user, source
  IP, database name, Postgres backend PID.
- **Every disconnection** (`rds.session.end`) with total session duration.
- **Every failed authentication** — both native Postgres FATAL lines and
  RDS Proxy "authentication failed" lines.
- **Every FATAL / PANIC** engine error.
- **Every pgaudit-flagged query** — DDL, GRANT/REVOKE, mass reads (if
  you enable pgaudit — off by default).

---

## 2. Architecture / pipeline

```
┌─────────────────────────────────┐                              ┌─────────────────────────┐
│  RDS Postgres instance          │                              │  BlackWatch             │
│                                 │                              │  (Docker / Lightsail)   │
│  postgresql.log emits:          │                              │                         │
│   - connection authorized       │                              │                         │
│   - disconnection: ...          │                              │                         │
│   - password auth failed        │                              │                         │
│   - AUDIT: SESSION,...          │                              │                         │
└───────────────┬─────────────────┘                              │                         │
                │                                                │                         │
                ▼                                                │                         │
CloudWatch Log group                                             │                         │
  /aws/rds/instance/<db>/postgresql                              │                         │
                │                                                │                         │
                │  subscription filter (filter-pattern="")       │                         │
                ▼                                                │                         │
Lambda: bw-rds-forwarder                                         │  aws_rds_sqs.drain()    │
   - decompress + unwrap CloudWatch envelope                     │   │                     │
   - classify log_group -> (db_instance, source_type)            │   ▼                     │
   - send ONE SQS message per batch                              │  ingest_payload         │
                │                                                │   target_module=aws.rds │
                ▼                                                │   │                     │
SQS queue: bw-rds-logs (SSE-SQS, 24h retention, DLQ)  ────────►  │   ▼                     │
                                                                 │  AwsRdsAdapter          │
                                                                 │   parses each log line  │
                                                                 │   into rds.* events     │
                                                                 │   │                     │
                                                                 │   ▼                     │
                                                                 │  rds/projection.py      │
                                                                 │   session.start -> row  │
                                                                 │   session.end   -> mark │
                                                                 │                         │
                                                                 │  /api/rds/* endpoints   │
                                                                 │  /rds page              │
                                                                 └─────────────────────────┘

┌─────────────────────────────────┐
│  RDS Proxy (optional)           │
│                                 │
│  /aws/rds/proxy/<proxy>         │
│   - proxy auth failed for user  │
└───────────────┬─────────────────┘
                │  same subscription-filter pattern
                ▼
Lambda: bw-rds-forwarder            (log_group prefix tells adapter to use proxy parser)
```

**Why this shape:**

- **Lambda is a pure forwarder** — never has business logic. All parsing,
  detection, and routing live in BW rules. Replacing this Lambda with
  something else (Kinesis Firehose, EventBridge, whatever) is a
  one-file change with no downstream code touched.
- **One SQS queue for all DBs** — the log group name tells us the DB;
  we don't need per-DB fan-out.
- **BW polls SQS every 60s** — reuses the exact same drain pattern as
  the CloudTrail queue for IAM. No new operational muscle.

---

## 3. Files & paths

### In the BlackWatch repo

| Path | Purpose |
|---|---|
| `deploy/rds/bw_log_forwarder.py` | Lambda source. Generic CloudWatch Logs → SQS forwarder. |
| `deploy/rds/setup.ps1` | Bootstrap: SQS queue + DLQ, IAM role, Lambda, subscription filters, BW reader user permission. Idempotent. |
| `blackwatch/modules/aws_rds.py` | Adapter. Postgres + pgaudit + RDS Proxy log line parsers. |
| `blackwatch/rds/projection.py` | Session tracker. Handles `rds.session.start` / `rds.session.end`. |
| `blackwatch/rds/__init__.py` | Package marker. |
| `blackwatch/connectors/aws_rds_sqs.py` | SQS drain. |
| `blackwatch/connectors/models.py` | `AwsRdsSqsConfig`. |
| `blackwatch/connectors/runner.py` | Dispatch for `aws_rds_sqs` connector type. |
| `blackwatch/sql/020_rds_sessions.sql` | Schema — `rds_active_sessions` table. |
| `blackwatch/storage.py` | `upsert_rds_session_start`, `close_rds_session`, `list_rds_*`, etc. |
| `blackwatch/api.py` | `/api/rds/summary`, `/api/rds/live`, `/api/rds/sessions`, `/api/rds/auth-failures`. |
| `blackwatch-ui/app/rds/page.tsx` | Databases summary, live sessions, session history (24h), auth failures. |
| `rules/aws_rds.yaml` | Detection + notify tags. |
| `docs/rds.md` | **This file.** |

### On AWS (created by `setup.ps1`)

| Resource | Naming | Notes |
|---|---|---|
| SQS queue | `bw-rds-logs` | SSE-SQS, 24h retention, redrive to DLQ after 5 tries. |
| SQS DLQ | `bw-rds-logs-dlq` | Failed messages land here. Nothing else touches it — inspect manually if it starts growing. |
| Lambda | `bw-rds-forwarder` | Python 3.12, 30s timeout, 128MB. Reads `QUEUE_URL` env var. |
| Lambda role | `bw-rds-forwarder-role` | Basic execution + `sqs:SendMessage` on the queue ARN. |
| Subscription filters | one per RDS log group | `filter-pattern=""` (forward everything). BW does the filtering. |
| IAM policy | `bw-read-rds-queue` (managed) | Attached to `blackwatch-sqs-reader`. `sqs:Receive/Delete/GetQueueAttributes`. |

### On BlackWatch (Lightsail)

| Item | Notes |
|---|---|
| Connector | `aws_rds_sqs` type, name `RDS logs`. |
| AWS profile | Reuses the existing `blackwatch` profile (same access keys as CloudTrail + ECS). |

---

## 4. Setup — first time

### Prep — check the DB's parameter group

You need `log_connections` and `log_disconnections` on. Cheapest check:

```powershell
aws rds describe-db-parameters --db-parameter-group-name <your-pg> --region us-west-1 --query "Parameters[?ParameterName=='log_connections' || ParameterName=='log_disconnections'].{name:ParameterName,value:ParameterValue,restart:ApplyType}" --output table
```

If either shows `-` or `0`, edit the parameter group:

```powershell
aws rds modify-db-parameter-group --db-parameter-group-name <your-pg> --parameters "ParameterName=log_connections,ParameterValue=1,ApplyMethod=immediate" "ParameterName=log_disconnections,ParameterValue=1,ApplyMethod=immediate" --region us-west-1
```

These are dynamic — no reboot. Changes apply within a few minutes.

### Deploy the forwarder

```powershell
$env:REGION = "us-west-1"
$env:LOG_GROUPS = "/aws/rds/instance/prod-database-healthlake/postgresql,/aws/rds/proxy/proxy-1768332114756-prod-database-healthlake"
.\deploy\rds\setup.ps1
```

The script prints a connector-registration command at the end. Run it
on Lightsail:

```bash
docker compose exec app python -c "from blackwatch import db, storage; import uuid; db.init_pool(); storage.upsert_connector(str(uuid.uuid4()), 'RDS logs', 'aws_rds_sqs', {'queue_url': '<paste-from-setup>', 'aws_region': 'us-west-1', 'aws_profile': 'blackwatch', 'interval_seconds': 60, 'wait_seconds': 10, 'max_batches': 5})"
```

Then in the BW UI → Connectors → **Test** → **Enable**.

Within one drain cycle (~60s) the `/rds` page should start populating.

---

## 5. Enabling pgaudit (query audit) — later

Not required for session tracking + auth failures. Only needed if you
want per-query DDL / role / mass-read alerts.

1. **Attach pgaudit to `shared_preload_libraries`** — requires a
   parameter group change and a DB reboot (this one is static):
   ```powershell
   aws rds modify-db-parameter-group --db-parameter-group-name <pg> --parameters "ParameterName=shared_preload_libraries,ParameterValue=pgaudit,ApplyMethod=pending-reboot" --region us-west-1
   aws rds reboot-db-instance --db-instance-identifier prod-database-healthlake --region us-west-1
   ```
2. **Create the extension** — one-off SQL after the reboot:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pgaudit;
   ```
3. **Configure what pgaudit logs** — DDL + role changes is the sweet
   spot; `all` is verbose and expensive:
   ```powershell
   aws rds modify-db-parameter-group --db-parameter-group-name <pg> --parameters "ParameterName=pgaudit.log,ParameterValue='ddl,role,misc',ApplyMethod=immediate" --region us-west-1
   ```
4. Optional: `pgaudit.log_parameter=on`, `pgaudit.log_relation=on` for
   richer audit rows.

Nothing on the BW side changes — the adapter already knows the pgaudit
line format.

---

## 6. How status flows

### Session lifecycle

1. Postgres logs `connection authorized: user=X database=Y` when a
   client connects.
2. Lambda ships the line to SQS.
3. Adapter emits `rds.session.start` with `session_id = pg:<db>:<pid>`.
4. Projection inserts a row into `rds_active_sessions` (or updates
   `last_seen_at` if we've seen the same pid before due to log replay).
5. When the client disconnects, Postgres logs `disconnection: session
   time: HH:MM:SS.mmm user=X database=Y host=IP`.
6. Adapter emits `rds.session.end` with the same session_id + duration.
7. Projection sets `disconnected_at` and `duration_seconds`.

Ghost sessions (start seen, end lost) sit in `rds_active_sessions` with
`disconnected_at IS NULL` until either a matching end arrives or you
add a reconciler pass (see §10).

### Auth failures

`FATAL: password authentication failed` and `no pg_hba.conf entry` both
map to `rds.auth.failure`. The RDS Proxy variant (`Proxy authentication
... failed for user "X"`) also maps to `rds.auth.failure` but with
`source_type = rds_proxy`.

Rules can burst-detect (many failures per user per window) — see
`rules/aws_rds.yaml`.

### pgaudit queries

`AUDIT: SESSION,...` lines get decoded by the adapter into
`rds.query.ddl`, `rds.query.role`, `rds.query.read`, `rds.query.write`,
`rds.query.function`, `rds.query.misc`. The rule file scores DDL + role
as critical, mass-read as high.

---

## 7. Notifications

Same tier system as the other modules. `rules/aws_rds.yaml` uses:

| Action | Rule | Notify tier |
|---|---|---|
| `rds.query.ddl` (DROP/TRUNCATE/etc.) | `rds-privileged-ddl` | `notify:critical` |
| `rds.query.role` (GRANT/REVOKE) | `rds-role-change` | `notify:critical` |
| `rds.error` (FATAL/PANIC) | `rds-fatal-error` | `notify:high` |
| `rds.query.function` | `rds-function-executed` | `notify:medium` |
| `rds.auth.failure` | `rds-auth-failure` | (low, informational — add burst rule if you want to page) |

**Recommended add-on rules once you have baseline data:**
- Multiple `rds.auth.failure` for the same user within 5 min → high
- `rds.session.start` from a new source IP for that user → high
- `rds.session.start` outside business hours for admin users → medium

Those need a small stateful projection to track baselines. Not shipped
by default; add when you know what "normal" looks like.

---

## 8. IAM model

### Forwarder Lambda role — `bw-rds-forwarder-role`

- `AWSLambdaBasicExecutionRole` (CloudWatch Logs writes for the Lambda's own logs)
- Inline `send-to-rds-queue`: `sqs:SendMessage` on `bw-rds-logs` ARN

Nothing else. The Lambda cannot even read RDS metadata.

### BlackWatch reader user — `blackwatch-sqs-reader`

Adds a managed policy `bw-read-rds-queue` on top of what it already had
for CloudTrail + ECS queues. `sqs:Receive/Delete/GetQueueAttributes` on
the new queue ARN. No cross-DB visibility, no engine access, no metadata.

### What the Lambda cannot do

- Read RDS metadata (no `rds:*`)
- Read other CloudWatch log groups (no wildcard perms)
- Modify anything — writes are gated to one SQS queue ARN

---

## 9. Operational tasks

### Tailing the forwarder (from your laptop)

```powershell
aws logs tail /aws/lambda/bw-rds-forwarder --follow --region us-west-1
```

Each invocation prints `{"forwarded": N, "db_instance": "...", "source_type": "..."}`.

### Watching messages land on the queue

```powershell
aws sqs get-queue-attributes --queue-url <bw-rds-logs-url> --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --region us-west-1
```

Growing in-flight count means BW is processing. Growing visible count
without draining means the BW connector isn't running (check `Enable`
in the UI + Test).

### Adding a new DB

Re-run `setup.ps1` with an expanded `$env:LOG_GROUPS`. The script is
idempotent — it just adds a new subscription filter without touching
the existing ones.

### Retiring the current CloudWatch Alarm + SNS email

Once you've verified BW's `rds-auth-failure` (or a burst rule you add)
covers what the CloudWatch alarm was doing:

```powershell
aws cloudwatch delete-alarms --alarm-names <alarm-name> --region us-west-1
aws sns delete-topic --topic-arn <topic-arn> --region us-west-1
```

Do this last, after BW has been running for a week and you're confident.

---

## 10. Troubleshooting

### "No RDS activity ingested yet" on the /rds page

Chain to check:
1. Are logs even reaching CloudWatch? `aws logs describe-log-streams --log-group-name /aws/rds/instance/<db>/postgresql` — should show recent streams.
2. Is the subscription filter attached? `aws logs describe-subscription-filters --log-group-name <lg>` — should list `bw-forwarder`.
3. Is the Lambda invoking? `aws logs tail /aws/lambda/bw-rds-forwarder --since 5m`.
4. Are messages landing on SQS? `get-queue-attributes` (see §9).
5. Is the BW connector enabled + verified? `/connectors` page.
6. Are events being written? `docker compose exec app python -c "from blackwatch import db, storage; db.init_pool(); r = storage.query_events(module='aws.rds', limit=5); [print(e['action'], e.get('event_time')) for e in r]"`.

### Sessions never close (they sit as "still open" forever)

Postgres emits the disconnection line only if `log_disconnections = on`.
Verify with `SHOW log_disconnections;` from psql. If it's off, flip it
in the parameter group.

If it's on and sessions still leak, the Postgres backend was killed
before it could log (rare — usually only in OOM or forced kill). A
reconciler pass polling `pg_stat_activity` and closing stale rows is
the safety net (not shipped by default; hook is `blackwatch/rds/
reconciler.py` if you want to add it).

### "Currently connected" shows more than pg_stat_activity does

Usually means log replay after a BW restart re-inserted an already-
closed session (adapter uses deterministic event_ids, so it's rare).
The reconciler above catches this too.

### Log costs surprised us

CloudWatch Logs subscription filters bill on bytes forwarded (~$0.60/GB
past the free tier). If your Postgres logs are chatty, you can tighten
the subscription filter's `filter-pattern` to only forward lines matching
key phrases (`{$.message = "*connection authorized*" || $.message =
"*disconnection*" || $.message = "*password authentication failed*"}`)
and BW parses fewer lines.

Downside: you lose the ability to catch new event types without changing
the filter. Only tighten if bill is a real concern.

---

## 11. What's intentionally NOT included

- **Business logic in the Lambda.** The Lambda is a dumb pipe; every
  decision — what to alert on, how to classify, when to escalate —
  lives in BW rules where it can be edited without redeploying AWS.
- **CloudWatch metric filters + alarms.** Explicitly *replaced* by this
  module. Alarms/metric filters are per-signal, alarm-shaped, and force
  you to build new AWS resources per detection. BW rules are versioned,
  reviewable, and add new detections with zero AWS changes.
- **Query content inspection (`SELECT * FROM ssn` etc.).** pgaudit
  captures the query text; adding column-level policies (block/alert on
  reads of specific tables) is future work.
- **Slow query detection.** Postgres already exposes this via
  `pg_stat_statements`; we don't want to duplicate. If you want
  slow-query alerts, poll that view via a small BW connector.
- **RDS instance posture (encryption / backups / public access).** That's
  covered by the existing `aws_posture_drift` connector's `check_rds`
  path. Complementary, not overlapping.
