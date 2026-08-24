# BW-002 Coverage Surface Implementation Plan

## Goal

Add a compact `/coverage` overview that tells operators which configured
collectors are healthy, stale, failing, unverified, or disabled, and links each
collector to the existing module surface.

## Design decisions

- Freshness is measured at the connector last-run level for this first version.
- A successful run is healthy even if it ingested zero events.
- No database migration is required; the endpoint derives its view from the
  existing connector records.
- The page is an overview and navigation surface, not a duplicate of each
  module's detailed table.

## Steps

1. Add pure coverage classification logic and tests.
2. Add `GET /coverage` to the backend.
3. Add typed UI API support, a `/coverage` page, and navigation.
4. Replace BW-001 with the proposed deep IP enrichment direction and remove
   BW-003 from the BlackWatch task registry.
5. Run focused backend tests, syntax checks, UI typecheck, and the BlackWatch
   contract validator.
