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
