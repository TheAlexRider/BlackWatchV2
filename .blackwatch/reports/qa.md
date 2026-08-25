# BlackWatch Cycle — IP investigation flow QA report

**Cycle:** 2026-08-25
**Trigger:** `BLACKWATCH CYCLE`
**Focus:** IP investigation as the primary Investigation workflow, with Tools retained.
**HEAD inspected:** `9cfb8a06b3aa6c298054012f23ff7cc38c6e7000`

## Reproducible findings

### QA-001 — The rich IP workflow is currently owned by Tools

**Severity:** high

**Evidence:** `blackwatch-ui/app/tools/ip-lookup/page.tsx` owns the IP form,
fetches the enriched result, and links back to `/tools`. The current
`IpLookupResult` includes provider evidence, related indicators, and matching
events, so the most valuable investigative output is nested under the Tools
route.

**Expected:** Investigations should own the durable IP evidence workflow;
Tools should remain a quick lookup surface.

### QA-002 — Investigations already has the required durable lifecycle

**Severity:** observation

**Evidence:** `blackwatch-ui/app/investigations/InvestigationNotebook.tsx`
already handles scan requests, polling, status, notes, evidence tables,
timeline/activity, and follow-up actions. `blackwatch/api.py` provides
validated IP creation plus scan, range, notes, and status endpoints.

**Implication:** This is primarily a routing/entry-point and data-presentation
integration task, not a reason to build a parallel IP case system.

### QA-003 — Tools and event-cell actions need an explicit handoff contract

**Severity:** high

**Evidence:** `IpCell.tsx` currently offers `Add to investigation` and
`Open in IP tool` as separate actions. The standalone Tools result has no
visible durable-investigation handoff in the inspected page.

**Expected:** Every quick IP lookup should make the next action obvious:
`Open as investigation` or `Add to investigation`, with reuse behavior that
does not create accidental duplicate cases.

### QA-004 — The two flows must not drift in enrichment output

**Severity:** medium

**Evidence:** The Tools route calls `/api/tools/ip-lookup`, while the
Investigation scan is handled by the investigation worker and result tables.
These paths need a defined shared normalization boundary or explicit mapping.

**Expected:** Provider evidence, related indicators, matching events, status,
and provenance should have the same labels and semantics regardless of entry
point. A provider failure must remain isolated and must not fail the case.

## Proposed verification

- Render `/investigations` with the IP-start action and verify valid/invalid
  IPv4 and IPv6 behavior.
- Create an investigation from Tools and from an event-cell action; verify
  the user lands on the same owned investigation notebook.
- Run a scan and verify queued/running/completed/failed states, provider
  partial failure, empty evidence, notes, and matching events.
- Reopen or rescan the same investigation and verify no duplicate case or
  destructive replacement of prior evidence.
- Verify direct Tools lookup still works without creating a case unless the
  user chooses the handoff.
- Run UI typecheck/build and focused API/storage/data-safety tests.

## Baseline limitations

- Graphify refresh was attempted but the saved interpreter returned
  `Access is denied`; the existing report is stale relative to HEAD.
- The delegated R&D and QA workers did not return within the bounded cycle
  window; this report was reconciled by the coordinator from direct repository
  evidence. No application files were changed by the cycle.
