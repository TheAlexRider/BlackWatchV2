# BlackWatch R&D Report — product, capability, and reliability roadmap

Cycle focus: identify the next ten highest-value tasks after the notification
route consolidation work.

Date: 2026-08-30

## Assessment

BlackWatch has a broad ingestion and notification foundation, but the next
value comes from making coverage truthful and dependable before adding many
more integrations. The repository shows three high-leverage gaps: notification
event ownership is still broader than the verified contracts, several planned
capabilities remain deferred, and deployment/test environments can hide
regressions. Route 53/DNS query logs are a good additive module because the
existing CloudWatch/SQS and DNS tool foundations can be reused.

## Evidence-backed priorities

1. Notification rollout truth and producer/catalog parity remain incomplete
   (`blackwatch/notify/catalog.py`, `blackwatch/notify/profiles.py`,
   `blackwatch/ueba/check.py`, `blackwatch/posture/projection.py`).
2. The UI has canonical notification redirects now, but create flows still
   span `/notifications/create`, `/notifications/create/event`, and
   `/notifications/rules/new`; the route inventory should govern future cleanup.
3. Threat Hunter explicitly defers cross-account observability and Live Tail
   (`docs/threat-hunter.md:246-265`).
4. Route 53 query-log ingestion is not represented as a BlackWatch module,
   while CloudWatch Logs → SQS forwarding and DNS parsing already exist
   (`docs/rds.md`, `blackwatch/connectors/aws_sqs.py`,
   `blackwatch-ui/app/api/tools/dns-lookup/route.ts`).
5. Existing build evidence has dependency blockers (`psycopg`, `jinja2`, and
   broken local Node package links), so CI/environment reproducibility is a
   product reliability issue, not just developer convenience.

## Recommended order

BW-036 and BW-037 should precede broad new feature work. BW-038 through BW-040
stabilize analyst navigation and live visibility. BW-041 through BW-045 add
carefully bounded capability, including Route 53, without changing storage
destructively.

## Connector operations focus — 2026-09-03

### Findings

1. **Actions have no immediate execution state.** `blackwatch-ui/app/connectors/page.tsx`
   uses ordinary submit buttons, even though `PendingButton` exists. The server
   action waits for `postForm()` and redirects only after the synchronous
   `blackwatch/connectors/runner.py:run_connector` completes. The runner stores
   only `last_status`, `last_error`, and `last_run_at`; there is no operation ID,
   running state, progress, or duplicate-run guard. This directly explains the
   reported uncertainty about whether Run now registered. Confidence: high.

2. **The scheduler has no explicit stale-retry policy.**
   `blackwatch/connectors/scheduler.py` ticks every 10 seconds but runs only
   enabled+verified connectors when their configured interval is due. Failed
   runs update `last_run_at`, so failures wait for the normal interval rather
   than following a visible retry policy. Exceptions are swallowed and the UI
   exposes no scheduler heartbeat, next run, retry count, or reason. Confidence:
   high.

3. **There is no connector-level Retry All.** The page has per-row Test, Run
   now, toggle, edit, and delete controls. `POST /modules/refresh` in
   `blackwatch/api.py` is type-based, synchronous, and lacks an aggregate
   operation status. Recovery therefore requires manual row-by-row actions.
   Confidence: high.

4. **Diagnostics are too shallow.** The connector API/storage contract exposes
   only the last attempt and a raw exception string. The UI renders errors as a
   compact row/tooltip, with no bounded run history, duration, stage, correlation
   ID, safe failure category, or troubleshooting next step. Confidence: high.

### Recommended task decomposition

- **BW-046 — Connector execution state and immediate feedback.** Add accessible
  pending feedback, a durable operation state/ID, duplicate protection, and
  success/failure outcome counts without changing connector data or evidence.
- **BW-047 — Bounded automatic stale retries.** Define stale separately from
  failed/disabled/unverified/never-run; add approximately one-minute configurable
  retry behavior with timeout, backoff/jitter, concurrency limits, and visible
  scheduler metadata. Preserve cursor and deduplication semantics.
- **BW-048 — Aggregate Retry All.** Add an admin-only eligible/all scope,
  aggregate operation ID, per-connector queued/running/succeeded/failed/
  skipped/timed-out states, progress, and duplicate protection.
- **BW-049 — Connector diagnostics and bounded run history.** Add last attempt/
  success, duration, next run, retries, scheduler heartbeat, safe redacted
  categories, correlation IDs, likely cause, and operator next steps.

BW-047 depends on BW-046; BW-048 depends on both; BW-049 can begin after BW-046
but should consume the final shared operation contract. All are proposed only.
