# BlackWatch Cycle — Module-specific Notifications R&D

**Cycle:** 2026-08-24
**Trigger:** `BLACKWATCH CYCLE`
**Focus:** module-by-module notification customization
**HEAD inspected:** `84f4989f61e6a9638d0a590d92711af0e013f20d`

## Product conclusion

Yes, this is a strong direction. BlackWatch should keep one shared delivery
and routing engine, but expose notification behavior as module-specific,
event-kind-specific profiles. A service outage, a certificate expiry, an IAM
change, and a probe-agent silence event should not be forced into one generic
message or one generic configuration panel.

The right boundary is:

```text
module + event kind
  -> trigger and severity policy
  -> channel, throttle, digest, silence, recovery behavior
  -> structured message profile
       what happened · why it matters · evidence · monitoring method
       next steps · runbook links · recovery wording
  -> existing shared channel delivery
```

This preserves the current asynchronous worker, retries, rate limits, acks,
and delivery log while making the content and operating policy specific to the
thing being monitored.

## Existing foundation

- `blackwatch/notify/model.py` already supports `NotificationRule` with a
  condition tree, channel list, throttling, silence, and an optional
  `message_template`.
- `blackwatch/notify/channels.py` already supports per-channel-type presets
  and rule-level Jinja overrides.
- `blackwatch/notify/routing_matrix.py` already models a curated module card,
  but the card only stores enabled/channel/threshold/silence and does not store
  a message template or event-kind selection.
- `blackwatch-ui/app/notifications/AlertWizard.tsx` previews a few event
  samples, but the selected sample is preview-only; it does not constrain the
  route to that event action.
- `blackwatch/services/projection.py` and `blackwatch/services/staleness.py`
  build hardcoded `extra.message` bodies for service transitions and probe
  silence. The default channel templates pass those bodies through verbatim.

## Scope findings

### R&D-001 — Build a cross-module Notification Studio

The current rule/template split is a good execution primitive, but a raw Jinja
textarea is too low-level for technical users who need to explain monitoring,
impact, and remediation. Build a guided Notification Studio whose primary unit
is the module: EC2, RDS, VPN, IAM, S3, API Gateway, FIM, UEBA, certificates,
services, posture, and every other supported area. Within each module, users
choose a plain-language alert type and edit structured message fields. Keep
rules as the dispatch source of truth, with profiles compiled into or attached
to the existing rule rows rather than creating a second delivery pipeline.

Proposed task: `BW-004` (reframed as the complete cross-module product).

### R&D-002 — Validate the model on services and probe agents

The ECS/service domain already distinguishes `service.down`,
`service.degraded`, `service.up`, `probe.agent.stale`,
`probe.agent.recovered`, and `probe.agent.first_seen`. These are a useful first
validation set because they already distinguish multiple event kinds and
contain rich context. They are not the product scope; the same Studio must
later cover all supported modules.

Proposed task: `BW-005`.

### R&D-003 — Make notification coverage discoverable

The notification catalogs are hardcoded and incomplete compared with the
rule/event surface. `MODULE_CARDS` and `MODULE_CATALOG` do not currently list
several active areas such as API Gateway, IAM, backup, EFS, network, secrets,
UEBA, and several host event families. Operators need to see which event kinds
have a profile, which use a fallback, and which are intentionally muted.

Proposed task: `BW-006`.

## Product guardrails

- The profile must distinguish detection facts from operator-authored
  explanation and remediation text.
- Provider/channel delivery remains centralized; only policy and content vary
  by module/event kind.
- A missing profile falls back safely to the existing event/channel rendering;
  it must never suppress an event or block ingestion.
- Templates must be previewable against representative real or synthetic
  events, with the available fields shown explicitly.
- Runbook links and next steps are optional per event kind, but the UI should
  make their absence visible for high-severity notifications.
