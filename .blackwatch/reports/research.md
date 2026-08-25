# BlackWatch Cycle — event-by-event notification planning

**Focus:** Every module and every notification event kind gets a unique content
contract while retaining one consistent high-level notification shape.

**State inspected:** Current working tree, including BW-011/BW-012/BW-013
notification changes. Existing user changes were preserved.

**Boundary:** Analysis only. No application source, tests, rules, deployment
files, or documentation were changed. All new work items are proposed and
implementation-disabled.

## Executive finding

The common notification structure is a good foundation, but the current catalog
is not yet a complete event contract registry. It contains 158 cataloged events
across 17 modules. The CloudTrail adapter alone maps 141 unique AWS API
operations to normalized actions, and 84 of those producer actions have no
catalog entry. Other producers also emit actions absent from the catalog,
including host state-diff events, VPN session events, and RDS lifecycle events.

The next phase must therefore reconcile, for every module and every event kind:

1. producer and derived actions;
2. fields genuinely present in the normalized event;
3. fields missing but needed for an operator decision;
4. event-specific wording, decision, response, and closure behavior; and
5. preview fixtures and golden rendering.

The consistent outer body should remain:

```text
[short event-specific headline]
What happened: [one precise sentence]
Facts: [only the facts needed to decide]
Decision: [what the recipient should determine first]
Next steps: [ordered response, containment, or owner action]
Recovery: [matching recovery/closure condition, or no automatic recovery]
Evidence: [traceable source, event ID, rule, or runbook link when useful]
```

The labels stay consistent. The factual fields, order, decision question,
response instructions, safe disclosure rules, and recovery semantics are owned
by each event kind.

## Evidence and current architecture

- `blackwatch/event.py:90-139` defines the normalized envelope: source,
  event time, action, outcome, actor, target, observables, severity, raw, and
  `extra`. Missing optional fields are normal and must be omitted, not replaced
  with invented prose.
- `blackwatch/notify/profiles.py:16-166,341-710` defines the common content
  fields, catalog, and module rollout metadata. Generic fallback still exists
  for most events.
- `blackwatch/notify/profiles.py:743-761` compiles guided content into a
  message template. `blackwatch/notify/channels.py:417-432` gives a rule-level
  template precedence over a channel template, so event-specific profiles are
  the correct content owner.
- `blackwatch/notify/catalog.py:144-215` already provides per-event delivery
  coverage and should become the surface for delivery and content coverage.
- `blackwatch-ui/app/notifications/profiles/[id]/page.tsx:55-168` already
  filters the editor by event metadata and shows contract status. Each rollout
  should extend that metadata with event facts and preview fixtures.
- `blackwatch/modules/aws_cloudtrail.py:35-232,862-1100` maps AWS API calls,
  extracts actor/target/request context, computes security flags, and creates
  friendly messages for IAM, S3, network, compute, storage, RDS control plane,
  EFS, Backup, Secrets, KMS, and CloudTrail events.
- `blackwatch/modules/aws_api_gw.py:126-307` deliberately limits API telemetry
  to source IP, method, route key, status, latency, response size, error type,
  and user agent. Contracts must not ask for URL paths or identity headers that
  the adapter intentionally does not ingest.
- `blackwatch/modules/aws_rds.py:273-555` emits database session, auth, proxy,
  query, and error facts from PostgreSQL and RDS Proxy logs. Derived alerts are
  produced in `blackwatch/rds/projection.py` and `blackwatch/rds/staleness.py`.
- `blackwatch/modules/ec2_host.py:100-365`, `blackwatch/hosts/diff.py:20-170`,
  and `blackwatch/hosts/projection.py:350-515` split host telemetry between
  agent facts and state-transition facts. Both origins must be visible in the
  final evidence line.
- `blackwatch/modules/vpn_openvpn.py:198-410` emits VPN auth, health, status,
  and certificate facts. `blackwatch/vpn/projection.py` derives session and
  service transitions.
- `blackwatch/modules/ecs_probe.py:51-111` emits probe heartbeats and service
  probe results; `blackwatch/services/projection.py:104-475` derives hysteresis,
  outage, degradation, unknown-state, and recovery events.
- `blackwatch/ueba/check.py:45-112` creates anomaly events from first-seen
  baseline dimensions. `blackwatch/modules/generic.py:32-72` is the fallback
  finding/webhook path, so findings need a typed minimum evidence contract.

## Catalog parity finding

Static comparison found 158 profile events, 141 unique CloudTrail actions, and
84 CloudTrail actions not represented in the notification catalog. Important
producer-only actions include IAM group/boundary/policy lifecycle, additional
KMS lifecycle actions, network topology create/delete/replace actions, RDS
cluster/snapshot/parameter-group lifecycle, S3 lifecycle/encryption actions,
EFS creation, Backup vault creation, Secrets value access, and EBS volume/
snapshot lifecycle.

These actions are not safe to call covered until they have an explicit contract
or an intentional non-notifying classification. Every module task below
includes this parity gate.

## Event-by-event contract inventory

“If present” is intentional: the renderer must omit unavailable values and must
not claim a user, IP, resource, threshold, impact, or recovery that the event
did not contain.

### 1. OpenVPN — `vpn.openvpn`

The authentication pilot exists, but the remaining VPN event kinds still need
unique contracts. Auth failure and success remain golden examples.

- `vpn.service.down` — Facts: VPN server, state, host/instance, last heartbeat,
  age, agent version. Decision: VPN down or monitoring stale? Next steps: check
  service process, host reachability, and recent restart/deploy. Recovery:
  `vpn.service.up` after a healthy heartbeat.
- `vpn.auth.failure` — Facts: user, source IP, server, time, failure line,
  outcome. Decision: did this user initiate it? Next steps: verify user/source,
  then investigate or contain credentials if unexpected. A later successful
  login is evidence, not automatic closure.
- `vpn.bruteforce` — Facts: source IP, failure count/window, server, sample
  users. Decision: attack or repeated client misconfiguration? Next steps:
  verify source ownership, rate-limit/block only under runbook, and review users.
  Recovery is a quiet/resolved detector, not one success.
- `vpn.session.concurrent` — Facts: identity, simultaneous IPs, server, client
  count, observation time. Decision: multi-device use or credential sharing?
  Next steps: confirm owner and terminate/rotate if unauthorized.
- `vpn.cert.expired` — Facts: certificate name/kind, subject, issuer, endpoint,
  expiry, days, revoked flag, server. Decision: which service/client is
  impacted? Next steps: renew/replace and verify chain. Recovery: healthy cert
  observation.
- `vpn.cert.probe.failed` — Facts: certificate identity, endpoint/path, probe
  error, server, last success if known. Decision: cert issue or probe issue?
  Next steps: test reachability before rotating cert. Recovery: next successful
  probe.
- `vpn.cert.expiring.critical` — Facts: certificate, exact expiry, days,
  endpoint, issuer, server. Decision: can renewal finish before deadline? Next
  steps: assign owner and renew immediately. Recovery: healthy renewal.
- `vpn.cert.expiring.high` — Facts: same identity/expiry facts and warning band.
  Decision: planned renewal? Next steps: verify owner and change window.
- `vpn.cert.expiring.warning` — Facts: identity, expiry, days, endpoint, owner
  if available. Decision: is it in the renewal queue? Next steps: schedule and
  verify monitoring.
- `vpn.auth.success` — Facts: user, source IP, server, time, method if present.
  Decision: expected successful access? Next steps: verify high-risk unfamiliar
  source; otherwise informational. No recovery event.
- `vpn.bruteforce.user` — Facts: targeted user, source IPs, count/window,
  server. Decision: targeted account attack or user error? Next steps: protect
  account and investigate source. Recovery is a quiet/resolved detector.
- `vpn.service.up` — Facts: server, heartbeat time, uptime/agent version,
  outage duration if available. Next steps: confirm reconnects and review cause.
  Recovery: pairs with `vpn.service.down`.
- `vpn.session.start` — Facts: user/common name, real IP, server, time, session
  identity. Decision: expected session? Next steps: verify owner/source for
  unusual sessions. Recovery: `vpn.session.end`.

Producer gap: `vpn.session.end` is emitted by `blackwatch/vpn/projection.py` but
is absent from the catalog and needs a profile or explicit non-notifying status.

### 2. EC2 host — `ec2.host`

Host notifications must distinguish access, persistence, integrity, resource
health, collector coverage, and state-diff signals.

- `host.agent.stale` — Facts: instance/hostname, last seen, age, stalled
  collectors, tags, agent version. Decision: host down or agent disconnected?
  Next steps: check agent, reachability, IAM/SQS, and last error. Recovery:
  `host.agent.recovered`.
- `host.agent.recovered` — Facts: instance, silence duration, heartbeat time,
  agent version, collector state. Decision: is telemetry trustworthy again?
  Next steps: review the blind interval. Recovery: pairs with stale.
- `host.auth.ssh.failure` — Facts: username, source IP, auth method/reason,
  host, time, journal line. Decision: expected failure or attack? Next steps:
  check account/source and investigate brute force. No direct recovery.
- `host.auth.ssh.password.success` — Facts: user, source IP, host, password
  method, time. Decision: was password SSH access allowed? Next steps: verify
  owner and key-only policy. No recovery.
- `host.auth.ssh.success` — Facts: user, source IP, host, method, time. Decision:
  expected access or suspicious/root access? Next steps: verify if unfamiliar.
- `host.bruteforce` — Facts: source IP, count/window, host, sample usernames,
  last failure. Decision: attack or noisy client? Next steps: verify source and
  contain under runbook. Recovery: quiet/resolved detector.
- `host.bruteforce.user` — Facts: targeted user, source IP, count/window, host.
  Decision: targeted attack? Next steps: protect account and investigate source.
- `host.sudo.failure` — Facts: user, command if captured, reason, host, time,
  journal evidence. Decision: unauthorized privilege attempt or operator error?
  Next steps: verify user/command and inspect nearby successful sudo. Producer
  gap: current classifier emits no command or reason for this event.
- `host.authorized_key.added` — Facts: host, OS user, key fingerprint/preview,
  actor if available, time. Decision: approved deployment or persistence? Next
  steps: verify owner/change ticket and remove if unexpected.
- `host.user.added` — Facts: username, UID, shell, host, actor/source. Decision:
  approved account creation? Next steps: verify owner, group/sudo access, and
  expiry. Recovery action `host.user.removed` is producer-supported but absent.
- `host.port.opened` — Facts: protocol, bind address, port, process, instance.
  Decision: intended listener or exposure? Next steps: identify process, verify
  SG reachability, and close/contain if unexpected. `host.port.closed` is absent.
- `host.fim.modified` — Facts: path, hashes, size/perms/owner, actor, detection
  source, host. Decision: approved deployment or tampering? Next steps: compare
  ticket and inspect diff. No generic recovery.
- `host.fim.deleted` — Facts: path, previous hash/owner/perms, actor, host.
  Decision: intentional removal or destructive action? Next steps: restore or
  contain under runbook.
- `host.fim.created` — Facts: path, new hash/size/owner/perms, actor, host.
  Decision: expected file or persistence? Next steps: identify creator and
  inspect content safely.
- `host.fim.perm_changed` — Facts: path, permissions before/after, owner,
  hashes, actor. Decision: access widened? Next steps: validate expected mode and
  restore least privilege.
- `host.fim.owner_changed` — Facts: path, owner before/after, permissions,
  hash, actor. Decision: expected transfer or privilege change? Next steps:
  verify owner and restore least privilege.
- `host.fim.coverage` — Facts: files monitored, scan time, gaps/errors, host.
  Decision: can integrity silence be trusted? Next steps: repair collector.
  Recovery: next healthy coverage report.
- `host.service.added` — Facts: systemd unit, enablement, host, actor/source.
  Decision: approved service or persistence? Next steps: inspect unit/executable.
  `host.service.removed` is producer-supported but absent.
- `host.cpu.anomaly` — Facts: normalized/raw load, CPU count, baseline mean/
  stdev/sample count, host. Decision: attack/workload anomaly or batch? Next
  steps: inspect processes/deploy/capacity. Recovery: `host.cpu.normal`.
- `host.cpu.normal` — Facts: current load, host, anomaly duration if retained.
  Next steps: review timeline; informational after stable normal streak.
- `host.cron.changed` — Facts: cron path, added/removed/changed, hash/detection,
  host, actor. Decision: persistence or deployment? Next steps: inspect schedule
  and executable owner.
- `host.disk.critical` — Facts: mount, used percentage, total, filesystem, host.
  Decision: imminent failure or growth? Next steps: identify consumers and
  free/expand. Recovery: `host.disk.recovered`.
- `host.disk.warn` — Facts: same disk facts plus warning band. Next steps:
  forecast and clean/expand. Recovery: `host.disk.recovered`.
- `host.disk.recovered` — Facts: mount, current usage, prior band, time. Next
  steps: review pressure cause. Recovery: closes disk warning/critical state.
- `host.file.changed` — Facts: critical-file path, change kind, hashes, owner,
  permissions, actor. Decision: security configuration change? Next steps:
  inspect diff and validate. Keep distinct from ordinary FIM.
- `host.memory.exhausted` — Facts: used percentage, available/total memory,
  host, process context if available. Decision: leak, spike, or attack? Next
  steps: inspect OOM/processes. Recovery: `host.memory.recovered`.
- `host.memory.recovered` — Facts: current usage/available memory, host, prior
  duration if available. Next steps: review pressure timeline.
- `host.oom_kill` — Facts: instance, kernel message, process if present, time,
  memory context. Decision: expected kill or service failure? Next steps:
  identify process and verify restart. Producer currently lacks normalized
  killed-process data.
- `host.collector.stalled` — Facts: collector, host, last successful report,
  error. Decision: one blind spot or agent-wide failure? Next steps: repair and
  assess affected detections. Recovery: `host.collector.recovered`.
- `host.collector.recovered` — Facts: collector, host, time, blind duration if
  available. Next steps: review missing telemetry. Recovery: pairs with stalled.
- `host.first_seen` — Facts: instance/hostname/account/region/tags, first report,
  agent version. Decision: expected enrollment? Next steps: verify ownership.
- `host.kernel.module.added` — Facts: module name, host, actor/source, time.
  Decision: approved driver or rootkit primitive? Next steps: verify package,
  signer, and load source. `host.kernel.module.removed` is absent from catalog.
- `host.kernel.module.removed` — Facts: module, host, time, prior owner.
  Decision: maintenance or loss of control? Next steps: verify host/package.
- `host.package_db.corrupted` — Facts: lock files/count, host, collector error.
  Decision: transient lock or corruption? Next steps: repair safely. Recovery:
  `host.package_db.recovered`.
- `host.package_db.recovered` — Facts: host, recovery time, prior lock/error if
  retained. Next steps: rerun inventory and review blind interval.
- `host.packages.changed` — Facts: added/removed names/counts, host, actor,
  deployment window. Decision: approved patch or malicious tool? Next steps:
  compare change ticket and inspect high-risk packages.
- `host.process.first_seen` — Facts: process command/comm, host, time, parent
  or executable path if available. Decision: expected workload or suspicious
  process? Next steps: inspect binary, parent, user, network. Producer currently
  exposes only `comm`.
- `host.sudoers.changed` — Facts: changed paths and state, actor, host. Decision:
  privilege expansion or administration? Next steps: inspect exact diff.
- `host.suid.added` — Facts: path, host, package/owner if available, time.
  Decision: approved privileged binary or escalation primitive? Next steps:
  verify provenance and quarantine if unexpected. `host.suid.removed` is absent.

<!-- APPEND-EVENT-INVENTORY -->
