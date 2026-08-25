# BW-017 ECS service and probe notification content review

Scope: the ECS probe agent, AWS-side ECS reader, SQS connector, adapter,
service/probe projections, staleness detector, notification catalog, routing
rules, profile renderer, and existing tests for:

`service.down`, `service.degraded`, `service.unknown`, `service.up`,
`probe.agent.stale`, `probe.agent.recovered`, and `probe.agent.first_seen`.

This is a content-review artifact. No application source, tests, rules,
deployment files, database files, or secrets were changed.

## Decision

Keep the shared profile envelope (`title`, `what_happened`, `facts`,
`decision`, `next_steps`, `why_it_matters`, `evidence`,
`monitoring_method`, `impact`, `recovery`, and optional `runbook_url`), but
make the event-specific contract below authoritative for all seven actions.
The notification must distinguish:

- service health from monitoring coverage;
- a confirmed outage from an unverified state;
- recovery from first observation;
- automatic recovery from manual resolution.

The current catalog already has separate entries for all seven actions in
`blackwatch/notify/profiles.py:608-680`, and `routes_view.py` maps both
`service.*` and `probe.*` to `ecs.probe`. That is necessary coverage, but not
yet sufficient content coverage: the existing tests do not assert the ECS
contracts, complete/partial rendering, or the actual delivery path for legacy
rules.

## Evidence and data flow

1. `scripts/ecs_probe.py:130-206` produces `http_alive` and `tcp` results.
   HTTP returns `up` for any 2xx/3xx/4xx response, `degraded` for 5xx, and
   `unknown` for network-layer or configuration failures. TCP returns `up` or
   `unknown`; a TCP failure is deliberately not called `down`.
2. `blackwatch/connectors/aws_ecs.py:47-98` produces ECS health and
   running-count results. ECS health can be `up`, `down`, `degraded`, or
   `unknown`; running-count smoothing can be `up`, `degraded`, or `down`.
   Its useful task/count fields are placed in `result_extra`.
3. `blackwatch/modules/ecs_probe.py:51-110` converts one report into one
   `probe.agent.heartbeat` plus one projection-only `service.probe.result` per
   valid target. The adapter fields are exact and stable: `vpc`,
   `agent_version`, `result_count`, `target_id`, `name`, `tier`, `status`,
   `latency_ms`, `error`, and `result_extra`.
4. `blackwatch/pipeline.py:45-57,128-177` excludes heartbeat/result events
   from storage and notification, then stores/routes only derived transitions.
5. `blackwatch/services/projection.py:223-270` emits first-seen/recovered
   heartbeat transitions. `:275-447` emits service transitions and adds the
   service state fields described below.
6. `blackwatch/services/staleness.py:35-82` emits `probe.agent.stale` after
   180 seconds since the last report and marks the agent inactive.
7. `blackwatch/notify/channels.py:64-113,417-439` passes `event.extra.message`
   through verbatim for the default Slack/Discord/Teams presets. A saved
   Notification Studio profile instead uses its compiled profile template.
   Therefore a legacy route can receive only the producer's short message and
   skip the structured decision/steps/evidence contract.

### Common normalized envelope

All derived events have the normal envelope fields `event_id`, `event_time`,
`source`, `action`, `outcome`, `severity`, `target`, `raw`, and `extra`.
Derived service/heartbeat events use `source.module=ecs.probe`; `_derive`
currently forces `source.transport=api` even when the original report arrived
through SQS (`projection.py:450-470`). Stale events use `transport=poll`.
Do not present transport as an operator fact until this is corrected or the
contract explicitly labels it as the BlackWatch processing path.

For content, identity precedence is:

1. `extra.service_name` for service events;
2. `target.name`;
3. `target.id`;
4. omit the identity line only when all three are absent.

Never render `None`, empty strings, placeholder values, or a zero duration
that means “not applicable”. Render a numeric zero only when it is a real
measurement (for example `total_tasks=0`). If an optional field is absent,
omit its complete fact line; do not replace it with `unknown`, `not reported`,
`no response`, or a synthetic identity. The action itself may say that the
state is unknown, but missing evidence must remain visibly missing.

## Exact current emitted fields

### Service transition events

`service.down`, `service.degraded`, `service.unknown`, and `service.up` are
created by `_project_result` with this `extra` shape:

| Field | Current source | Omission/meaning |
|---|---|---|
| `vpc` | report `vpc` | Fallback is literal `unknown`; do not render the fallback as a real environment. |
| `name`, `service_name` | report target name, then target ID | `service_name` is always populated by projection, potentially with an ID. |
| `target_id` | report target ID | Required for projection; should be shown only as a fallback identity. |
| `tier`, `monitor_tier` | report tier, then `unknown` | `http_alive`, `tcp`, `ecs_health`, `ecs_running`; do not infer a tier. |
| `prev_status` | stored service status | `null` on first observation. |
| `status` | effective projected status | One of `up`, `down`, `degraded`, `unknown`. |
| `latency_ms` | probe result | `null` for AWS-side readers and failed checks; omit. |
| `error` | probe result | `null` when no error was supplied; do not invent one. |
| `error_signal` | `_down_hint(error)` | Currently always has a fallback such as `no response`; treat it as derived evidence only when `error` exists. |
| `consecutive_failures` | projection counter | Always present; do not claim the configured threshold was met without checking the counter. |
| `consecutive_successes` | projection counter | Always present; use on `service.up` only. |
| `last_report` | transition event time | Always present as an ISO timestamp. |
| `downtime_seconds` | computed downtime | Currently present with `0` when not recovering from down; omit zero when it means not applicable. |
| `unknown_seconds` | computed unknown interval | Currently present with `0` when not recovering from unknown; omit zero when it means not applicable. |
| `down_seconds` | recovery-only computation | Added only to `service.up` when a previous `down_since` exists. |
| `tags` | `probe_targets.tags` | Optional; currently includes `env`, `role`, and AWS counts when available. |
| `monitoring_method` | incoming field or `service probe` | Current fallback is safe as a method label, not evidence. |
| `monitoring_impact` | incoming field or generic fallback | Use as impact context, not as a measured outage. |
| `message` | projection formatter | Always present and currently bypasses structured profile content on default channels. |

The derived event does **not** currently copy `result_extra` into its
notification `extra`. This hides ECS task counts, `running`, `desired`,
`below_window_pct`, `cluster`, `service`, `http_status`, `host`, and `port`
from the content renderer even though the projection stores some of them in
`service_status.extra` as `tier_extra`.

### Probe-agent transition events

`probe.agent.first_seen` and `probe.agent.recovered` currently contain:

`vpc`, `service_name` (same as VPC), `monitor_tier=probe`,
`monitoring_method=probe heartbeat`, `monitoring_impact`, `last_report` (the
new heartbeat time), `agent_version`, and `message`.

`probe.agent.stale` currently contains:

`vpc`, `service_name`, `monitor_tier=probe`, `monitoring_method`,
`monitoring_impact`, `error_signal=no heartbeat`, `last_report` (the last
successful report), `age_seconds`, `downtime_seconds` (same age),
`agent_version`, and `message`. It does **not** contain `unknown_seconds`,
`silence_seconds`, or `stale_after_seconds`.

## Event contracts

### `service.down`

Headline: `ECS service down — <service> · <vpc>`; omit the separator and VPC
when VPC is absent.

Facts: service identity; VPC/environment; `tier`; current status; previous
status when present; `consecutive_failures`; `error`/`error_signal` when an
error exists; latency when measured; detection time; last report; and
`cluster`, `service`, task counts, or running/desired counts only after they
are copied into the derived event. Do not claim customer impact from an
ECS health signal alone without the service impact statement.

Decision: `Treat this as an outage unless an approved maintenance window or an
intentional scale-to-zero explains it.` A probe failure by itself must not be
described as confirmed application failure when the status is actually
`unknown`.

Ordered next steps:

1. Confirm the target, environment, maintenance window, and whether desired
   count is intentionally zero.
2. Inspect the failing tier: endpoint/DNS/network for `http_alive` or `tcp`,
   ECS task/container health for `ecs_health`, and running/desired counts for
   `ecs_running`.
3. Check recent deployments, service logs, dependencies, and the error signal.
4. Restore the service or escalate through the service outage runbook.

Evidence: the transition action, `status`, `prev_status`, failure counter,
timestamp, probe tier, and raw error/latency. If a task-count field is not on
the derived event, say that task-level evidence is unavailable rather than
reconstructing it from stored state in the renderer.

Impact: customer requests or dependent systems may fail; scope is not known
from this event unless the producer supplies a service-specific impact.

Recovery/manual resolution: `service.up` is the automatic recovery event only
after the configured successful-probe threshold. Current code uses
`UP_THRESHOLD=2` (`projection.py:196-204`), while `docs/ecs.md:327-332` and
the rules comment say one success. Resolve the contract to the actual emitted
counter before rollout. Maintenance or intentional scale-to-zero is manual
resolution/annotation, not a fabricated recovery event.

### `service.degraded`

Headline: `ECS service degraded — <service> · <vpc>`.

Facts: service, VPC, tier, current and previous status, latency when present,
error/HTTP signal when present, failure counter, detection time, and
tier-specific counts when propagated. For `ecs_health`, prefer healthy,
unhealthy, unknown, and total task counts. For `ecs_running`, prefer running,
desired, and below-window percentage. For HTTP, prefer HTTP status and
latency. Do not use the same generic “some tasks healthy” wording for all
tiers.

Decision: `Decide whether this is an early outage signal, capacity pressure,
or an approved change.`

Ordered next steps:

1. Identify whether the signal is HTTP 5xx, mixed ECS task health, or a
   sustained running-count shortfall.
2. Compare latency/errors and capacity with recent deployments and dependency
   health.
3. Restore capacity or reduce traffic impact before the service crosses down.
4. Record the owner and the change or incident that explains the signal.

Evidence: the degraded transition, raw status/error/latency, failure count,
and tier-specific result data when available.

Impact: some requests, tasks, or users may experience errors or increased
latency; do not call the whole service unavailable unless `service.down` is
emitted.

Recovery/manual resolution: use `service.up` after the configured successful
threshold. A single good sample, a deployment completion message, or a manual
acknowledgement is not recovery.

### `service.unknown`

Headline: `ECS service health unverified — <service> · <vpc>`.

Facts: service, VPC, tier, current/previous status, `unknown_seconds`,
`error`/`error_signal` when supplied, latency when measured, last report, and
detection time. State explicitly that this is an inability to classify the
service, not proof of downtime.

Decision: `Treat service health as unverified until the probe path or an
independent service check establishes a known state.`

Ordered next steps:

1. Check the probe agent and the endpoint path separately.
2. Check DNS, security groups, routes, credentials, listener/port, and the
   most recent probe error.
3. Independently verify the service through ECS or an approved out-of-band
   check.
4. Restore monitoring and record the blind interval and conclusion.

Evidence: the sustained unknown interval and the available network/config
error; a missing error must result in no error line.

Impact: the service may be healthy, degraded, or down while BlackWatch cannot
distinguish those states. This is an availability-confidence incident and
must not be rendered as a confirmed outage.

Recovery/manual resolution: a valid known result changes the state. `service.up`
is a recovery notification only when the projection confirms healthy recovery
from an emitted unknown alert; a later `service.down` is a new confirmed
service condition, not a recovery. Manual resolution requires an independent
check and a recorded explanation for the blind interval.

### `service.up`

Headline: `ECS service recovered — <service> · <vpc>` when `prev_status` is
`down`, `degraded`, or an emitted `unknown`; use `ECS service first healthy
observation — ...` when `prev_status` is absent. The action key is the same,
so the renderer must branch on `prev_status` and not always say “recovered”.

Facts: service, VPC, tier, current status, previous status, consecutive
successes, current latency when measured, last report/detection time, and
positive `down_seconds` or `unknown_seconds` only when applicable. Include
`downtime_seconds` only if it is a real measured outage duration; current code
sets it to zero for non-down recoveries.

Decision: `Confirm stability and review the earlier outage or monitoring gap
before closing the incident.`

Ordered next steps:

1. Verify that the required consecutive healthy probes continue.
2. Review the incident timeline, deployment, dependency, and failure signal.
3. Confirm that the service is healthy from the relevant tier, not only from a
   different monitoring path.
4. Close the earlier service alert only after cause and stability are understood.

Evidence: the success counter, previous status, current latency, and measured
down/unknown duration. A first-ever `service.up` has no outage evidence and
must be labeled first observation.

Impact: availability has returned, but the cause may remain unresolved and a
flapping service may fail again.

Recovery/manual resolution: this is terminal for the corresponding service
condition; there is no further automatic recovery action. Closing the incident
is manual after review. It does not recover `probe.agent.stale`.

### `probe.agent.stale`

Headline: `Probe coverage stale — <vpc>`.

Facts: VPC/scope, last report, `age_seconds`, configured staleness threshold,
agent version when present, detection time, and affected monitoring tiers.
The current producer emits `age_seconds` but not the threshold; add
`stale_after_seconds` or keep the threshold as versioned catalog metadata.
Do not render `unknown_seconds`: it is not emitted here.

Decision: `Restore monitoring coverage or explicitly accept the blind interval;
do not treat agent silence as proof that services are down.`

Ordered next steps:

1. Check the probe task/process, host/network path, SQS access, SSM access,
   credentials, and last logs.
2. Independently check critical services while the VPC is blind.
3. Restore the agent and verify a fresh heartbeat plus expected result count.
4. Review the silent interval for missing events and record manual acceptance
   if the silence was intentional.

Evidence: `last_report`, `age_seconds`, the staleness check time, and the
configured threshold. `message` is presentation text, not the primary
evidence.

Impact: HTTP/TCP monitoring for the VPC is unavailable; service outages and
security-relevant changes in that scope may go undetected. This event says
nothing about ECS task health by itself.

Recovery/manual resolution: `probe.agent.recovered` is the coverage recovery
event. An operator acknowledgement, a service.up event, or a new service
result does not close this coverage gap. Manual resolution is repair/disablement
plus a documented blind interval if the agent is intentionally retired.

### `probe.agent.recovered`

Headline: `Probe coverage recovered — <vpc>`.

Facts: VPC/scope, new heartbeat time, previous last-report time, silence
duration, agent version, and result count when available. The current producer
only emits the new `last_report` and `agent_version`; it does not emit the
previous report, silence duration, stale threshold, or result count.

Decision: `Confirm that coverage is stable and account for evidence that may be
missing from the silence interval.`

Ordered next steps:

1. Verify consecutive heartbeats and expected target/result count.
2. Review the silent interval and independently checked service state.
3. Check the agent version/configuration and SQS/SSM path for recurrence.
4. Close the coverage incident only after stability and missing-evidence
   review.

Evidence: the heartbeat after `active=False` and the projection transition.
There is currently no stable `recovered_from_event_id` or previous timestamp,
so do not claim an exact silence duration.

Impact: coverage is available again, but events during the blind interval may
be missing or delayed.

Recovery/manual resolution: this is the automatic recovery for
`probe.agent.stale` only. It does not recover `service.down` or
`service.unknown`; those require their own service evidence. Manual closure
still requires review of the blind interval.

### `probe.agent.first_seen`

Headline: `New probe coverage source — <vpc>`.

Facts: VPC/scope, first report time, agent version when present, result count
when present, and source/ownership context only if the normalized event really
contains it. The current projection does not copy the heartbeat's
`result_count`, account, region, queue identity, or target inventory into the
derived event.

Decision: `Confirm that the new probe is expected, assigned to the right
environment, and authorized to report these targets.`

Ordered next steps:

1. Verify the VPC/account, queue binding, task owner, and deployment/change.
2. Confirm target assignment, credentials, tier, and expected result count.
3. Confirm that the source is not duplicating another probe or creating false
   coverage.
4. Record the onboarding decision or disable/remove the unexpected source
   through the approved change path.

Evidence: the first heartbeat transition (`prev_active is None`) and its
available agent version/report time. Do not call the event a security finding
without an ownership or authorization signal.

Impact: a new source changes monitoring coverage. An unexpected or misbound
probe can create false confidence; an expected source may improve visibility.

Recovery/manual resolution: no recovery event is required. Resolution is
owner confirmation and onboarding/change documentation, or intentional
disablement. Do not pair first-seen with `probe.agent.recovered`.

## Complete and partial fixtures

These are proposed normalized derived-event fixtures for golden tests. They
are documentation data only and must not be used as delivered identities or
production examples. `null` means the producer did not provide the field; the
renderer must omit that fact line.

### Complete fixtures

```json
{
  "service.down": {"target":{"id":"svc-1","type":"ecs.service","name":"payments-api"},"extra":{"vpc":"prod","service_name":"payments-api","target_id":"svc-1","tier":"http_alive","monitor_tier":"http_alive","prev_status":"up","status":"down","latency_ms":5000,"error":"timed out","error_signal":"timeout","consecutive_failures":2,"last_report":"2026-08-25T09:59:00Z","tags":{"env":"prod","role":"api"}}},
  "service.degraded": {"target":{"id":"svc-2","type":"ecs.service","name":"orders-api"},"extra":{"vpc":"prod","service_name":"orders-api","target_id":"svc-2","tier":"ecs_health","monitor_tier":"ecs_health","prev_status":"up","status":"degraded","latency_ms":null,"error":null,"error_signal":"no response","consecutive_failures":2,"last_report":"2026-08-25T10:00:00Z","tier_extra":{"total_tasks":4,"healthy":3,"unhealthy":1,"unknown":0}}},
  "service.unknown": {"target":{"id":"svc-3","type":"ecs.service","name":"billing-api"},"extra":{"vpc":"prod","service_name":"billing-api","target_id":"svc-3","tier":"tcp","monitor_tier":"tcp","prev_status":"up","status":"unknown","latency_ms":3000,"error":"DNS lookup failed","error_signal":"DNS lookup failed","unknown_seconds":900,"last_report":"2026-08-25T10:00:00Z"}},
  "service.up": {"target":{"id":"svc-1","type":"ecs.service","name":"payments-api"},"extra":{"vpc":"prod","service_name":"payments-api","target_id":"svc-1","tier":"http_alive","monitor_tier":"http_alive","prev_status":"down","status":"up","latency_ms":42,"consecutive_successes":2,"down_seconds":180,"downtime_seconds":180,"last_report":"2026-08-25T10:03:00Z"}},
  "probe.agent.stale": {"target":{"id":"prod","type":"probe.agent","name":"probe-prod"},"extra":{"vpc":"prod","service_name":"prod","monitor_tier":"probe","last_report":"2026-08-25T09:50:00Z","age_seconds":600,"downtime_seconds":600,"agent_version":"1.0"}},
  "probe.agent.recovered": {"target":{"id":"prod","type":"probe.agent","name":"prod"},"extra":{"vpc":"prod","service_name":"prod","monitor_tier":"probe","last_report":"2026-08-25T10:01:00Z","agent_version":"1.0","previous_last_report":"2026-08-25T09:50:00Z","silence_seconds":660}},
  "probe.agent.first_seen": {"target":{"id":"prod","type":"probe.agent","name":"prod"},"extra":{"vpc":"prod","service_name":"prod","monitor_tier":"probe","last_report":"2026-08-25T10:00:00Z","agent_version":"1.0","result_count":12}}
}
```

The complete fixture intentionally includes `tier_extra` and the recovered
probe correlation fields that are **recommended producer additions**. Tests
must fail or mark the fixture partial until those fields are actually emitted.

### Partial fixtures and expected omissions

```json
{
  "service.down": {"target":{"id":"svc-x","type":"ecs.service","name":null},"extra":{"vpc":"dev","service_name":"svc-x","tier":"tcp","status":"down","prev_status":null,"error":null,"latency_ms":null,"consecutive_failures":1}},
  "service.degraded": {"target":{"id":"svc-y","type":"ecs.service","name":"orders"},"extra":{"vpc":null,"tier":"ecs_running","status":"degraded","error":null,"latency_ms":null,"consecutive_failures":2}},
  "service.unknown": {"target":{"id":"svc-z","type":"ecs.service","name":null},"extra":{"vpc":"dev","service_name":"svc-z","tier":"tcp","status":"unknown","unknown_seconds":600,"error":null}},
  "service.up": {"target":{"id":"svc-u","type":"ecs.service","name":"api"},"extra":{"vpc":"dev","tier":"http_alive","status":"up","prev_status":null,"consecutive_successes":1,"latency_ms":null,"down_seconds":null}},
  "probe.agent.stale": {"target":{"id":"dev","type":"probe.agent","name":"probe-dev"},"extra":{"vpc":"dev","last_report":null,"age_seconds":null,"agent_version":null}},
  "probe.agent.recovered": {"target":{"id":"dev","type":"probe.agent","name":"dev"},"extra":{"vpc":"dev","last_report":"2026-08-25T10:01:00Z","agent_version":null}},
  "probe.agent.first_seen": {"target":{"id":"dev","type":"probe.agent","name":"dev"},"extra":{"vpc":"dev","last_report":"2026-08-25T10:00:00Z","agent_version":null}}
}
```

Expected behavior for the partial fixtures:

- no `in dev`/`· dev` suffix when VPC is absent;
- no latency, error, duration, version, previous-status, or task-count line
  when the value is absent;
- target ID may be used as the identity fallback only when it is present;
- no `unknown`, `not reported`, `no response`, or invented outage duration
  should appear merely because a field is absent;
- `service.up` with no previous status must not say “recovered”;
- `probe.agent.recovered` must not claim a silence duration until the producer
  emits a previous timestamp or duration.

## Catalog, routing, and producer gaps

1. **Structured content is bypassable.** `channels.py` renders
   `extra.message` verbatim for the default presets. The ECS projection always
   supplies `message`, but that message contains only a headline and a few
   facts, not the profile's decision, ordered next steps, evidence, impact, or
   manual-resolution guidance. A legacy route can therefore look covered in
   the catalog while delivering incomplete content. Either make the structured
   profile template the route authority or make the producer message a compact
   rendering of the same contract.
2. **ECS module rollout metadata is inconsistent.**
   `apply_event_contracts` marks the seven events rolled out, but its module
   metadata update at `content_contracts.py:505-507` only names
   `vpn.openvpn`, `ec2.host`, and `aws.rds`. The `ecs.probe` module can remain
   `generic` with a stale content-gap count even while its events are marked
   rolled out. `tests/test_notification_catalog.py:84-103` does not assert the
   ECS module status.
3. **No BW-017 rendering goldens exist.** Existing tests assert that the seven
   keys exist and expose a few fields (`test_notification_profiles.py:79-95`),
   but do not render each event, test the complete/partial fixtures, assert
   omission behavior, or cover email plus a chat channel. The rendering tests
   cover generic profile mechanics and VPN examples, not ECS contracts.
4. **Probe stale field mismatch.** The stale producer emits `age_seconds`
   (`staleness.py:67-70`), while the current service contract fixture uses
   `unknown_seconds` (`content_contracts.py:260-275`). The real stale duration
   is consequently omitted or shown incorrectly.
5. **Probe recovery lacks correlation facts.** `probe.agent.recovered`
   receives only the new heartbeat time and version (`projection.py:253-267`).
   It cannot truthfully render previous report, silence duration, stale
   threshold, or a recovery correlation ID. Add those fields additively or
   explicitly omit them.
6. **First-seen loses heartbeat facts.** The heartbeat has `result_count`, but
   `_project_heartbeat` does not copy it into either derived event. Account,
   region, queue binding, and target inventory are also unavailable in the
   derived event, so onboarding content must not imply those facts.
7. **Tier-specific evidence is lost.** `result_extra` is stored in state but
   is not copied into the derived transition event. ECS task counts and
   running/desired data should be normalized into a bounded `tier_extra` or
   named fields before they are promised in notifications.
8. **Initial transitions bypass hysteresis.** `effective` starts as the first
   `incoming_status` (`projection.py:323-333`), so a first result can emit
   `service.down`, `service.degraded`, `service.unknown`, or `service.up`
   before the stated thresholds. This conflicts with the content wording,
   `docs/ecs.md:327-332`, and the rule comment. The contract must either label
   first observations explicitly or the producer must enforce thresholds
   before emitting a transition.
9. **Threshold documentation disagrees with code.** Code uses
   `UP_THRESHOLD=2`; `docs/ecs.md` and `rules/ecs.yaml:1-3` describe one
   successful probe. The notification must not promise a recovery threshold
   until this is reconciled.
10. **Unknown rule wording is inaccurate.** `rules/ecs.yaml:46-72` says
    unknown follows consecutive probe failures, while the projection uses a
    ten-minute elapsed interval (`UNKNOWN_AFTER_SECONDS=600`). Use elapsed
    unknown duration in the headline/facts and correct the rule description.
11. **Mixed ECS health statuses need validation.**
    `aws_ecs.py:55-64` can count a task with `HEALTHY` plus a missing
    `healthStatus` as healthy because it filters falsey values before `all()`.
    A notification contract should not claim all tasks are healthy until the
    producer distinguishes missing/unknown container status.
12. **Source transport is normalized inaccurately.** `_derive` forces API
    transport for derived service and heartbeat events, including queue-fed
    reports. This is not a content blocker if transport is omitted, but it is
    unsafe to show as evidence until corrected.

## Existing tests and verification status

Relevant tests inspected:

- `tests/test_ecs_probe.py` covers adapter shape, HTTP/AWS aggregation, and
  running-count smoothing, but not notification content.
- `tests/test_ecs_projection.py` covers sustained unknown and unknown recovery.
  Its first unknown assertion expects no event, which exposes the initial-state
  behavior mismatch if the current projection is evaluated literally.
- `tests/test_notification_profiles.py` covers catalog presence and token
  compilation, but its uniqueness/rollout assertions cover only the previously
  approved VPN, EC2, and RDS modules.
- `tests/test_notification_catalog.py` covers delivery coverage states, not
  ECS module content rollout metadata.
- `tests/test_notification_rendering.py` covers generic guided rendering and
  VPN previews; it has no ECS event golden tests.

The environment did not provide a `pytest` executable, so this review records
no test-pass claim. The recommended BW-017 test set is seven complete fixtures
plus seven partial fixtures, each rendered as plain/email and Slack or
Discord, with assertions for headline, every section, recovery wording, and
absence of unavailable fields; projection tests should also assert the exact
derived `extra` fields and first-observation semantics.

