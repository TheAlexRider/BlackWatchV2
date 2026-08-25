# BW-014 OpenVPN notification-content review

Status: reviewed — content design only  
Scope: `vpn.openvpn` producer, projection, correlation, rules, and current notification catalog  
Reviewed: 2026-08-25

This document keeps the existing outer notification shape, but defines the
inner content independently for every OpenVPN signal. The intended rendered
order is:

1. Headline
2. What happened
3. Facts
4. Decision
5. Next steps
6. Evidence
7. Recovery / manual resolution

The current guided profile contract has `why_it_matters` but no `decision`
field. `decision` is therefore an additive content field required by this
review. It should not change saved profile IDs, routing, channels, throttling,
silence settings, advanced templates, audit history, or stored event data.

## Executive findings

- `vpn.auth.failure` is the only OpenVPN event with a genuinely event-specific
  notification contract today. Its user, source IP, server, and time are the
  right facts; the message should stay short and decision-led.
- `vpn.auth.success` has useful identity facts but should be informational and
  should not create an incident-style “why this matters” paragraph.
- `vpn.service.down`, `vpn.service.up`, `vpn.session.start`, and
  `vpn.session.concurrent` are derived alerts, but the catalog currently gives
  them shared module-level prose rather than their own operational message.
- `vpn.session.end` is emitted by `blackwatch/vpn/projection.py` but is absent
  from `NOTIFICATION_CATALOG`, rules, and Notification Studio coverage.
- Session start/end events currently contain only `server`, `derived`, and
  `common_name` in `extra`, plus principal/source IP in the envelope. They do
  not contain connection start time, end time, duration, virtual address, or
  the full prior client record. A notification must omit those values until
  the producer adds them.
- `vpn.service.health`, `vpn.status.snapshot`, and `vpn.cert.snapshot` are
  real producer actions, but the ingest pipeline marks them projection-only.
  They should be explicitly classified as internal/non-notifying in the
  catalog rather than silently treated as covered alerts.
- `vpn.cert.drift` is documented as a future projection event but is not
  emitted by the reviewed producer/projection code. It must remain future or
  be implemented in a later additive task; it must not receive a misleading
  “rolled out” profile now.
- Brute-force events are emitted by correlation, not the OpenVPN adapter. Their
  decisive facts are the counting dimension, count, threshold, and time window.

## Field inventory and omission rules

### Envelope fields actually available

All notifying events can draw from the normalized envelope when present:

- `event_time`
- `source.module`, `source.account`, `source.region`, `source.transport`
- `action`, `outcome`, `severity`
- `actor.principal`, `actor.source_ip`
- `target.id`, `target.type`, `target.name`
- `observables`
- `event_id`, `rule_matches`, and `tags` for links/internal context, not for
  user-facing prose unless explicitly useful

### OpenVPN `extra` fields actually emitted

| Event family | Fields emitted | Omit when absent |
|---|---|---|
| Health heartbeat | `server`, `state`, optional `agent_version`, `uptime_seconds`, `instance_id`, `hostname` | Every optional heartbeat field; never print `unknown` placeholders |
| Status snapshot | `server`, `client_count`, `clients[]`; each client may contain `common_name`, `real_address`, `real_ip`, `virtual_address`, `virtual_ipv6`, `bytes_received`, `bytes_sent`, `connected_since`, `connected_since_t`, `username`, `client_id`, `peer_id`, `data_channel_cipher` | Per-client fields not present in the status version; omit the entire client table from notifications unless a snapshot is intentionally made visible |
| Auth success/failure | `server`, `log_line`, `message` | `source_ip`, principal, and raw log line if not present; do not invent account or geography |
| Certificate alert | `server`, `kind`, `source`, `subject`, `issuer`, `not_after`, `days_remaining`, `path`, `error`, `revoked` | Any missing certificate attribute; do not say “renewal failed” unless `error` says so |
| Session start/end | `server`, `derived`, `common_name`; envelope principal/source IP; observables for IP/user | Duration, connected-since, virtual IP, bytes, and client ID until added by producer |
| Concurrent session | `server`, `derived`, `identity`, `source_ips`; envelope principal and target | Count beyond the listed IPs; do not call it account takeover without corroborating evidence |
| Brute-force correlation | `count_in_window`, `window_seconds`, `threshold`, `trigger_event_id`, `source_ip`, `principal`, `dimension` | User or IP if the dimension does not contain it; do not expose the trigger event ID as the main fact |

### Required rendering behavior

- Render only non-empty fields. A missing source IP should remove the source-IP
  line, not produce `unknown source`, `—`, or a generic paragraph.
- Do not render raw `clients[]` as JSON in email or chat. The snapshot is an
  internal projection input; session-derived alerts should carry the useful
  client facts instead.
- Do not use module-wide fallback text for an event whose contract is marked
  reviewed. Every reviewed event must have its own `facts`, `decision`,
  `next_steps`, `evidence`, and `recovery` semantics.
- Keep severity in the headline only when it helps triage. Do not repeat the
  same severity in three sections.
- `Recovery` must state either the exact matching recovery event or that no
  automatic recovery exists and what manual resolution means.

## Event-by-event message matrix

The “fixture” column refers to the representative payloads defined below.
Partial fixtures are deliberate: they verify that absent values disappear
cleanly instead of becoming fabricated prose.

### Adapter and projection signals

| Event | Exact decision-critical fields | Headline | What happened | Facts | Decision | Ordered next steps | Evidence | Recovery / manual resolution | Fixture |
|---|---|---|---|---|---|---|---|---|---|
| `vpn.service.down` | `event_time`; target server; `extra.prev_active=true`; `extra.active=false`; optional `state`, `hostname`, `instance_id` from preceding health signal if propagated | `VPN service down · <server>` | The monitored OpenVPN service changed from up to down. | Server; detected time; previous state; current state; optional host/instance. | `Contain or restore the VPN service if this is not an approved maintenance window.` | 1. Confirm maintenance/change window. 2. Check OpenVPN process, host health, listener, and recent config/certificate changes. 3. Restore service or escalate using the VPN outage runbook. | State transition from `vpn.service.health` plus the heartbeat/server fields that caused it. | Pair with `vpn.service.up`. No recovery should be claimed until the up transition is observed. | F1 complete; F1-partial |
| `vpn.service.up` | `event_time`; target server; `extra.prev_active` (`false` for recovery or `null` for first seen); `extra.active=true` | `VPN service recovered · <server>` or `VPN service first seen · <server>` | The VPN service is active again, or this is its first recorded active heartbeat. | Server; detected time; previous state; current state; first-seen vs recovered. | `Confirm stability before closing the earlier outage; first-seen is an onboarding decision, not an incident recovery.` | 1. Determine whether this is first-seen or recovery. 2. Check consecutive healthy heartbeats and active sessions. 3. Review the outage timeline before closing. | Projection transition fields `prev_active` and `active`. | Pair with `vpn.service.down` for recovery. First-ever `up` has no prior incident to recover. | F1 complete; F1-first-seen |
| `vpn.session.start` | `event_time`; target server; principal from `username` or `common_name`; source IP from `real_ip`; `extra.common_name`; observables | `VPN session started · <user> · <server>` | A client appeared in the latest status snapshot that was absent from the previous snapshot. | User/common name; source IP; server; detected time. Do not imply authentication method. | `Decide whether this connection is expected for this user and source.` | 1. Confirm the user and source IP are expected. 2. Check the corresponding auth event if available. 3. Investigate concurrent or unusual access if the connection is not approved. | State diff between two status snapshots; `raw.derived_from=status.snapshot`. | No separate recovery event; the matching `vpn.session.end` is a session closure, not proof the connection was authorized. | F2 complete; F2-partial |
| `vpn.session.end` | Same currently emitted fields as start: `event_time`; target server; principal; source IP; `extra.common_name`; observables; `derived=true` | `VPN session ended · <user> · <server>` | A client present in the previous status snapshot is no longer present. | User/common name; last observed source IP; server; detected time. Label source IP as “last observed,” not current. | `Decide whether the session ended normally or disappeared unexpectedly.` | 1. Compare the end time with the user’s expected work window. 2. Check OpenVPN/auth logs for disconnect or failure evidence. 3. Close the session trail only when the end is expected or explained. | This is the end counterpart to `vpn.session.start`; it is not an automatic remediation event. Manual resolution is an operator explanation/closure. | F2-end complete; F2-end-partial |
| `vpn.session.concurrent` | `event_time`; target server; `actor.principal`; `extra.identity`; `extra.source_ips[]`; observables; `derived=true` | `Concurrent VPN sessions · <user>` | The same VPN identity was observed from more than one source IP at the same time. | Identity; all observed source IPs; VPN server; detection time. | `Treat as possible credential sharing or compromise until the identity owner confirms both sessions.` | 1. Confirm whether the user intentionally has multiple connections. 2. Compare IPs, geography/device context if available, and auth history. 3. Revoke or rotate credentials/certificates if unauthorized. 4. Record the owner’s decision. | Projection evidence: more than one distinct `real_ip` for one identity in one snapshot. | No automatic recovery. Manual resolution is owner confirmation, session termination, and credential action when required. | F3 complete; F3-partial |
| `vpn.status.snapshot` | `event_time`; target server; `client_count`; `clients[]`; observables | No user notification | Internal snapshot used to maintain the live VPN read model. | Not user-facing; do not expose the whole client list through the alert renderer. | No notification decision. | No notification steps. | Snapshot payload and status parser output remain available for derived session/concurrent events. | Projection-only. No profile should route it. | F4 complete |
| `vpn.service.health` | `event_time`; target server; `outcome`; `extra.state`; optional agent/host heartbeat fields | No user notification | Internal heartbeat used to detect service transitions. | Not user-facing; only the transition is alert-worthy. | No notification decision. | No notification steps. | Heartbeat payload. | Projection-only; `vpn.service.down`/`up` carry the operator signal. | F1 complete |

### Authentication and correlation signals

| Event | Exact decision-critical fields | Headline | What happened | Facts | Decision | Ordered next steps | Evidence | Recovery / manual resolution | Fixture |
|---|---|---|---|---|---|---|---|---|---|
| `vpn.auth.failure` | `event_time`; principal; source IP; target server; `extra.message`; `extra.log_line`; outcome=failure; observables | `VPN login failed · <user or source>` | A VPN authentication attempt failed. | User; source IP; VPN server; time. | `Decide whether the failed attempt was expected; one failure alone is not proof of attack.` | 1. Confirm whether the user initiated the attempt. 2. If unexpected, investigate the source IP and recent account activity. 3. Escalate or follow the credential-response runbook if failures continue. | `extra.message` and the original `log_line`; never paste the full raw record unless requested. | No automatic recovery event. A later successful login is a separate event and must not silently close the failure. | F5 complete; F5-no-ip; F5-no-user |
| `vpn.auth.success` | `event_time`; principal; source IP; target server; outcome=success; `extra.message`/log line; observables | `VPN login succeeded · <user>` | A VPN authentication attempt succeeded. | User; source IP; VPN server; time. | `Decide whether the successful login matches the user’s expected access.` | 1. If expected, no action. 2. If unexpected, verify the user/source and review recent failures or concurrent sessions. 3. Escalate only when corroborating evidence exists. | Original journal line when available; the normalized identity/source fields are sufficient for the compact message. | No automatic recovery semantics. This event can provide context for a failure but does not resolve one. | F6 complete; F6-partial |
| `vpn.bruteforce` | `event_time`; target server; actor/source IP; optional principal; `count_in_window`; `threshold`; `window_seconds`; `dimension=source_ip`; `trigger_event_id` | `VPN brute-force activity · <source IP>` | At least the configured threshold of failed VPN logins came from one source IP within the configured window. | Source IP; count; threshold; window; server; optional targeted user. | `Treat as active suspicious authentication activity unless the source is a known approved scanner or gateway.` | 1. Verify whether the source is an approved NAT, scanner, or corporate gateway. 2. Check targeted users and success events in the same window. 3. Block/rate-limit or investigate the source according to the runbook. 4. Protect affected accounts if any login succeeded. | Correlation fields are the evidence: `count_in_window`, `threshold`, `window_seconds`, and `dimension`. The triggering event ID is an audit link, not a headline fact. | No automatic recovery. Manual resolution is containment plus documenting why the source is trusted or blocked. | F7 complete; F7-partial |
| `vpn.bruteforce.user` | `event_time`; target server; actor principal; optional source IP; `count_in_window`; `threshold`; `window_seconds`; `dimension=principal`; `trigger_event_id` | `VPN credential-stuffing activity · <user>` | At least the configured threshold of failed VPN logins targeted one username within the configured window, regardless of source IP. | Username; count; threshold; window; server; observed source IP only if present; dimension. | `Treat as possible credential stuffing unless the account is a known test target.` | 1. Confirm the account owner and whether a password reset/test explains the pattern. 2. Review all source IPs and any successful login. 3. Lock, rotate, or step-up-protect the account if unauthorized. 4. Record the resolution. | Correlation count/window/dimension plus the triggering failure. If multiple IPs are not carried, link to the event trail rather than inventing a list. | No automatic recovery. Manual resolution is account protection and owner confirmation. | F8 complete; F8-no-ip |

### Certificate signals

| Event | Exact decision-critical fields | Headline | What happened | Facts | Decision | Ordered next steps | Evidence | Recovery / manual resolution | Fixture |
|---|---|---|---|---|---|---|---|---|---|
| `vpn.cert.expiring.warning` | target cert name/id/type; `server`; `kind`; `source`; `subject`; `issuer`; `not_after`; `days_remaining`; `path`; `revoked=false`; event time | `VPN certificate expires in <days> days · <name>` | A monitored VPN certificate entered the warning window. | Certificate name/type; server; expiry timestamp; days remaining; subject/issuer when present; path when useful. | `Decide whether renewal is already scheduled and whether the remaining window is safe for the next deployment/use period.` | 1. Identify the certificate owner and renewal path. 2. Confirm the certificate used by the live VPN endpoint. 3. Renew and deploy before the threshold. 4. Verify with a healthy probe. | `days_remaining`, `not_after`, certificate identity, and probe source. | Healthy probe/renewal is the recovery condition; no matching recovery event currently exists. Until one is emitted, manual closure must record the renewed certificate and verification time. | F9 warning; F9-partial |
| `vpn.cert.expiring.high` | Same certificate fields; `days_remaining < 14` | `VPN certificate expires soon · <name>` | A monitored certificate is inside the high-risk renewal window. | Certificate identity; server; expiry; days remaining; owner/source. | `Renew or schedule immediately; confirm there is no deployment dependency that will fail first.` | 1. Check current endpoint certificate. 2. Confirm renewal owner and expiry plan. 3. Renew/deploy and validate the full chain. 4. Escalate if renewal cannot complete inside the window. | Same certificate fields; include `error` only if present. | Recovery requires a healthy probe after renewal or a future explicit certificate-recovered event. | F9 high |
| `vpn.cert.expiring.critical` | Same certificate fields; `days_remaining < 7` | `VPN certificate expires in <7 days · <name>` | A monitored certificate is critically close to expiry. | Certificate identity; exact expiry; days remaining; live source/path; issuer/subject. | `Treat as an urgent outage-prevention task.` | 1. Confirm whether the live endpoint uses this certificate. 2. Renew/deploy immediately. 3. Validate client trust and VPN handshake. 4. Escalate to the certificate owner if blocked. | Exact expiry data and probe source. Avoid claiming client impact before validation. | Manual resolution is renewal plus successful endpoint validation; current code does not emit a dedicated recovery action. | F9 critical |
| `vpn.cert.expired` | Same certificate fields; `days_remaining < 0` | `VPN certificate expired · <name>` | A monitored VPN certificate is past its expiry time. | Certificate; server; expiry; days overdue; source/path; subject/issuer. | `Assume secure connectivity may fail until the live endpoint is verified and the certificate is replaced.` | 1. Verify whether the expired certificate is live. 2. Replace/renew it immediately. 3. Validate the VPN endpoint and client trust chain. 4. Check for outage or failed handshakes during the expired period. | `not_after`, negative `days_remaining`, certificate source/path, and any probe error. | Recovery is manual renewal and successful probe/endpoint validation. Add a future `vpn.cert.recovered` event if automatic closure is required. | F10 complete; F10-live-unknown |
| `vpn.cert.probe.failed` | target cert; `server`; `kind`; `source`; `path`; `error`; optional certificate identity/expiry fields; outcome=failure | `VPN certificate check failed · <name>` | BlackWatch could not read or evaluate a VPN certificate. | Certificate name/type; server; probe source/path; error; last known expiry only if actually present. | `Decide whether this is a probe/permission failure or evidence that certificate health is unknown.` | 1. Inspect probe error and file/path permissions. 2. Confirm the expected certificate exists and is readable. 3. Run an independent endpoint check. 4. Repair the probe and verify a healthy result. | `error`, `path`, source, and any available certificate fields. Do not turn a probe failure into “certificate expired.” | Recovery is a successful subsequent probe. Until then, manual resolution must explain why certificate health is trusted. | F11 complete; F11-no-error |
| `vpn.cert.snapshot` | `server`; `certs[]`; `count`; each cert record as above | No user notification | Internal certificate inventory used to generate per-certificate alerts and update the VPN read model. | Not user-facing; do not send the entire certificate inventory. | No notification decision. | No notification steps. | Inventory is the source for the per-certificate event. | Projection-only. Per-certificate alerts carry the actionable signal. | F12 complete |
| `vpn.cert.drift` | No producer fields available in reviewed code; documentation only | Not ready for rollout | Documented as a future “live certificate differs from PKI certificate” signal, but no reviewed producer emits it. | No honest facts can be promised yet. | Do not create a profile until a producer contract exists. | Additive future work must define live path, PKI path, hashes/versions, observed time, and owner before notification design. | None currently available. | Not applicable until emitted. | No fixture; explicit gap |

## Representative fixtures

These fixtures describe the minimum data the producer should expose to golden
notification tests. They are documentation fixtures only; this review does not
modify tests or application code.

### F1 — service transition

Complete derived `vpn.service.down`:

```json
{
  "action": "vpn.service.down",
  "event_time": "2026-08-25T04:10:00Z",
  "target": {"id": "vpn-1", "type": "vpn.server", "name": "vpn-1"},
  "outcome": "success",
  "extra": {"server": "vpn-1", "derived": true, "prev_active": true, "active": false}
}
```

Partial `vpn.service.down`: target `vpn-1`, `prev_active=true`, `active=false`,
but no host metadata. The message must still be complete enough to act and
must omit hostname/instance/agent fields.

Complete `vpn.service.up` uses `prev_active=false`, `active=true`. A first-seen
fixture uses `prev_active=null`, `active=true` and must say “first seen,” not
“recovered.”

### F2 — session start/end

Complete start:

```json
{
  "action": "vpn.session.start",
  "event_time": "2026-08-25T04:12:00Z",
  "actor": {"principal": "alice", "source_ip": "1.2.3.4"},
  "target": {"id": "vpn-1", "type": "vpn.server", "name": "vpn-1"},
  "observables": [{"type": "ip", "value": "1.2.3.4"}, {"type": "user", "value": "alice"}],
  "extra": {"server": "vpn-1", "derived": true, "common_name": "alice"}
}
```

Complete end has the same shape with `action=vpn.session.end` and the last
observed source IP. A partial fixture omits principal but retains
`common_name=alice`; rendering may use common name as the identity. If both
identity and source IP are absent, headline the server and say only that an
unidentified client disappeared; do not invent a user.

### F3 — concurrent identity

```json
{
  "action": "vpn.session.concurrent",
  "event_time": "2026-08-25T04:13:00Z",
  "actor": {"principal": "alice"},
  "target": {"id": "vpn-1", "name": "vpn-1"},
  "extra": {
    "server": "vpn-1", "derived": true, "identity": "alice",
    "source_ips": ["1.2.3.4", "5.6.7.8"]
  }
}
```

### F4 — internal status snapshot

```json
{
  "action": "vpn.status.snapshot",
  "event_time": "2026-08-25T04:14:00Z",
  "target": {"id": "vpn-1", "name": "vpn-1"},
  "extra": {
    "server": "vpn-1",
    "client_count": 1,
    "clients": [{"common_name": "alice", "username": "alice", "real_ip": "1.2.3.4", "connected_since": "2026-08-25T04:12:00Z"}]
  }
}
```

This must remain projection-only and must not be rendered as a bulk email.

### F5/F6 — authentication

Complete failure:

```json
{
  "action": "vpn.auth.failure",
  "event_time": "2026-08-25T04:06:21.424277Z",
  "actor": {"principal": "atharva.kale", "source_ip": "107.197.154.253"},
  "target": {"id": "vpn-1", "type": "vpn.server", "name": "vpn-1"},
  "outcome": "failure",
  "extra": {"server": "vpn-1", "message": "VPN authentication FAILED", "log_line": "107.197.154.253:63403 SENT CONTROL [atharva.kale]: 'AUTH_FAILED'"}
}
```

Partial failure omits `source_ip`; the notification must retain user, server,
time, and the failed outcome without printing a blank source line. A complete
success uses `outcome=success`, the same identity fields, and the success log
line. A partial success without a user must not claim a named user.

### F7/F8 — brute-force correlation

Per-IP:

```json
{
  "action": "vpn.bruteforce",
  "event_time": "2026-08-25T04:20:00Z",
  "actor": {"principal": "alice", "source_ip": "203.0.113.10"},
  "target": {"id": "vpn-1", "name": "vpn-1"},
  "outcome": "failure",
  "extra": {"count_in_window": 5, "threshold": 5, "window_seconds": 300, "dimension": "source_ip", "trigger_event_id": "evt-1"}
}
```

Per-user uses `action=vpn.bruteforce.user`, `dimension=principal`, and should
retain a source IP only when the trigger event provides one. Never infer that
all attempts came from one IP for the per-user detector.

### F9–F12 — certificates

Complete warning:

```json
{
  "action": "vpn.cert.expiring.warning",
  "event_time": "2026-08-25T04:25:00Z",
  "target": {"id": "vpn-1/server-cert", "type": "vpn.cert.server", "name": "server-cert"},
  "outcome": "success",
  "extra": {
    "server": "vpn-1", "kind": "server", "source": "live", "subject": "CN=vpn.example.com",
    "issuer": "Example CA", "not_after": "2026-09-20T00:00:00Z", "days_remaining": 26,
    "path": "/etc/openvpn/server.crt", "revoked": false
  }
}
```

High and critical fixtures change only the threshold and `days_remaining`.
Expired uses a negative value. Probe-failed uses `outcome=failure` and an
`error`, with expiry fields optional. A partial fixture with only `name`,
`server`, and `error` must not print a made-up expiry date or issuer.

## Unique contract recommendations by event family

The outer shell remains the same, but the inner content should use these
event-specific rules:

- Availability: focus on state transition, maintenance decision, and
  service-restoration steps.
- Authentication: focus on identity, source, expected-vs-unexpected decision,
  and no automatic recovery claim.
- Correlation: focus on detector dimension, count, threshold, and time window;
  never repeat five generic explanatory paragraphs.
- Sessions: focus on who/where/which server and whether the change is expected;
  distinguish “session ended” from “incident recovered.”
- Concurrent sessions: focus on identity plus all source IPs and possible
  credential sharing.
- Certificates: focus on certificate identity, exact expiry/probe evidence,
  urgency band, and verification after renewal.
- Projection-only snapshots: remain out of notification delivery and be
  explicitly visible as internal support events in coverage metadata.

## Producer/catalog gaps and additive fields

### Must be classified before rollout

1. Add `vpn.session.end` to the notification catalog and coverage, or mark it
   explicitly non-notifying. The producer already emits it; silent omission is
   not acceptable.
2. Explicitly classify `vpn.service.health`, `vpn.status.snapshot`, and
   `vpn.cert.snapshot` as projection-only/non-notifying catalog actions. This
   prevents a future catalog audit from treating them as missing coverage.
3. Resolve the documentation/code mismatch for `vpn.cert.drift`. It is listed
   in `docs/vpn-agent.md`, but no reviewed producer emits it.

### Additive producer fields needed for perfect session messages

For `vpn.session.start` and `vpn.session.end`, add fields without renaming or
removing existing ones:

- `username` and `common_name` separately
- `real_address` and `real_ip`
- `virtual_address` and `virtual_ipv6` when available
- `connected_since` and `connected_since_t`
- `session_ended_at` for the end event
- `session_duration_seconds` when the timestamps are valid
- `client_id`, `peer_id`, and `data_channel_cipher` when useful for support

For a session end, preserve the previous client record in `extra.previous_client`
or copy the fields above into the derived event. Otherwise the end notification
cannot report duration or distinguish a normal disconnect from a stale snapshot.

### Additive content contract fields needed by all reviewed events

- `decision`: one short operator decision, placed between Facts and Next steps.
- `fixture_complete` and `fixture_partial`: catalog-owned preview samples for
  golden rendering tests.
- `recovery_event_kind`: explicit pairing for `vpn.service.down` →
  `vpn.service.up`; avoid implying that `vpn.auth.success` recovers an auth
  failure.
- `notification_mode`: `alert`, `informational`, or `projection_only`.

## Test matrix

The implementation task should add tests before rollout. Each reviewed event
needs a complete and partial fixture test, but the assertions can be grouped
by family:

| Test group | Events | Required assertions |
|---|---|---|
| Catalog parity | Every action listed above | Every producer, projection, and correlation action is either cataloged with a contract or explicitly marked projection-only/future; `vpn.session.end` is not silently absent |
| Auth rendering | `vpn.auth.failure`, `vpn.auth.success` | User/source/server/time render; missing source/user lines disappear; success does not claim recovery of failure |
| Brute-force rendering | `vpn.bruteforce`, `vpn.bruteforce.user` | Count, threshold, window, and dimension render; per-IP and per-user wording stay distinct |
| Availability rendering | `vpn.service.down`, `vpn.service.up` | Down/up pairing renders; first-seen up is not called recovered; repeated health heartbeats do not notify |
| Session rendering | `vpn.session.start`, `vpn.session.end` | Start/end facts are distinct; missing identity is handled; duration is omitted until producer support exists |
| Concurrent rendering | `vpn.session.concurrent` | All source IPs render; one identity from multiple IPs is not labeled confirmed compromise |
| Certificate rendering | All five certificate alerts | Exact expiry/probe fields render; warning/high/critical/expired wording differs; probe failure never claims expiry |
| Snapshot suppression | Health/status/cert snapshots | Projection-only actions do not create notifications or user-facing bulk payloads |
| Channel parity | All notifying events | Email/plain-text and one chat channel preserve the same decision-critical facts and omission behavior |
| Recovery semantics | Service, session, certificate, auth/brute-force | Only explicit pairs/recovery signals close an alert; manual-resolution text is present where no automatic recovery exists |

## Recommended implementation order

1. Add the additive `decision` content field and notification mode metadata to
   the profile contract/UI without changing existing profile IDs.
2. Add catalog parity metadata and the explicit `vpn.session.end` contract.
3. Mark health/status/cert snapshots projection-only and keep them out of
   delivery.
4. Add the session context fields and derive duration additively.
5. Implement event-specific VPN templates from this matrix.
6. Add complete/partial golden fixtures and channel-parity tests.
7. Only then mark OpenVPN content as fully rolled out.

