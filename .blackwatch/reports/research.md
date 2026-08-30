# BlackWatch R&D Report — notification completion and UI consolidation

Cycle focus: verify BW-020–BW-030, then identify unnecessary pages and broken or confusing destinations.

Date: 2026-08-30

## Executive assessment

BW-020 through BW-030 have implementation and focused-test artifacts in the current worktree, including dedicated notification contracts, producer normalization, catalog metadata, and per-task test files. The latest review handoffs report passing focused and data-safety checks. However, the canonical task files still say `status: proposed` and `implementation_allowed: false`, the changes are uncommitted, and the prior full-suite verification was blocked by missing runtime dependencies. Therefore the work is functionally advanced but not yet release-closed or independently auditable from repository state alone.

The next safe sequence is one completion gate for BW-020–BW-030, followed by four UI information-architecture/linking tasks. Do not delete a route until incoming links, redirects, bookmarks, and server-side destinations are covered by tests or an intentional compatibility redirect.

## Findings

### R-01 — BW-020–BW-030 need a durable completion gate

Affected area: notification contracts, task metadata, tests.

Evidence:

- `.blackwatch/tasks/BW-020.yaml` through `.blackwatch/tasks/BW-030.yaml` all remain `status: proposed` with `implementation_allowed: false`.
- The worktree contains implementation changes in `blackwatch/notify/content_contracts.py`, `blackwatch/notify/profiles.py`, `blackwatch/notify/catalog.py`, producer modules, and focused tests `tests/test_bw020_*.py` through `tests/test_bw030_*.py`.
- `.blackwatch/reports/qa.md` records that earlier full verification was blocked by missing `psycopg`/`jinja2`, and the prior cycle state records Graphify refresh as blocked.

Impact: operators cannot distinguish “implemented and reviewed” from “proposed” by reading durable project artifacts. A false rollout status could expose incomplete notification contracts or hide untested delivery behavior.

Recommendation: create an explicit completion audit that checks producer-to-catalog parity, contract coverage, missing-field behavior, exact email/chat rendering, recovery semantics, and data-safety tests for BW-020–BW-030. Keep blocked checks visibly blocked; do not mark completion based only on focused tests.

Confidence: high.

### R-02 — Rule editing has two destinations for the same object

Affected area: notification rule authoring UI.

Evidence:

- `blackwatch-ui/app/notifications/page.tsx:458` sends the main rule table’s Edit action to `/notifications/rules/{id}/edit`.
- `blackwatch-ui/app/notifications/rules/[id]/edit/page.tsx` branches between `AlertWizard` and `RuleForm` based on rule kind.
- `blackwatch-ui/app/notifications/rules/[id]/page.tsx` separately renders `RuleForm` for the same rule ID.
- `blackwatch-ui/app/notifications/rules/new/page.tsx` has its own preset-picker/form flow, while `/notifications/create` → `/notifications/create/event` uses `AlertWizard`.

Impact: the same notification rule can appear to have multiple edit pages with different headers, back links, and data-fetch paths. Users can land on a different editor depending on which link they click.

Recommendation: choose one canonical route per rule kind and make the other route a compatibility redirect, or make one shared page component the only renderer. Preserve old URLs with redirects until compatibility policy permits removal.

Confidence: high.

### R-03 — Legacy notification pages are redirect-only

Affected area: notification information architecture.

Evidence:

- `blackwatch-ui/app/notifications/routing/page.tsx` only redirects to `/notifications`.
- `blackwatch-ui/app/notifications/perf-alerts/quick/page.tsx` only redirects to `/notifications`.
- Their comments explicitly say the old pages were folded into the main dashboard.
- The current dashboard already links to the canonical log, profile, channel, rule, and performance-alert paths.

Impact: the route tree is larger than the actual product and stale links are harder to detect. Deleting these pages outright would break bookmarks.

Recommendation: remove internal links to these paths, document them as compatibility routes, and delete only after a deliberate compatibility window.

Confidence: high.

### R-04 — IP lookup is duplicated across Tools and Investigations

Affected area: investigation workflow and analyst navigation.

Evidence:

- `blackwatch-ui/app/investigations/InvestigationStartForm.tsx:21-34` starts an investigation by POSTing the IP to `/api/investigations`.
- `blackwatch-ui/app/tools/ip-lookup/page.tsx:52-102` independently owns a full IP lookup page.
- `blackwatch-ui/components/domain/IpCell.tsx:73` navigates to `/tools/ip-lookup`, while the same component also offers “Add to investigation”.
- `blackwatch-ui/components/domain/IpLookupModal.tsx:68-71` also links to `/tools/ip-lookup`.
- `blackwatch-ui/lib/investigation-flow.ts` already centralizes investigation URL helpers, but some IP controls bypass it.

Impact: analysts lose investigation context and experience duplicate lookup paths.

Recommendation: make investigation detail the canonical destination for IP enrichment and automatic lookup; keep Tools as a secondary standalone entry point. Route investigation-intent IP actions through the shared helper.

Confidence: high.

### R-05 — Navigation/link destinations need a generated contract before deletion

Affected area: global navigation, cross-module links, route maintenance.

Evidence:

- `blackwatch-ui/components/layout/SideNav.tsx:38-64` exposes top-level destinations, while notification subpages and detail pages are reached indirectly.
- Cross-module links target `/events/{id}`, `/aws-posture/{id}`, `/notifications/...`, and `/tools/ip-lookup`; the route tree contains dynamic pages and compatibility redirects.
- Existing tests include `blackwatch-ui/lib/investigation-flow.test.ts` and `responsive-layout.test.ts`, but no visible route-manifest test verifies every internal destination.

Impact: deleting a page based only on sidebar visibility can break deep links, action buttons, or server redirects.

Recommendation: add a static route manifest and link-integrity test covering internal href, redirect, and form-action destinations. Use it to identify genuinely unreachable pages before removal.

Confidence: high.

## Proposed next five tasks

1. **BW-031 — Close the BW-020–BW-030 notification release gate**
2. **BW-032 — Unify notification rule create/edit destinations**
3. **BW-033 — Consolidate notification navigation and retire internal legacy paths**
4. **BW-034 — Make Investigations the canonical IP investigation flow**
5. **BW-035 — Add route/link integrity and safe page-deletion inventory**

These are proposed only. Each requires explicit `IMPLEMENT BW-###` approval. No application code, tests, docs, deployment, or data were modified by this R&D role.
