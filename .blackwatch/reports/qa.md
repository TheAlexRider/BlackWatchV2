# BlackWatch QA Report — event-level notification contracts

Cycle focus: every notification event gets a unique, evidence-backed contract while the outer notification body remains consistent.

Date: 2026-08-25

## Verdict

The current BW-011/BW-012/BW-013 implementation is a useful rendering foundation, but it is not yet event-complete. The catalog contains 158 event kinds across 17 modules. Only the VPN authentication pilot has a genuinely event-specific contract and realistic sample. ECS has event-specific prose, but its preview data is still synthetic and not tested end-to-end. EC2, RDS, and VPN are labelled `rolled_out` even though their non-pilot events inherit module-wide guidance. IAM and S3 remain explicitly generic. The remaining modules have generic defaults, generic preview samples, or both.

The next implementation phase must be one module at a time and must gate rollout on four separate checks:

1. The event key must be emitted by a real producer or be explicitly classified as a planned/future event.
2. The notification contract must identify the facts required for that exact event type.
3. Every fact in the contract must be sourced from normalized envelope fields or named `extra` fields that the producer actually emits.
4. The preview fixture, missing-field behavior, recovery pairing, and channel rendering must be tested for that exact event type.

## Findings

### QA-01 — rollout status overstates completion

Severity: high

Evidence:

- `blackwatch/notify/profiles.py:104-155` gives every event the same generic `facts`, `next_steps`, and optional explanatory fields.
- `blackwatch/notify/profiles.py:190-338` defines module-level rollout prose.
- `blackwatch/notify/profiles.py:341-375` copies the same `why_it_matters`, `next_steps`, monitoring, impact, and recovery text to every event in a rolled-out module.
- `blackwatch/notify/profiles.py:378-697` contains 158 event kinds, but only VPN auth failure/success have custom event-level facts and samples.

Observed result: `ec2.host` (39 events), `aws.rds` (22 events), `vpn.openvpn` (13 events), and `ecs.probe` (7 events) are shown as rolled out, while the contract content for most events is only module-specific. A “database snapshot changed” notification and a “database authentication failed” notification must not ask for or explain the same facts and response.

Reproduction:

1. Import `NOTIFICATION_CATALOG`.
2. Compare `facts`, `next_steps`, `why_it_matters`, `monitoring_method`, `impact`, and `recovery` for all events within each module.
3. The six fields are identical for all events in EC2, RDS, VPN’s non-auth events, and the module-level fallback portion of ECS.

Expected: `content_status: rolled_out` means the individual event kind has an explicit contract, not merely that its module has a paragraph of guidance.

Proposed test: assert that every rolled-out event has a unique `contract_id`, event-specific required fields, an explicit fixture provenance, and a contract body that does not equal another event’s body unless the event kinds are intentionally declared aliases.

### QA-02 — representative previews can invent facts or show the wrong shape

Severity: high

Evidence:

- `blackwatch/notify/profiles.py:104-155` supplies `sample-user`, `192.0.2.10`, `sample-target`, and `sample monitored signal` to every generic event.
- `blackwatch/notify/profiles.py:341-365` adds a generic target and message to rolled-out module events, but does not derive the sample from the producer fixture.
- `blackwatch/notify/profiles.py:816-850` correctly centralizes preview event construction, but the catalog sample remains generic for most event kinds.

Observed risks:

- Certificate events need `host`, `port`, `subject`, `issuer`, `not_after`, `days_remaining`, `sans`, and optionally `error`; a sample user/source IP is misleading.
- AWS posture events need `resource_id`, `resource_type`, `finding_type`, account/region, severity, and structured evidence; a sample SSH-like actor is misleading.
- S3 inventory events need bucket posture values such as public state, encryption, versioning, logging, and public reasons.
- UEBA events need the triggering principal, dimension, baseline value, trigger action, and first-seen context.
- API Gateway events need API name, route, method, status, latency, source IP, user agent, reason, and request ID.

Expected: a preview is representative of the exact producer shape. Synthetic values must be visibly labelled as fixtures and must never be copied into delivery output when a real field is absent.

Proposed test: for every event kind, render a complete fixture and a missing-field fixture; assert that the complete preview contains only producer-backed facts and the missing-field output omits the absent fact without using sample placeholders.

### QA-03 — catalog event identity is not fully aligned with runtime producers

Severity: critical

Evidence:

- `blackwatch/notify/profiles.py:501` catalogs `posture.finding.open`, but `blackwatch/posture/projection.py:29-109` emits `aws.posture.finding.new` and `aws.posture.finding.resolved`; no producer or rule emits `posture.finding.open`.
- `blackwatch/notify/profiles.py:690-691` catalogs `ueba.anomaly`, but `blackwatch/ueba/check.py:12,80-110` emits dynamic actions such as `<category>.anomaly.first_seen_source_ip`, `<category>.anomaly.first_seen_action`, and `<category>.anomaly.first_seen_user_agent_family`.
- `blackwatch/modules/aws_s3_access.py:50-224` emits S3 object events from module `aws.s3.access`, while the catalog places them under `aws.s3`.
- `blackwatch/modules/aws_cloudtrail.py:860-1097` emits the IAM, S3 management, network, compute, storage, EFS, Backup, Secrets, RDS-management, and KMS actions with runtime source module `aws.cloudtrail`, while the catalog groups them under specialized product modules.
- `blackwatch/notify/catalog.py:100-119` has only a narrow IAM module alias map. Specialized module ownership is therefore not represented consistently in coverage.

Impact: a profile can look configured in the UI while not matching the runtime action/source combination the operator expects. Coverage can also attribute an event to the wrong producer, which makes its field contract and runbook guidance unreliable.

Expected: the canonical catalog must distinguish `event_kind`, producer/source ownership, and UI module. Alias/grouping must be explicit. Dynamic event families such as UEBA must be represented as families with a safe matching strategy, not as one literal action that never fires.

Proposed test: extract all literal and dynamic emitted actions from adapters/projections/rules and compare them with the notification catalog. Fail on orphan catalog keys, unprofiled emitted actions, and ambiguous producer ownership.

### QA-04 — available fields are still universal rather than event-specific

Severity: high

Evidence: `blackwatch/notify/profiles.py:31-68` defines common and service field lists, and `blackwatch/notify/profiles.py:135` assigns the same content field list to every event.

Examples of missing exact fields:

- EC2 host FIM: path, change type, before/after hashes, permissions, owners, and whodata actor (`blackwatch/modules/ec2_host.py:284-340`).
- EC2 host health: current metric, threshold/baseline, uptime, collector errors, and age (`blackwatch/modules/ec2_host.py:100-160` plus host projections).
- RDS: database instance, database user, source/real client IP, reason, backend PID, session duration/idle time, threshold, query/function/DDL details, and proxy state (`blackwatch/modules/aws_rds.py:300-551`, `blackwatch/rds/projection.py:36-348`).
- IAM/CloudTrail: event name, actor type/root/via-role, account/region, resource, request scope, MFA use, error code, wildcard-policy or weakened-control signal (`blackwatch/modules/aws_cloudtrail.py:900-1097`).
- S3: bucket/object, operation, HTTP status, bytes, auth type, user agent, public reasons, encryption, versioning, logging, and exposure transition (`blackwatch/modules/aws_s3_access.py:150-224`, `blackwatch/modules/aws_s3.py:63-130`, `blackwatch/s3/projection.py:41-182`).
- API Gateway: API, route, method, status, integration status, latency, response length, request ID, reason, and scanner signature (`blackwatch/modules/aws_api_gw.py:150-307`).
- Certificates: endpoint, port, subject, issuer, expiry timestamp, days remaining, SANs, and probe error (`blackwatch/modules/cert_expiry.py:20-95`).
- UEBA: principal type/id, triggering action, anomaly dimension, baseline value, and event source context (`blackwatch/ueba/check.py:80-110`).

Expected: the UI editor should show only fields meaningful for the selected event kind, with plain-language descriptions and an indication of whether each field is envelope, producer `extra`, derived state, or unavailable.

Producer/schema assessment: most required values already exist in the normalized event envelope or `extra`; an additive `extra` contract is sufficient for the first pass. No destructive or breaking schema change is justified. Some CloudTrail events need additive structured summaries in `extra` because raw request parameters are too varied to safely render directly.

### QA-05 — recovery semantics are asserted as prose, not verified as event pairs

Severity: high

Evidence:

- `_MODULE_ROLLOUT` supplies generic recovery sentences (`blackwatch/notify/profiles.py:190-338`).
- `blackwatch/services/projection.py:216-430`, `blackwatch/hosts/staleness.py`, `blackwatch/vpn/projection.py:42-125`, `blackwatch/s3/projection.py:79-160`, and `blackwatch/posture/projection.py:60-109` contain distinct transition/recovery behavior.

Observed result: “matching recovery event” is used even for events with no automatic recovery event, such as a one-time IAM policy attachment, a malware finding, a first-seen bucket, or a backup deletion. Conversely, actual recovery pairs such as `service.down` → `service.up`, `probe.agent.stale` → `probe.agent.recovered`, posture new → resolved, and VPN service down → up need explicit correlation wording and stable identifiers.

Expected: each event contract declares one of `paired_recovery`, `state_update`, `no_automatic_recovery`, or `manual_resolution`, with the matching action and correlation key when applicable.

Proposed test: assert that recovery text is absent for one-shot events unless a manual-resolution instruction is present, and assert the exact recovery action/correlation key for stateful event pairs.

### QA-06 — notification rendering tests cover metadata, not the full delivery contract

Severity: high

Evidence: `tests/test_notification_profiles.py` and `tests/test_notification_rendering.py` validate catalog presence, template compilation, and the VPN pilot. They do not exercise all producer fixtures, all event families, actual missing-field omission, or email/chat output for each completed module.

The bundled Python runtime can run the 21 focused profile/catalog/rendering tests, but the channel integration path is blocked locally because `jinja2` and `psycopg` are unavailable to the bundled runtime. This is a test-environment blocker, not a pass.

Expected: each module task adds golden tests for every event type in the module, at least one plain-text/email path and one chat path, plus malformed/partial producer fixtures.

## Module-by-module field and contract audit

The following is the required contract planning inventory. The outer body should remain consistent: concise title, what happened, exact facts, next action, optional why/impact, monitoring source, and recovery/resolution semantics. The inner facts and action order must be unique to the event kind.

### 1. VPN — `BW-014` follow-up after the auth pilot

Event kinds: `vpn.service.down`, `vpn.auth.failure`, `vpn.bruteforce`, `vpn.session.concurrent`, `vpn.cert.expired`, `vpn.cert.probe.failed`, `vpn.cert.expiring.critical`, `vpn.cert.expiring.high`, `vpn.cert.expiring.warning`, `vpn.auth.success`, `vpn.bruteforce.user`, `vpn.service.up`, `vpn.session.start`.

Required facts by family:

- Service down/up: server, current/previous active state, transition time, last healthy time, outage duration, and recovery state.
- Auth failure/success: user, source IP, server, event time, authentication method/message; missing user/IP must be omitted.
- Brute force: aggregation dimension (IP or user), count, time window, targeted identity, source IP set, and threshold.
- Concurrent sessions: identity, server, distinct source IPs, active session count, and threshold.
- Certificate events: certificate kind/common name, endpoint/server, issuer/serial if available, expiry, days remaining, revoked status, and probe error.
- Session start: user/common name, source IP, server, and observed time.

Producer sources: `blackwatch/modules/vpn_openvpn.py:232-390` and `blackwatch/vpn/projection.py:42-125`. Additive producer fields may be needed for count/window and certificate identity; no envelope change is required.

### 2. EC2 hosts — `BW-015`

Event kinds: `host.agent.stale`, `host.agent.recovered`, `host.auth.ssh.failure`, `host.auth.ssh.password.success`, `host.auth.ssh.success`, `host.bruteforce`, `host.bruteforce.user`, `host.sudo.failure`, `host.authorized_key.added`, `host.user.added`, `host.port.opened`, `host.fim.modified`, `host.fim.deleted`, `host.fim.created`, `host.fim.perm_changed`, `host.fim.owner_changed`, `host.fim.coverage`, `host.service.added`, `host.cpu.anomaly`, `host.cpu.normal`, `host.cron.changed`, `host.disk.critical`, `host.disk.warn`, `host.disk.recovered`, `host.file.changed`, `host.memory.exhausted`, `host.memory.recovered`, `host.oom_kill`, `host.collector.stalled`, `host.collector.recovered`, `host.first_seen`, `host.kernel.module.added`, `host.kernel.module.removed`, `host.package_db.corrupted`, `host.package_db.recovered`, `host.packages.changed`, `host.process.first_seen`, `host.sudoers.changed`, `host.suid.added`.

Required facts by family:

- Agent/coverage: instance, hostname, account/region, last report, silence age, agent version, collector name, and coverage impact.
- SSH/sudo: host, user, source IP, method, reason, command, and event time.
- Brute force: source IP or targeted user, failure count/window, threshold, and host.
- FIM/configuration: path or object name, change type, before/after hashes/permissions/owners, actor/whodata, and detection source.
- Host health: metric, observed value, baseline/threshold, duration, process/kernel message, and recovery counterpart.

Producer source: `blackwatch/modules/ec2_host.py:86-360`, with staleness and host projections. The producer already carries most values in `extra`, but the contract must expose the exact nested keys rather than universal placeholders.

### 3. RDS — `BW-016`

Event kinds: `rds.auth.failure`, `rds.auth.burst`, `rds.instance.create`, `rds.instance.delete`, `rds.instance.modify`, `rds.snapshot.modify`, `rds.session.concurrent`, `rds.session.long_idle`, `rds.query.role`, `rds.query.function`, `rds.error`, `rds.proxy.source.new`, `rds.proxy.client.connect`, `rds.proxy.client.disconnect`, `rds.proxy.backend_hba_reject`, `rds.proxy.misconfig`, `rds.session.start`, `rds.session.end`, `rds.session.new_source`, `rds.query.ddl`, `rds.parameter_group.modify`, `rds.user.unknown`.

Required facts: database instance, database user, source/real client IP, server/proxy, reason/error, backend PID, session ID, session duration or idle age, concurrent count and threshold, query/function/DDL class, proxy state, resource change flags, actor, account/region, and the specific security/configuration setting. Auth burst and new-source events require count/window or allowlist context. Session recovery/closure should use session ID and exact start/end semantics.

Producer sources: `blackwatch/modules/aws_rds.py:300-551`, `blackwatch/rds/projection.py:36-348`, and `blackwatch/rds/staleness.py`. No generic “database changed” template is acceptable across these event families.

### 4. ECS services and probes — `BW-017`

Event kinds: `service.down`, `service.degraded`, `service.unknown`, `service.up`, `probe.agent.stale`, `probe.agent.recovered`, `probe.agent.first_seen`.

Required facts: service/target ID and name, VPC/environment, monitoring tier, raw status, health-check error, latency, consecutive failure/success count, downtime/unknown duration, last report, agent version, and environment tags. Service recovery must state what recovered and how long it was impaired; probe recovery must distinguish monitoring coverage from service health.

Producer sources: `blackwatch/modules/ecs_probe.py:49-120`, `blackwatch/services/projection.py:216-430`, and `blackwatch/services/staleness.py:22-129`. The event prose is more specific than other modules, but the preview fixture and channel golden tests are not representative enough to call the module complete.

### 5. IAM and CloudTrail — `BW-018`

Event kinds: `iam.access_key.create`, `iam.mfa.deactivate`, `iam.role.update_trust`, `iam.user.create`, `iam.user.delete`, `iam.role.create`, `iam.role.delete`, `iam.login_profile.create`, `iam.policy.attach`, `iam.policy.put_inline`, `kms.key.disable`, `kms.key.delete_scheduled`, `kms.policy.put`, `kms.grant.create`, `kms.rotation.disable`, `cloudtrail.trail.delete`, `cloudtrail.logging.stop`, `cloudtrail.trail.update`, `auth.console.login`, `auth.federated.login`.

Required facts: action headline, actor principal/type/root/via-role, source IP/user agent, AWS account/region, affected identity/key/role/policy/trail, exact change scope, MFA use or login kind, error status, wildcard-policy or weakened-control signal, and approved change window. Recovery is normally manual or a follow-up change, not an automatic recovery alert.

Producer source: `blackwatch/modules/aws_cloudtrail.py:860-1097`. Additive `extra` summaries are likely required because request parameters differ by CloudTrail API. The catalog must explicitly model `aws.cloudtrail` as the producer while retaining IAM/CloudTrail as the operator-facing module.

### 6. S3 — `BW-019`

Event kinds: `s3.object.access.anonymous`, `s3.object.access`, `s3.bucket.create`, `s3.bucket.delete`, `s3.bucket.acl.put`, `s3.bucket.policy.put`, `s3.bucket.bpa.put`, `s3.bucket.bpa.delete`, `s3.bucket.public`, `s3.bucket.public_removed`, `s3.bucket.encryption.delete`, `s3.bucket.versioning.put`, `s3.bucket.versioning_off`, `s3.bucket.logging.put`, `s3.bucket.unencrypted`, `s3.bucket.first_seen`, `s3.bucket.disappeared`.

Required facts: bucket/object, operation, requester/actor, source IP, user agent, auth type, HTTP status/bytes, account/region, public exposure reason, prior/current public state, encryption state, versioning/MFA-delete state, access-block state, logging target, scan timestamp, and whether disappearance may be a partial scan. Anonymous access must clearly say anonymous and must not be rendered as a named user.

Producer sources: `blackwatch/modules/aws_s3_access.py:133-224`, `blackwatch/modules/aws_s3.py:63-130`, and `blackwatch/s3/projection.py:41-182`. The object-access producer is `aws.s3.access`, not `aws.s3`; ownership must be explicit.

### 7. API Gateway — `BW-020`

Event kinds: `api.auth.failure`, `api.auth.burst`, `api.error`, `api.error.burst`, `api.scanner_ua`, `api.source.new`.

Required facts: API name, route, HTTP method, status, integration status, latency, response length, request ID, source IP, user agent, error/reason, scanner signature, source-IP count/window, and whether the event is a single request or an aggregate burst. The next step differs between authentication failure, server error, scanner, and new source.

Producer source: `blackwatch/modules/aws_api_gw.py:150-307`, with burst/new-source projections. The current generic fields do not expose the HTTP facts needed for action.

### 8. AWS Posture — `BW-021`

Event kinds: `network.sg.instance_attach`, `posture.finding.open`, `aws.posture.finding.new`, `aws.posture.finding.resolved`.

Required facts: resource ID/type, finding type, severity, account/region, evidence details, control/check name, actor/change source for SG attachment, first-seen/resolved timestamps, and resolution reason. `posture.finding.open` is not emitted and must be removed, aliased, or explicitly marked future before any profile is enabled. `network.sg.instance_attach` is CloudTrail-derived and should be owned by the network/compute presentation while preserving its actual source.

Producer sources: `blackwatch/modules/aws_posture.py:87-159`, `blackwatch/posture/projection.py:29-109`, and CloudTrail normalization.

### 9. TLS Certificates — `BW-022`

Event kinds: `cert.expired`, `cert.expiring.critical`, `cert.expiring.high`, `cert.expiring.warning`, `cert.probe.failed`.

Required facts: endpoint/name, host/port, subject, issuer, expiry time, days remaining, SANs, certificate kind, probe timestamp, and exact probe error. Expiry contracts need urgency-specific action: renew now, schedule renewal, or monitor. Probe failure must distinguish “certificate expired” from “certificate could not be checked.” Recovery is a successful probe or renewed certificate, not generic recovery prose.

Producer source: `blackwatch/modules/cert_expiry.py:20-95`.

### 10. UEBA — `BW-023`

Event kind currently cataloged: `ueba.anomaly`.

Runtime actions are dynamic: `<category>.anomaly.first_seen_source_ip`, `<category>.anomaly.first_seen_source_country`, `<category>.anomaly.first_seen_source_asn`, `<category>.anomaly.first_seen_hour_of_day`, `<category>.anomaly.first_seen_action`, and `<category>.anomaly.first_seen_user_agent_family` (`blackwatch/ueba/check.py:12,80-110`).

Required facts: principal/type, trigger event/action, anomaly dimension, newly observed baseline value, source IP/geo/ASN/UA or hour, target, account/region, and the baseline warm-up state. The contract must explain that “first seen” is not proof of compromise and direct the operator to verify the principal and recent change context. A literal `ueba.anomaly` profile cannot match the current runtime family.

### 11. Security Findings — `BW-024`

Event kind: `finding.malware.detected`.

Required facts: finding source/vendor, signature or detection name, affected object/resource, hash, bucket/path, account/tenant, scan time, engine/version, confidence, and containment/owner status. The generic adapter preserves arbitrary fields in `extra`/`raw` (`blackwatch/modules/generic.py:41-80`); the notification contract must define the minimum safe field set without claiming that every finding has malware-specific fields. Recovery is manual resolution unless the producer supplies a resolved action.

### 12. AWS Backup — `BW-025`

Event kinds: `backup.recovery_point.delete`, `backup.vault.delete`, `backup.vault.policy.delete`, `backup.vault.policy.put`, `backup.copy_job.start`.

Required facts: vault/recovery-point ID, backup plan/resource, actor, account/region, retention/immutability, policy change summary, copy destination account/region, job ID, and whether the action is destructive or cross-account. Next steps must verify the last known-good recovery point and retention policy. There is no automatic recovery for deletion; restoration is an operator action.

Producer source: CloudTrail normalization and signals in `blackwatch/modules/aws_cloudtrail.py:790-800,1013-1018`.

### 13. AWS EFS — `BW-026`

Event kinds: `efs.filesystem.policy.delete`, `efs.filesystem.policy.put`, `efs.mount_target.create`, `efs.mount_target.delete`, `efs.mount_target.sg.modify`, `efs.filesystem.delete`.

Required facts: file-system ID/name, mount target/AZ, security groups, actor, account/region, policy summary, wildcard/public signal, and dependent workload impact. Policy changes and mount-target deletion require different response steps. Recovery is a deliberate policy/mount restoration, not a generic event.

Producer source: CloudTrail normalization and EFS-specific signal extraction in `blackwatch/modules/aws_cloudtrail.py:1007-1011`.

### 14. AWS Network — `BW-027`

Event kinds: `network.igw.attach`, `network.peering.accept`, `network.tgw_peering.accept`, `network.sg.ingress.add`.

Required facts: VPC/subnet/gateway/peering IDs, source/destination accounts, route or ingress protocol/port/CIDR, actor, region, and whether the rule is public or risky. The next step is to validate intended connectivity/exposure, not simply inspect a generic resource owner. Recovery is manual reversal or an explicit follow-up network change.

Producer source: CloudTrail normalization, including SG signal extraction at `blackwatch/modules/aws_cloudtrail.py:987-989`.

### 15. AWS Secrets — `BW-028`

Event kinds: `secrets.secret.create`, `secrets.secret.update`, `secrets.secret.restore`, `secrets.secret.delete`.

Required facts: secret name/ARN, actor, account/region, version/stage, rotation metadata, consuming service if known, deletion/restore window, and change type. Never include secret values. Update, delete, and restore require different action order; recovery is restore/consumer recovery only when a matching event exists.

Producer source: CloudTrail action normalization and `secrets.*` signals in `blackwatch/modules/aws_cloudtrail.py:800-804`.

### 16. AWS Compute — `BW-029`

Event kinds: `compute.imds.modify`, `compute.ami.modify`, `compute.instance.modify`.

Required facts: instance/image ID, actor, account/region, metadata v1/v2 setting, image visibility/share scope, security groups/instance configuration, and special flags such as public or cross-account exposure. The next step differs between credential-theft risk, image exposure, and operational instance change.

Producer source: CloudTrail normalization and compute signal extraction in `blackwatch/modules/aws_cloudtrail.py:989-1001,1051-1060`.

### 17. AWS Storage — `BW-030`

Event kind: `storage.snapshot.modify`.

Required facts: snapshot/volume ID, actor, account/region, public/cross-account share scope, encryption, retention, and before/current state. Public exposure and ordinary configuration changes need distinct title, impact, and response steps. Recovery is manual share removal or restore verification.

Producer source: CloudTrail normalization and storage signal extraction in `blackwatch/modules/aws_cloudtrail.py:997-1000`.

## Proposed one-module-at-a-time rollout

The proposed tasks are intentionally sequential. Each task starts as `status: proposed` with `implementation_allowed: false`.

1. BW-014 — VPN remaining event types.
2. BW-015 — EC2 host event types.
3. BW-016 — RDS event types.
4. BW-017 — ECS/probe event types.
5. BW-018 — IAM and CloudTrail event types.
6. BW-019 — S3 inventory and object-access event types.
7. BW-020 — API Gateway event types.
8. BW-021 — AWS Posture and ownership reconciliation.
9. BW-022 — TLS certificate event types.
10. BW-023 — UEBA dynamic anomaly event family.
11. BW-024 — Security Findings producer contract.
12. BW-025 — AWS Backup event types.
13. BW-026 — AWS EFS event types.
14. BW-027 — AWS Network event types.
15. BW-028 — AWS Secrets event types.
16. BW-029 — AWS Compute event types.
17. BW-030 — AWS Storage event type.

Every task must preserve the same outer body structure, retain explicit advanced templates, avoid fabricated facts, add only additive producer `extra` fields when required, and include golden rendering plus missing-field and recovery-semantic tests before that module is labelled rolled out.

## Verification performed

Passed:

- `C:\Users\TheAl\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_notification_profiles tests.test_notification_catalog tests.test_notification_rendering -v` — 21 tests passed.
- `C:\Users\TheAl\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe node_modules/next/dist/bin/next build` from `blackwatch-ui` — production build passed.
- Bundled Node TypeScript check after the build — passed with no output.
- `git diff --check` — passed; only line-ending warnings were reported for existing working-tree files.

Blocked and not treated as passing:

- `pytest -q` — `pytest` is not installed/on PATH.
- `npm run typecheck` — `npm` is not installed/on PATH. Direct bundled `tsc` was used instead.
- `npm run build` — `npm` is not installed/on PATH. Direct bundled Next.js build was used instead.
- Channel integration tests — bundled Python lacks the runtime dependencies required by the channel/profile service import path (`jinja2`/`psycopg`).
- Graphify refresh — configured interpreter `C:\Users\TheAl\AppData\Local\Programs\Python\Python312\python.exe` is blocked by Windows with “Access is denied”; existing `graphify-out` was retained and not modified.

No application source, tests, rules, deployment files, documentation, database, or Graphify output were modified by this QA role. Only this QA report and the proposed task YAML files were written.
