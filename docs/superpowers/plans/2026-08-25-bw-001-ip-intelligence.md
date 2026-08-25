# BW-001 IP Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing IP lookup with cached, source-attributed threat enrichment and bounded investigation pivots without making provider API keys mandatory.

**Architecture:** Keep `ip-api.com` as the fast path and add a server-side provider adapter layer in the Next.js route. Each optional provider reports its own state (`success`, `not_configured`, `rate_limited`, or `error`), while normalized results expose only safe investigation fields. The UI renders provider status, local-feed context, related indicators, and observed BlackWatch events without storing credentials or changing application data.

**Tech Stack:** Next.js 15 route handlers, React server components, TypeScript, Node's built-in test runner, existing BlackWatch event API, existing local threat-feed enrichment.

**Spec:** `.blackwatch/tasks/BW-001.yaml`

## Global Constraints

- The existing `ip-api.com` lookup must continue working when every optional provider is unavailable.
- Provider API keys are read only from server-side environment variables and are never returned to the browser.
- Provider failures and rate limits are isolated and visible; they must not hide successful results.
- Caching is bounded and keyed by the observable/provider, never by raw credentials.
- Do not add database migrations, destructive SQL, event writes, or production mutations.
- Preserve all unrelated user changes already present in the worktree.

---

### Task 1: Provider normalization and validation contract

**Files:**
- Create: `blackwatch-ui/lib/ip-intelligence.ts`
- Test: `blackwatch-ui/lib/ip-intelligence.test.ts`

**Interfaces:**
- Produces `isValidObservable`, `normalizeProviderStatus`, `extractIndicators`, and the shared response types used by the route and UI.

- [ ] Write tests first for valid IPv4/IPv6/hostname input, invalid input rejection, provider status normalization, and deduplicated indicator extraction.
- [ ] Run the focused Node test and confirm it fails because the module is missing.
- [ ] Implement the smallest pure helpers and types needed by the tests.
- [ ] Run the focused Node test and confirm it passes.

### Task 2: Server-side provider adapters and safe caching

**Files:**
- Create: `blackwatch-ui/lib/ip-intelligence-server.ts`
- Modify: `blackwatch-ui/app/api/tools/ip-lookup/route.ts`

**Interfaces:**
- Consumes the pure normalization helpers from Task 1.
- Produces a response containing the existing `ip-api.com` fields plus `providers`, `indicators`, and `observedEvents`.

- [ ] Add server-only adapters for GreyNoise Community, AbuseIPDB, and VirusTotal using their documented environment variables.
- [ ] Map missing keys, HTTP 429 responses, upstream errors, and successful responses to explicit provider states without returning secrets.
- [ ] Use bounded Next.js fetch revalidation for provider results and preserve the fast-path result if optional calls fail.
- [ ] Add bounded event pivots through the existing authenticated BlackWatch events endpoint, extracting only deduplicated safe indicators.
- [ ] Validate the requested observable before any upstream call and return HTTP 400 for unsafe input.

### Task 3: Lookup presentation and operator guidance

**Files:**
- Modify: `blackwatch-ui/components/domain/IpLookupResult.tsx`
- Modify: `blackwatch-ui/app/tools/ip-lookup/page.tsx`
- Modify: `blackwatch-ui/components/domain/IpLookupModal.tsx`
- Modify: `.env.example`
- Modify: `docs/threat-intel.md`

**Interfaces:**
- Consumes the response produced by Task 2.

- [ ] Render provider-by-provider availability, provenance, confidence, rate-limit messaging, and optional-key guidance.
- [ ] Render local-feed matches and a bounded investigation trail for domains, certificates, URLs, hashes, and observed events.
- [ ] Keep the modal compact and preserve the full-page investigation experience.
- [ ] Document exactly which accounts are optional and where their server-side keys belong.

### Task 4: BW-001 record and verification

**Files:**
- Modify: `.blackwatch/tasks/BW-001.yaml`

- [ ] Record the explicit approval and the no-key-first provider policy.
- [ ] Run focused tests, the UI typecheck, the UI production build, and relevant Python regression tests.
- [ ] Inspect the final diff and confirm no database schema/data files were changed.

