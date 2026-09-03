# BlackWatch QA Report — roadmap audit

Cycle focus: release blockers, reproducible bugs, missing verification, and
safe expansion opportunities.

Date: 2026-08-30

## Verification status

- Existing focused UI tests and data-safety tests have passed in prior work.
- Full notification delivery tests remain blocked when the bundled Python
  runtime cannot import `jinja2`/`psycopg`.
- The local UI dependency layout has missing `next`/`typescript` links, so a
  local typecheck/build cannot currently be treated as trustworthy.
- Existing Graphify output is retained, but refresh has previously been
  blocked; no stale graph is treated as current evidence.

## Defect and risk themes

- Cataloged notification actions can differ from runtime producer actions;
  this risks rules that appear configured but never fire.
- Notification create/edit and compatibility routes need one tested canonical
  flow before any page deletion.
- Manual refresh and deferred Live Tail leave analysts without timely evidence
  during active incidents (`docs/ui-design.md`, `docs/threat-hunter.md`).
- Connector failures, queue lag, dead-letter messages, and stale collectors
  need a single operator-facing health view.
- Deployment scripts must prove named-volume identity, migration safety, and
  backup freshness before rebuilds.

No production state or application code was changed by this QA audit.

## Connector UX and reliability investigation — 2026-09-03

Scope: Run Now acknowledgement, stale-connector automation, Retry All,
progress/status visibility, and diagnostics.

### Verification commands and results

- `git status --short` — clean before this QA-only artifact update; no user
  changes were present to overwrite.
- Existing Graphify context was inspected. `graphify-out/graph.json`,
  `GRAPH_REPORT.md`, and `graph.html` exist. The configured Graphify Python
  interpreter could not start on this host (`Access is denied`), so no graph
  refresh/query result was treated as new evidence.
- `pytest -q` — blocked: `pytest` is not recognized by PowerShell.
- `npm run typecheck` from `blackwatch-ui` — blocked: `npm` is not recognized.
- `npm run build` from `blackwatch-ui` — blocked: `npm` is not recognized.
- Static inspection of the connector page, server actions, FastAPI routes,
  runner, scheduler, storage layer, and existing UI helpers completed.

### Confirmed findings

#### BW-046 — Run Now has no immediate acknowledgement or resilient error UI

- Reproduction: open `/connectors`, click `Run now` on a verified connector,
  then observe the UI while the provider call is running or fails.
- Expected: the clicked row immediately changes to a pending state, disables
  duplicate submission, shows that the request was accepted, and then reports
  success/failure without requiring a page refresh.
- Observed: the control is a plain server-action form. The request runs
  synchronously in the backend and the page only changes after a redirect and
  re-render. There is no pending label, spinner, request ID, or inline action
  error. If the server action throws, `postForm()` raises and there is no
  connector-page error boundary or action-level recovery.
- Evidence: `blackwatch-ui/app/connectors/page.tsx:158-169`,
  `blackwatch-ui/app/connectors/actions.ts:12-24,41-47`,
  `blackwatch/ui/views.py:952-957`,
  `blackwatch/connectors/runner.py:22-88`.
- Severity: high. Operators can click repeatedly or assume a failed click was
  ignored, causing duplicate drains and avoidable troubleshooting.
- Regression risk: action feedback must preserve authentication, role checks,
  connector data, and the existing synchronous runner semantics until a safe
  job/status API exists.
- Proposed test: component/action test asserting immediate pending/disabled
  state, successful result, rejected request, and server exception rendering;
  API test asserting the run response has a stable operation/status contract.

#### BW-047 — Scheduler does not retry stale/unverified connectors

- Reproduction: configure a connector, leave it unverified or disabled, or let
  it become stale; wait beyond its configured interval and inspect its
  `last_run_at`/status.
- Expected: an explicitly configured stale retry policy should attempt eligible
  connectors periodically (default about one minute), with bounded backoff,
  visibility into the next attempt, and no retry for intentionally disabled or
  unverified configuration.
- Observed: `_due()` immediately returns false unless both `enabled` and
  `verified` are true. The scheduler only evaluates due connectors every ten
  seconds, and failures update `last_run_at`; there is no retry count, backoff,
  next-run timestamp, or explicit stale-retry state. The scheduler swallows
  unexpected exceptions.
- Evidence: `blackwatch/connectors/scheduler.py:22-30,33-44`,
  `blackwatch/connectors/runner.py:80-88`,
  `blackwatch/storage.py:585-603`.
- Severity: high. A connector can remain silent with no clear distinction
  between disabled, never verified, failed, and awaiting retry.
- Regression risk: automatic retries can create provider/API cost, duplicate
  queue reads, or alert storms. Disabled/unverified connectors must remain
  excluded and retry policy must be bounded and auditable.
- Proposed test: scheduler tests for enabled/verified due connectors, stale
  failure retry, disabled/unverified exclusion, interval boundaries, backoff,
  and recovery transition.

#### BW-048 — No Retry All operation or aggregate run orchestration

- Reproduction: open `/connectors` with multiple failing/stale connectors and
  look for an aggregate recovery action.
- Expected: one explicit `Retry all` control should run only eligible failing
  or stale connectors, show per-connector results, prevent duplicate aggregate
  runs, and preserve disabled/unverified exclusions.
- Observed: the page renders only per-row Test, Run now, Enable/Disable, Edit,
  and Delete controls. No aggregate connector action exists. The existing
  `POST /api/modules/refresh` is module-type scoped, synchronous, admin-only,
  and is used by module pages rather than the connector control plane; it does
  not provide a Retry All operation over stale/failing connector records.
- Evidence: `blackwatch-ui/app/connectors/page.tsx:31-40,148-203`,
  `blackwatch/api.py:509-540`,
  `blackwatch-ui/app/refresh-actions.ts:8-79`.
- Severity: medium-high. Recovery requires repetitive manual actions and
  makes fleet-wide connector outages harder to resolve consistently.
- Regression risk: aggregate execution must not run disabled, unverified, or
  intentionally paused connectors; it must also avoid parallel database pool
  exhaustion and provider rate-limit spikes.
- Proposed test: API/UI tests for eligible selection, mixed success/failure,
  duplicate-click protection, empty selection, and per-connector result
  rendering.

#### BW-049 — Connector status lacks progress, history, and diagnostics

- Reproduction: run a slow or failing connector, then inspect the connector
  row before and after completion and try to determine what it is doing or why
  it failed.
- Expected: show queued/running/succeeded/failed/stale states, started/finished
  times, duration, attempt count, last error category, next retry, and a safe
  diagnostics view with provider/queue checks and correlation ID.
- Observed: the API returns only `last_run_at`, `last_status`, and
  `last_error`. The row displays a timestamp, a status pill, and raw last-error
  text only after completion. There is no run record, in-progress state,
  progress phase, diagnostic action, queue lag, retry count, or reason code.
- Evidence: `blackwatch/api.py:545-563`,
  `blackwatch/storage.py:522-535,585-603`,
  `blackwatch-ui/app/connectors/page.tsx:121-140`.
- Severity: high. Operators cannot reliably tell whether a click registered,
  whether work is still running, or whether the failure is credentials,
  permissions, network, queue, parsing, or database related.
- Regression risk: diagnostics must redact credentials and raw sensitive
  payloads, remain read-only, and avoid introducing a second source of truth
  for connector state.
- Proposed test: contract tests for state transitions and redaction, plus UI
  tests for active progress, stale/failure detail, diagnostics failure, and
  last-known-safe state when the status endpoint is unavailable.

### QA conclusion

The concerns are reproducible from the current implementation. The most
urgent dependency is a durable connector-run status model (BW-049), because
Run Now feedback, Retry All, and automated retry need a shared operation state.
BW-046, BW-047, and BW-048 should be planned against that contract rather than
adding independent toasts or ad-hoc polling. No application source, tests,
rules, deployment files, database data, or production resources were changed.
