# BlackWatch Cycle — IP intelligence in the Investigation flow

**Cycle:** 2026-08-25
**Trigger:** `BLACKWATCH CYCLE`
**Focus:** Make IP investigation a first-class Investigation workflow while retaining Tools access.
**HEAD inspected:** `9cfb8a06b3aa6c298054012f23ff7cc38c6e7000`

## Product conclusion

The user's direction is correct. IP intelligence is not merely a utility
lookup: provider evidence, related indicators, and matching BlackWatch events
form an investigation record. `/investigations` should be the primary place
to start, run, review, annotate, and preserve that evidence. `/tools` should
remain available for a quick, disposable lookup and should offer a clear
handoff into an investigation.

The desired flow is:

```text
Investigation → Investigate IP → create/open case → run enrichment scan
  → normalized provider evidence → related indicators → matching events
  → timeline, notes, status, and follow-up actions

Tools → IP lookup → fast result → Open as investigation (optional)
```

## Existing foundation

- `blackwatch-ui/app/investigations/page.tsx` already provides the durable
  investigation list and describes investigations as the place to preserve
  evidence and connect related events.
- `blackwatch-ui/app/investigations/[id]/page.tsx` and
  `InvestigationNotebook.tsx` already provide an investigation status,
  scan lifecycle, evidence tables/timeline, notes, actions, and matching
  module results.
- `blackwatch/api.py` already exposes investigation creation, retrieval,
  scanning, range updates, notes, and status updates, with IP validation and
  ownership checks.
- `blackwatch-ui/components/domain/IpLookupResult.tsx` now presents provider
  evidence, related indicators, and matching events as a normalized result,
  but the result is still hosted by `/tools/ip-lookup`.
- `blackwatch-ui/components/domain/IpCell.tsx` already supports both
  `Add to investigation` and `Open in IP tool`, proving that both entry points
  are needed.

## Proposed task — BW-007

Make IP intelligence a first-class Investigation workflow. Add an obvious,
accessible IP entry action to the Investigations area, reuse the existing
investigation scan/evidence model, and keep the Tools lookup as a lightweight
entry point with an `Open as investigation` handoff. Avoid creating a second
provider pipeline or duplicating enrichment data.

## Acceptance direction

- A user can start an IP investigation from `/investigations` without first
  opening Tools.
- An IP investigation creates or opens a durable investigation record, runs
  the existing bounded enrichment scan, and shows normalized provider output,
  related indicators, matching events, timeline, notes, and status in the
  Investigation notebook.
- `/tools/ip-lookup` remains available for quick lookups and includes a clear
  handoff to the corresponding investigation; existing event-cell actions
  continue to work.
- Provider results have one shared presentation model and do not trigger
  duplicate provider requests merely because the user entered through Tools
  or Investigations.
- Loading, unavailable-provider, invalid-IP, empty-evidence, and scan-failure
  states are understandable in both entry points.
- The behavior is covered by focused UI/API tests, including creation,
  handoff, ownership, scan status, and preservation of existing Tools access.
- Any persistence change is additive and must pass the project's data-safety
  contract; no compose/build action may remove existing investigation or
  provider data.

## Risks and decisions

- Do not make the Tools page the canonical case store; disposable lookups and
  durable investigations have different user intent.
- Decide whether repeated investigation scans refresh an existing result set,
  append a new scan version, or both. Preserve the existing evidence history
  when refreshing.
- Avoid silently creating duplicate investigations for the same IP; offer
  reuse/open behavior or make the duplicate decision explicit.
- Keep provider credentials server-side and keep provider provenance visible,
  but secondary to the normalized BlackWatch output.
