# Actionable Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace generic notification prose with compact, fact-rich, module-specific and actionable notifications, starting with VPN and then rolling out safely across the catalog.

**Architecture:** Keep the existing profile/rule/channel routing pipeline. Add an explicit event content contract to the notification catalog, render compact fact/action sections from the real event, and preserve advanced templates and existing channel delivery. The UI will derive its editable fields and preview samples from the selected event contract.

**Tech Stack:** Python notification catalog/profile service/Jinja renderer, PostgreSQL-backed existing notification profiles, Next.js/React Notification Studio, pytest/unittest fixtures.

**Spec:** `.blackwatch/tasks/BW-011.yaml`, `.blackwatch/tasks/BW-012.yaml`, `.blackwatch/tasks/BW-013.yaml`.

## Global Constraints

- Existing notification profiles, routing, channels, audit history, delivery history, and collected data must be preserved.
- Any database change must be additive; no `DROP`, `TRUNCATE`, destructive migration, or `docker compose down -v`.
- Explicit advanced templates remain authoritative.
- Missing event facts are omitted; no fabricated sample values may reach a delivered notification.
- Implement BW-011 before BW-012, and BW-012 before BW-013.

### Task 1: BW-011 — Content contract and renderer

**Files:**
- Modify: `blackwatch/notify/profiles.py`
- Modify: `blackwatch/notify/profile_service.py`
- Modify: `blackwatch/notify/channels.py`
- Modify: `blackwatch-ui/app/notifications/profiles/[id]/page.tsx`
- Modify: `blackwatch-ui/components/domain/notifications/ProfilePreview.tsx`
- Test: `tests/test_notification_profiles.py`
- Test: `tests/test_notification_rendering.py`

**Interfaces:**
- Catalog event specs expose `content_schema`, `defaults`, and `preview_sample`.
- The profile renderer receives the stored profile plus a real event and produces a compact default unless `advanced_template` is set.
- The UI reads event-specific fields from the profile API and uses the same preview renderer as delivery.

- [ ] Write failing tests for compact default rendering, omission of missing facts, advanced-template precedence, and preservation of channel formatting.
- [ ] Run the focused tests and confirm they fail for the missing contract/renderer behavior.
- [ ] Add the smallest event-content contract representation and a compact renderer that emits a title, facts, action, and optional recovery/runbook lines.
- [ ] Keep the existing profile storage shape compatible; derive new defaults from catalog metadata rather than deleting or rewriting saved rows.
- [ ] Update the profile API/UI field metadata and preview copy to be event-specific while retaining an advanced-template escape hatch.
- [ ] Run focused backend and UI checks available in the environment.

### Task 2: BW-012 — VPN notification pilot

**Files:**
- Modify: `blackwatch/notify/profiles.py`
- Modify: `blackwatch/notify/profile_service.py`
- Modify: `blackwatch/modules/vpn_openvpn.py` only if a safe display field is required
- Modify: `blackwatch-ui/app/notifications/profiles/[id]/page.tsx`
- Test: `tests/test_vpn.py`
- Test: `tests/test_notification_rendering.py`

**Interfaces:**
- `vpn.auth.failure` uses the contract from BW-011 and renders principal, source IP, event time, VPN server, evidence, and response guidance when present.
- `vpn.auth.success` remains concise and informational.
- Partial journal events render without invented identity or network data.

- [ ] Add failing golden tests for complete VPN failure, missing source IP, and VPN success output.
- [ ] Run the tests and verify the expected failures.
- [ ] Define VPN-specific facts and action guidance in the catalog; do not hard-code unsafe remediation such as automatic revocation.
- [ ] Add representative VPN preview data and ensure live recent-event preview uses the same output path.
- [ ] Run the VPN and notification test set and verify no generic placeholder prose appears.

### Task 3: BW-013 — Module rollout and coverage guard

**Files:**
- Modify: `blackwatch/notify/profiles.py`
- Modify: `blackwatch/notify/catalog.py`
- Modify: `blackwatch-ui/app/notifications/page.tsx`
- Modify: `blackwatch-ui/app/notifications/profiles/page.tsx`
- Modify: `blackwatch-ui/app/notifications/profiles/[id]/page.tsx`
- Test: `tests/test_notification_catalog.py`
- Test: `tests/test_notification_profiles.py`
- Test: `tests/test_notification_rendering.py`

**Interfaces:**
- Coverage reports `rolled_out`, `configured`, `muted`, `fallback`, and `unconfigured` distinctly.
- High/critical events without an explicit module-specific contract are visible gaps, never silently complete defaults.
- Rollout metadata identifies VPN, EC2/SSH, RDS, ECS, IAM, S3, certificates, UEBA, and findings.

- [ ] Add failing coverage tests for rollout state and generic fallback detection.
- [ ] Run focused tests and verify the guard fails against remaining generic catalog events.
- [ ] Add rollout metadata and module-specific defaults in batches without changing event identifiers or stored profile IDs.
- [ ] Update the UI coverage and profile editor to show event-specific fields and rollout state.
- [ ] Run the full notification test set and available typecheck/build; record unavailable tooling honestly.

## Verification checklist

- [ ] `pytest -q tests/test_notification_profiles.py tests/test_notification_catalog.py tests/test_notification_rendering.py tests/test_vpn.py`
- [ ] `npm run typecheck` from `blackwatch-ui`
- [ ] `npm run build` from `blackwatch-ui`
- [ ] `git diff --check`
- [ ] Confirm only intended application/tests plus plan/task status files changed.
- [ ] Confirm no destructive SQL, Compose volume change, or deployment mutation.
