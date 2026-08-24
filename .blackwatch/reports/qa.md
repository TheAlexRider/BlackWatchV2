# BlackWatch Cycle — Notification QA Report

**Cycle:** 2026-08-24
**Focus:** module-by-module notification customization

## Baseline verification

| Check | Result | Evidence |
|---|---|---|
| Python syntax compilation | PASS | Bundled Python `compileall -q blackwatch scripts tests` |
| UI typecheck | PASS | Bundled TypeScript `tsc --noEmit --incremental false` |
| `pytest -q` | BLOCKED | `pytest` is not available in the current shell; the project interpreter remains inaccessible |
| `npm run typecheck` | BLOCKED | `npm` is not available in the current shell; bundled TypeScript check passed instead |
| `npm run build` | BLOCKED | `npm` is not available in the current shell; prior bundled Next build hit local workspace-root `EPERM/readlink` |
| Graphify refresh | BLOCKED | Saved Graphify interpreter returns `Access is denied`; existing report is stale |

## Reproducible findings

### QA-001 — Module cards cannot save module-specific message templates

**Severity:** high

**Reproduction:** Open the module-routing path, choose a module, channel, and
threshold, then save. The API endpoint `notif_card_save` calls
`routing_matrix.save_card` with only `enabled`, `channel`, and `threshold`.
`routing_matrix.save_card` writes the generated `auto:<module>` rule without a
`message_template`.

**Observed:** The card can customize routing policy but not its wording or
explanation. The general alert wizard can save a rule-level template, but that
is a separate workflow and does not make the module card itself complete.

**Expected:** A module profile should be able to configure its event kinds,
message content, monitoring explanation, next steps, recovery behavior, and
runbook links without requiring a raw advanced rule.

**Affected files:**

- `blackwatch/api.py` around `notif_card_save`
- `blackwatch/notify/routing_matrix.py` around `save_card`
- `blackwatch/sql/007_notification_rules.sql`
- `blackwatch/sql/021_notification_rule_template.sql`

**Proposed test:** Save a module profile with a template, reload it through the
API, render a matching event, and assert the saved module-specific body is
used.

### QA-002 — The alert wizard's event samples do not control matching

**Severity:** high

**Reproduction:** Create an alert for `ecs.probe`, choose the
`service.down` sample in the message step, and save the route. The saved match
is still only `source.module` plus selected severity values; the sample choice
is not included in the condition.

**Observed:** A template previewed for `service.down` can be delivered for
`service.degraded`, `service.up`, or `probe.agent.stale` when they share the
same module and severity range. This is precisely the cross-kind confusion the
user wants to avoid.

**Expected:** The operator chooses the event kind/action explicitly, or the UI
clearly labels the template as applying to every selected event kind.

**Affected files:**

- `blackwatch-ui/app/notifications/AlertWizard.tsx`
- `blackwatch-ui/app/notifications/wizard-actions.ts`
- `blackwatch/notify/routes_view.py`
- `blackwatch/api.py` notification route save endpoint

**Proposed test:** Save a route for `service.down` and assert a
`service.degraded` event does not use that route/template unless the operator
explicitly selected both actions.

### QA-003 — Producer-formatted messages bypass the central customization model

**Severity:** medium

**Reproduction:** Generate a service transition or probe-agent stale event.
`services/projection.py` and `services/staleness.py` populate
`event.extra.message`. The default channel templates render that field
verbatim.

**Observed:** Message wording is split between producer code and notification
configuration. A channel-level preset cannot independently reshape these
messages, and the source of truth is not visible in the notification UI.

**Expected:** Producer code should emit structured facts; a selected
module/event profile should own the human-facing wording. A compatibility
fallback may keep current messages until a profile exists.

**Affected files:**

- `blackwatch/services/projection.py`
- `blackwatch/services/staleness.py`
- `blackwatch/notify/channels.py`

**Proposed test:** Render the same structured service-down event with two
profiles and assert the output changes without changing the projection code.

### QA-004 — Notification module catalogs under-report active event families

**Severity:** medium

**Reproduction:** Compare `MODULE_CARDS`/`MODULE_CATALOG` with the rule files
under `rules/`. The catalogs cover RDS, CloudTrail, S3, posture, VPN, hosts,
ECS probes, and certificates, while the repository also has API Gateway,
backup, EFS, network, secrets, UEBA, and broader IAM/auth event families.

**Observed:** Operators cannot tell whether an event family is intentionally
unrouted, using a fallback, or simply absent from the module notification UI.

**Expected:** A notification catalog should expose configured, fallback, and
unconfigured states for every supported module/event kind.

**Proposed test:** Build the catalog from the supported event registry/rules
and assert every supported action has a discoverable coverage state.

## QA recommendation

Implement `BW-004` as the cross-module, beginner-friendly Notification Studio
and compatibility layer, then use `BW-005` as the first production pilot. Do
not rewrite every producer message in one pass; the fallback path should keep
existing notifications working while profiles are added module by module.
