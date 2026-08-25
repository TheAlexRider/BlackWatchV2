# BW-015 EC2 host and SSH notification content review

Status: review complete · implementation remains gated by the coordinator

This review covers the `ec2.host` notification module. It is an analysis artifact only. No application source, tests, rules, deployment files, database files, or production data were changed.

## Review conclusion

The common notification shell is suitable for this module:

1. headline
2. What happened
3. Facts
4. Decision
5. Next steps
6. Evidence
7. Recovery or manual resolution

The inner content must not be generated from one generic EC2 paragraph. SSH access, privilege use, persistence changes, FIM changes, resource pressure, telemetry loss, and package/runtime changes require different facts and different operator decisions.

The current profile contract has `title`, `what_happened`, `facts`, `next_steps`, `why_it_matters`, `evidence`, `monitoring_method`, `impact`, `recovery`, and `runbook_url`, but no first-class `decision` field. Add `decision` additively to the content contract before marking EC2 rolled out. Until then, the renderer may place `Decision:` as the first line of `Next steps`, but the UI should expose it separately so an operator can edit it without rewriting the procedure.

Do not notify on every heartbeat or snapshot. Those are input/control events. Notify on the meaningful transition, the rejected snapshot, a configured performance breach, or a security-relevant state change.

## Evidence inventory

### Normalized envelope shared by most events

The adapter in `blackwatch/modules/ec2_host.py` normalizes these fields:

| Envelope field | Source and behavior | Rendering rule |
|---|---|---|
| `source.module` | `ec2.host` | Use only as a small Monitoring label, not as the headline. |
| `source.account`, `source.region` | Host payload, falling back to ingest context | Include when useful for fleet triage; omit when absent. |
| `event_time` | Journal/FIM/OOM time where available; otherwise adapter/projection time | Always show for an alert. Do not call an adapter timestamp the detection time unless the source supplied one. |
| `target.id` | EC2 instance ID | Include as stable identity. |
| `target.name` | Hostname; derived events may use the saved display name | Show `name (instance-id)` when both exist. |
| `actor.principal` | User for SSH/sudo; best-effort FIM process identity | Never replace a missing identity with `unknown user`. |
| `actor.source_ip` | SSH source address | Omit when not emitted. |
| `outcome`, `severity` | Normalized event envelope/rule | Use for status and urgency, not as evidence. |
| `extra.tags` | Host tags promoted to every adapter event | Include only configured routing/context tags; never dump the whole object by default. |

### Producer facts by source

| Source | Exact normalized extras | Important limitations |
|---|---|---|
| SSH journal | `method` or `reason=invalid_user`; top-level actor and user/IP observables | Failure parsing does not preserve a normalized port, SSH key fingerprint, or failure reason beyond `invalid_user`. |
| Sudo journal | `command` only for `host.sudo.exec`; empty extra for `host.sudo.failure` | Sudo failure needs additive `reason`, `tty`, `target_user`, and optionally a scrubbed message. Sudo success needs `tty`, `pwd`, and `target_user` if available. |
| Snapshot diff | Per-transition fields listed below | Several diffs discard before/after hashes, process details, versions, and previous values. Do not invent them in notification text. |
| FIM change | `path`, `change_type`, before/after hashes, sizes, modes, owners, `detection`, and optional `actor` dict | Top-level FIM actor is only built from `comm` and `uid`; full audit context remains in `extra.actor`. |
| Heartbeat/projection | Memory, CPU, collector, RPM DB, coverage, and uptime data | Projection events often retain only the fields needed to detect a transition. Additive fields are required for a richer message. |
| Performance alert | Metric, label, threshold, comparison, current value, window, breach ratio, rule identity, tags, generated message | This is the actionable alert for heartbeat metrics; `host.service.health` itself is not. |

## Event-by-event message matrix

The `omit` instruction in every row is mandatory: absent values are removed rather than rendered as `unknown`, `sample`, `not available`, or a generic filler sentence.

### Access, authentication, and privilege

| Event | Exact emitted fields; omit when absent | Headline / What happened | Facts / Decision | Ordered next steps | Evidence / Recovery |
|---|---|---|---|---|---|
| `host.auth.ssh.failure` | `actor.principal`, `actor.source_ip`, `target.name/id`, `extra.method` or `extra.reason=invalid_user`, `event_time`, account/region, tags | **SSH login failed on `<host>`**. An SSH authentication attempt failed. | Facts: user, source IP, method/reason, time, host. Decision: **Expected, investigate, or contain?** | 1. Confirm whether the user and source IP are expected. 2. If not, review nearby SSH failures and active sessions. 3. Apply the SSH/credential runbook if the pattern is suspicious. | Evidence is the normalized SSH event and journal cursor-backed event time; do not print raw `MESSAGE` unless explicitly scrubbed. No automatic recovery; manual resolution is an expected/unauthorized decision. |
| `host.auth.ssh.password.success` | `actor.principal`, `actor.source_ip`, `extra.method`, target, time | **SSH password login succeeded on `<host>`**. A password-based SSH login succeeded. | Facts: user, IP, method, time. Decision: **Was password authentication authorized for this host and user?** | 1. Confirm the account owner initiated the session. 2. Verify password authentication is allowed by policy. 3. If unexpected, investigate session activity and rotate credentials. | Evidence is the successful journal event. No recovery pair; manually close after validation or containment. |
| `host.auth.ssh.success` | `actor.principal`, `actor.source_ip`, `extra.method` (normally public key), target, time | **SSH login succeeded on `<host>`**. An SSH authentication succeeded. | Facts: user, IP, method, time. Decision: **Does this match an approved access path?** | 1. Confirm the user, source, and key-based access are expected. 2. Escalate only if the source or timing is anomalous. | Evidence is the journal event. Informational/manual resolution; do not send recovery language. |
| `host.bruteforce` | actor principal/IP when present, target, `extra.count_in_window`, `window_seconds`, `threshold`, `dimension`, `trigger_event_id`, time | **SSH brute-force activity from `<source>`**. Repeated SSH failures crossed the configured threshold. | Facts: source IP, count, threshold, window, target. Decision: **Is this hostile probing, a broken client, or an approved scanner?** | 1. Confirm the source and target host. 2. Check whether the source is an approved scanner or NAT. 3. Block/rate-limit and investigate accounts if unauthorized. | Evidence is the derived correlation event plus the triggering SSH event ID. No recovery event is produced; resolve manually or record that the window expired. |
| `host.bruteforce.user` | actor principal/IP when present, target, count/window/threshold, `dimension=principal`, trigger ID, time | **SSH brute-force activity against `<user>`**. Repeated failures targeted one account. | Facts: account, source IPs only when available, count, threshold, window. Decision: **Is the account under credential stuffing?** | 1. Confirm the account owner and recent successful logins. 2. Investigate source IPs. 3. Lock, reset, or add controls according to the credential-response runbook. | Evidence is the correlation event and trigger ID. No automatic recovery; manually close after account review/containment. |
| `host.sudo.failure` | `actor.principal` when parsed; target, time; current producer extra is otherwise empty | **Sudo authorization failed on `<host>`**. A user failed a privileged-command authorization or authentication check. | Facts: user when available, host, time. Decision: **Was this an expected admin action or an unauthorized privilege attempt?** Never claim a command because current producer does not emit one for failures. | 1. Identify the user and intended target command from host audit/journal data. 2. Check whether the account should have sudo access. 3. Investigate repeated failures and contain if unexpected. | Evidence is the normalized failure event. Additive producer fields needed: `reason`, `tty`, `target_user`, `command` when safely available, and a scrubbed event message. No recovery pair. |
| `host.sudo.exec` *(producer-only)* | `actor.principal`, `extra.command`, target, time; currently no catalog profile | **Privileged command executed on `<host>`**. A sudo command was accepted for the user. | Facts: user, command, host, time. Decision: **Was this exact command approved?** Do not call it malicious from sudo success alone. | 1. Confirm the actor and change/ticket. 2. Validate command scope and target. 3. If unauthorized, preserve audit evidence and follow privileged-access response. | Evidence is the scrubbed parsed sudo line and normalized command. No recovery pair; manual review. Add `tty`, `pwd`, and target user for a complete decision. |

### Persistence, identity, network exposure, and configuration

| Event | Exact emitted fields; omit when absent | Headline / What happened | Facts / Decision | Ordered next steps | Evidence / Recovery |
|---|---|---|---|---|---|
| `host.authorized_key.added` | `extra.user`, `fingerprint`, `preview`, target, time, tags | **SSH key added for `<user>` on `<host>`**. A new authorized key appeared. | Facts: account, fingerprint, short preview if present, host, time. Decision: **Can the key be tied to an approved owner/change?** | 1. Match the fingerprint to the owner and change record. 2. If unrecognized, remove the key and rotate/verify the account. 3. Review nearby logins from the account. | Evidence is snapshot diff data. The agent intentionally does not provide the complete public-key body/comment. No automatic recovery; manual resolution. |
| `host.authorized_key.removed` *(producer-only)* | `extra.user`, `fingerprint`, target, time | **SSH key removed for `<user>` on `<host>`**. A previously observed authorized key disappeared. | Facts: account and fingerprint. Decision: **Was key removal planned or did it indicate cleanup after compromise?** | 1. Confirm the change owner. 2. Check for recent use of the key. 3. Reconcile the host's approved key inventory. | Evidence is snapshot diff data. No recovery pair; manual resolution. |
| `host.user.added` | `extra.user`, `uid`, `shell`, target, time | **Local user added on `<host>`**. A new local account appeared. | Facts: username, UID, shell, host, time. Decision: **Is this account approved and least-privileged?** | 1. Identify owner and provisioning source. 2. Check shell, groups, SSH keys, and first login. 3. Disable/remove only under the approved response procedure. | Evidence is the users snapshot diff. No recovery event; manual resolution. |
| `host.user.removed` *(producer-only)* | `extra.user`, target, time | **Local user removed from `<host>`**. A previously observed local account disappeared. | Facts: username, host, time. Decision: **Was deprovisioning expected and complete?** | 1. Confirm ticket/owner. 2. Check lingering keys, processes, sudoers entries, and data ownership. | Evidence is users snapshot diff. No automatic recovery. |
| `host.port.opened` | `extra.proto`, `address`, `port`, `process` when emitted, target, time | **Listening port opened on `<host>`**. A new listener was observed. | Facts: protocol, bind address, port, process when available. Decision: **Is this exposure approved and intentionally bound?** | 1. Identify the service/process owner. 2. Compare bind scope with expected exposure. 3. Restrict/stop the listener or update the approved inventory. | Evidence is the ports snapshot diff. If `process` is absent, omit it; do not infer a process from the port. No recovery pair. |
| `host.port.closed` *(producer-only)* | `extra.proto`, `address`, `port`, target, time | **Listening port closed on `<host>`**. A previously observed listener disappeared. | Facts: protocol, address, port, time. Decision: **Was service removal planned, or did availability change unexpectedly?** | 1. Confirm deployment/maintenance. 2. Check dependent service health. 3. Reopen/escalate only if the service should be available. | Evidence is ports snapshot diff. No recovery pair; manual/operational resolution. |
| `host.service.added` | `extra.unit`, target, time | **System service added on `<host>`**. A new enabled systemd service/timer appeared. | Facts: unit name, host, time. Decision: **Is the unit approved, signed, and expected to start?** | 1. Identify package and owner. 2. Review unit file and enablement source. 3. Disable/quarantine if unauthorized. | Evidence is the systemd unit set diff. No recovery pair. |
| `host.service.removed` *(producer-only)* | `extra.unit`, target, time | **System service removed from `<host>`**. A previously observed enabled unit disappeared. | Facts: unit name, host, time. Decision: **Was removal planned, and did it affect a dependency?** | 1. Confirm change record. 2. Check dependent service health. 3. Restore only through the owner-approved deployment path. | Evidence is systemd snapshot diff. No automatic recovery. |
| `host.cron.changed` | `extra.path`, `change` (`added`, `removed`, `changed`), target, time | **Scheduled task changed on `<host>`**. A monitored cron file changed. | Facts: path and change type. Decision: **Does the new schedule belong to an approved job?** | 1. Inspect the file diff through the host/FIM view. 2. Identify owner and execution account. 3. Remove or restore unauthorized persistence. | Evidence is the cron snapshot diff. Current producer does not include before/after hashes or content; add them if the notification must explain the exact change. No recovery pair. |
| `host.sudoers.changed` | `extra.changes` map of path → `added/removed/changed`, target, time | **Sudo policy changed on `<host>`**. One or more sudoers files changed. | Facts: affected paths and change types. Decision: **Did an approved administrator change privilege policy?** | 1. Run `visudo -c` and inspect the exact diff. 2. Identify actor/change owner. 3. Revert or constrain unauthorized privilege grants. | Evidence is sudoers snapshot diff. Add before/after hashes or FIM actor if exact attribution is required. No automatic recovery. |
| `host.suid.added` | `extra.path`, target, time | **SUID executable added on `<host>`**. A new set-user-ID file appeared. | Facts: path, host, time. Decision: **Is the file from an approved package and expected to be SUID?** | 1. Identify package/owner and verify checksum. 2. Check creation/change timeline. 3. Remove SUID or quarantine if unauthorized. | Evidence is SUID path-set diff. No recovery pair. |
| `host.suid.removed` *(producer-only)* | `extra.path`, target, time | **SUID executable removed from `<host>`**. A previously observed SUID path disappeared. | Facts: path, host, time. Decision: **Was privilege reduction expected, and did it break a service?** | 1. Confirm package/deployment change. 2. Check whether the file was removed or permissions changed. | Evidence is SUID set diff. No automatic recovery. |
| `host.kernel.module.added` | `extra.module`, target, time | **Kernel module loaded on `<host>`**. A module not present in the prior snapshot appeared. | Facts: module name, host, time. Decision: **Is this module approved for this kernel and workload?** | 1. Identify package, signer, and load source. 2. Compare with change window. 3. Unload/isolate only with kernel-owner guidance. | Evidence is the `lsmod` set diff. No automatic recovery. |
| `host.kernel.module.removed` | `extra.module`, target, time | **Kernel module removed from `<host>`**. A previously observed module disappeared. | Facts: module, host, time. Decision: **Was removal planned or did a dependency fail?** | 1. Confirm maintenance. 2. Check affected interfaces/services. | Evidence is kernel-module set diff. No automatic recovery. |

### File integrity and monitoring coverage

| Event | Exact emitted fields; omit when absent | Headline / What happened | Facts / Decision | Ordered next steps | Evidence / Recovery |
|---|---|---|---|---|---|
| `host.fim.created` | `path`, `change_type=created`, after hash/size/mode/owner when supplied, `detection`, optional `actor` (`uid/gid/pid/comm/exe/proctitle`), target, time | **Protected file created on `<host>`**. A watched path appeared. | Facts: path, detection method, after metadata, actor when auditd supplied. Decision: **Is this file expected and created by an approved process?** | 1. Identify owner/process. 2. Compare content/hash with expected baseline. 3. Quarantine/remove only after preserving evidence if unauthorized. | Evidence is FIM baseline/inotify/auditd data. A created file can be manually resolved; no recovery event. |
| `host.fim.modified` | path, before/after hash/size/mode/owner, `detection`, optional actor, target, time | **Protected file modified on `<host>`**. A watched file's content or metadata changed. | Facts: path, exact before/after values available, detection, actor. Decision: **Was this change approved?** | 1. Inspect before/after and actor. 2. Validate syntax for config files. 3. Restore known-good state or approve the new baseline. | Evidence is FIM change record. No recovery pair; resolution is restore/approve and document. |
| `host.fim.deleted` | `path`, `change_type=deleted`, before hash/size/mode/owner when supplied, detection, optional actor, target, time | **Protected file deleted on `<host>`**. A watched path disappeared. | Facts: path, last known metadata, detection, actor if available. Decision: **Was deletion planned, or did it remove a security/control file?** | 1. Verify deletion owner and impact. 2. Restore from approved source if needed. 3. Search for related persistence or tampering. | Evidence is FIM event/history. No automatic recovery; manual restoration/approval. |
| `host.fim.perm_changed` | `path`, before/after mode, hashes/sizes if emitted, detection, optional actor, target, time | **Protected file permissions changed on `<host>`**. Mode bits changed on a watched path. | Facts: path, old/new mode, actor/detection. Decision: **Do the new permissions match least privilege?** | 1. Validate mode against policy. 2. Identify actor. 3. Restore secure mode if unexpected. | Evidence is FIM metadata. No recovery pair. |
| `host.fim.owner_changed` | `path`, before/after owner, hashes/sizes if emitted, detection, optional actor, target, time | **Protected file owner changed on `<host>`**. UID/GID ownership changed. | Facts: path, old/new owner, actor/detection. Decision: **Is ownership change authorized?** | 1. Compare with package/deployment owner. 2. Check access implications. 3. Restore ownership if unauthorized. | Evidence is FIM metadata. No recovery pair. |
| `host.file.changed` | `path`, `change` from critical-file hash diff, target, time | **Critical host file changed on `<host>`**. A monitored critical-file hash changed. | Facts: path and change kind only. Decision: **Was this critical-file change expected?** | 1. Open the FIM/history view for exact before/after evidence. 2. Validate the config and actor. 3. Restore or approve. | Evidence is the `critical_files` snapshot diff. Current producer does not emit hashes or actor here; add `sha256_before`, `sha256_after`, and FIM attribution if this alert must stand alone. No recovery pair. |
| `host.fim.coverage` | `paths_configured`, `files_tracked`, `last_full_scan_at`, `last_scan_duration_ms`, `scan_errors`, `paths_inotify`, `paths_baseline_only`, `inotify_active`, `inotify_watch_count`, `auditd_active`, optional `configured_paths`, `path_stats` | **File-integrity monitoring coverage changed on `<host>`** only when coverage degrades. The raw heartbeat summary is not itself an incident. | Facts: tracked/configured counts, last scan, errors, active sensors. Decision: **Is monitoring coverage sufficient for the host's risk tier?** | 1. Compare configured vs tracked paths. 2. Resolve scan errors/sensor failures. 3. Confirm coverage returns to policy. | Evidence is projection-only coverage data. Treat healthy summaries as UI-only. Add a separate degraded/recovered transition if notifications are required; current event has no recovery semantics. |

### Resource pressure, telemetry, and package/runtime state

| Event | Exact emitted fields; omit when absent | Headline / What happened | Facts / Decision | Ordered next steps | Evidence / Recovery |
|---|---|---|---|---|---|
| `host.cpu.anomaly` | `load_norm_1min`, `load_1min`, `cpu_count`, `baseline_mean`, `baseline_stdev`, `baseline_n`, target, time | **CPU load anomaly on `<host>`**. Sustained normalized load exceeded the host baseline. | Facts: current load, normalized load, CPU count, baseline mean/stdev/sample count. Decision: **Is this expected workload or an unexplained process spike?** | 1. Inspect top processes and deployment activity. 2. Compare with traffic/job volume. 3. Mitigate runaway work or scale capacity if needed. | Evidence is the rolling-baseline transition. No automatic recovery until `host.cpu.normal`; avoid claiming a process because this event does not carry one. |
| `host.cpu.normal` | `load_norm_1min`, target, time | **CPU load returned to normal on `<host>`**. CPU returned to baseline after the configured normal-sample threshold. | Facts: current normalized load and time. Decision: **Is the incident resolved, or is the cause still unknown?** | 1. Confirm workload and process timeline. 2. Close the alert with cause or mark as transient. | Recovery pair for `host.cpu.anomaly`; do not repeat the full incident body. |
| `host.disk.critical` | `mount`, `used_pct`, `total`, `fs_type`, target, time | **Disk space critical on `<host>`**. A mount crossed the critical usage threshold. | Facts: mount, used %, capacity, filesystem. Decision: **Can space be safely reclaimed or must service capacity be expanded now?** | 1. Identify the mount and largest safe-to-remove consumers. 2. Protect logs/evidence and avoid deleting live data blindly. 3. Free space, expand, or fail over according to runbook. | Evidence is disk threshold transition. Recovery is `host.disk.recovered` after falling below the hysteresis threshold; no recovery claim before that event. |
| `host.disk.warn` | mount, used %, total, filesystem, target, time | **Disk space warning on `<host>`**. A mount crossed the warning threshold. | Facts: mount, used %, capacity. Decision: **Is growth expected and is there enough runway?** | 1. Check growth trend and retention. 2. Schedule cleanup/expansion before critical. | Evidence is threshold transition. Recovery is only the explicit recovered event; current event has no previous percentage or free bytes. |
| `host.disk.recovered` | mount, current `used_pct`, total, filesystem, target, time | **Disk space recovered on `<host>`**. The mount returned below the recovery threshold. | Facts: mount and current capacity. Decision: **Was space reclaimed safely and is recurrence controlled?** | 1. Verify the remediation and retention policy. 2. Close the warning/critical incident with cause. | Recovery for disk warn/critical. Current producer does not include prior state or reclaimed amount. |
| `host.memory.exhausted` | `used_pct`, `available_kb`, `total_kb`, target, time | **Memory pressure critical on `<host>`**. Memory usage crossed the exhaustion threshold. | Facts: used %, available, total. Decision: **Is a workload consuming memory or is capacity insufficient?** | 1. Inspect top processes/OOM history. 2. Reduce load/restart only under runbook. 3. Add capacity or fix leak. | Evidence is heartbeat transition. Add `used_kb` and top-process context if available; do not infer a process. Recovery is `host.memory.recovered`. |
| `host.memory.recovered` | `used_pct`, `available_kb`, target, time | **Memory pressure recovered on `<host>`**. Usage returned below the recovery threshold. | Facts: current used %, available, time. Decision: **Is the cause fixed or did pressure temporarily dip?** | 1. Confirm process/capacity cause. 2. Close only after verifying stable samples. | Recovery for memory exhaustion; no automatic root-cause claim. |
| `host.oom_kill` | `extra.kernel_message`, target, event time from OOM record, tags | **Process killed by the kernel on `<host>`**. The OOM killer terminated a process under memory pressure. | Facts: exact scrubbed kernel message, host, time. Decision: **What process was killed and was the memory pressure expected?** | 1. Parse/identify PID and process. 2. Correlate with memory pressure and deployment. 3. Restart/fix/scale according to service owner. | Evidence is the kernel message. Current adapter discards structured OOM fields and only retains `kernel_message`; add normalized `pid`, `process`, `command`, `uid`, `memory_used`, and `cgroup` when present. Recovery is manual or a later memory-recovered event, not automatic. |
| `host.collector.stalled` | `extra.collector`, target, time; heartbeat also has `collector_errors` but transition drops it | **Host telemetry collector stalled on `<host>`**. The named collector missed its expected reporting window. | Facts: collector name, host, detection time. Decision: **Is host visibility incomplete enough to trust current security conclusions?** | 1. Identify collector error/last success. 2. Repair agent permissions/dependencies. 3. Treat data from that collector as incomplete until recovered. | Evidence is projection set-difference. Add `last_success_at`, `age_seconds`, `expected_interval_seconds`, and `error` for an actionable message. Recovery is `host.collector.recovered`. |
| `host.collector.recovered` | `extra.collector`, target, time | **Host telemetry collector recovered on `<host>`**. The named collector resumed reporting. | Facts: collector and recovery time. Decision: **Is the recovered data complete, or is there a gap to document?** | 1. Confirm a successful collection. 2. Record the blind-spot interval and validate the first result. | Recovery for collector stalled. Add the blind-spot duration and last error if available. |
| `host.package_db.corrupted` | `lock_files`, `lock_count`, target, time | **Package database is blocked on `<host>`**. Stale RPM database locks were detected without a live RPM process. | Facts: lock paths/count, host, time. Decision: **Is package inventory unreliable or is a package operation currently active?** | 1. Confirm no package manager is running. 2. Preserve evidence and repair the package DB using the OS runbook. 3. Re-run inventory. | Evidence is RPM lock/process check. Recovery is `host.package_db.recovered`; do not tell the operator to delete locks blindly. |
| `host.package_db.recovered` | current extra is empty, target, time | **Package database recovered on `<host>`**. The package database became readable again. | Facts: host and recovery time only. Decision: **Did inventory complete after recovery?** | 1. Run/confirm package inventory. 2. Close the blind spot with the repair record. | Recovery for package DB corruption. Add `lock_files_cleared` or inventory result if available, but do not invent it. |
| `host.packages.changed` | `added` (max 50), `removed` (max 50), `added_count`, `removed_count`, target, time | **Installed packages changed on `<host>`**. The package set differs from the prior snapshot. | Facts: counts and bounded names. Decision: **Do changes match an approved package/deployment operation?** | 1. Match packages to change record and package manager logs. 2. Verify source/version/signature. 3. Remove/roll back unauthorized software. | Evidence is package-set diff. The producer does not include versions or actor; add those if the alert must support supply-chain triage. No recovery pair. |
| `host.process.first_seen` | `extra.comm`, target, time; current projection does not preserve process user/PID/args | **New process observed on `<host>`**. A process name not previously seen in the host snapshot appeared. | Facts: command name, host, time. Decision: **Is this process expected for this host and workload?** | 1. Identify PID/user/command line from the host at investigation time. 2. Validate package and parent. 3. Contain only if unauthorized. | Evidence is snapshot first-seen state. Add `pid`, `user`, scrubbed `args`, executable path, parent, and package/version; current code only emits `comm`. No automatic recovery. |

### Liveness and onboarding

| Event | Exact emitted fields; omit when absent | Headline / What happened | Facts / Decision | Ordered next steps | Evidence / Recovery |
|---|---|---|---|---|---|
| `host.agent.stale` | `instance_id`, `last_seen`, `age_seconds`, target name/id, account/region, time | **EC2 host agent stopped reporting**. No heartbeat arrived within the stale window. | Facts: host, last seen, age, account/region. Decision: **Is the host down, the agent broken, or the path to BlackWatch blocked?** | 1. Check instance health and agent process. 2. Check SQS/network/IAM delivery. 3. Restore telemetry and assess the blind-spot interval. | Evidence is host-status staleness, not an inferred host outage. Recovery is `host.agent.recovered`; do not say the host is healthy merely because the agent returns. |
| `host.agent.recovered` | derived `instance_id`, `display_name`, `hostname`, target, time; current extra has no explicit blind-spot duration | **EC2 host agent recovered**. A previously stale host sent a heartbeat again. | Facts: host and recovery time. Decision: **Is telemetry complete after the gap?** | 1. Record outage/blind-spot duration. 2. Check agent logs and queued events. 3. Validate the first post-recovery snapshot. | Recovery for agent stale. Add `stale_since`, `gap_seconds`, and `agent_version` to make recovery actionable. |
| `host.first_seen` | derived `instance_id`, `display_name`, `hostname`, target, account/region, time | **EC2 host observed for the first time**. BlackWatch created the host status record. | Facts: instance, friendly name, account/region, first observation time. Decision: **Is this host expected in the monitored fleet?** | 1. Confirm inventory/ownership. 2. Verify agent identity/tags and expected collectors. 3. Assign owner and monitoring policy. | Evidence is first projection observation. No recovery pair; manual onboarding/approval. |

## Producer-only and catalog-gap events

These events are emitted or referenced by the host pipeline but are absent from the `ec2.host` notification catalog. They must be explicitly classified; they must not inherit generic module text silently.

| Event | Classification | Recommendation |
|---|---|---|
| `host.service.health` | Input/control, emitted every heartbeat | UI/read-model only. Never notify per heartbeat. Its facts feed CPU, memory, collector, FIM coverage, and performance evaluation. |
| `host.state.snapshot` | Input/control, emitted when snapshots are shipped | UI/projection only. Do not notify on a normal snapshot. |
| `host.state.snapshot.rejected` | Actionable data-integrity/visibility alert | Add catalog entry. Show `reason`, `size_bytes`, `cap_bytes`, host, and time. Decision: **Is the host still sufficiently monitored?** Next steps: reduce payload/collector volume, verify the next accepted snapshot, and investigate the blind spot. Manual resolution; no recovery event exists today. |
| `host.sudo.exec` | Actionable security event | Add catalog entry with command-specific content. Add `tty`, `pwd`, and target user if the producer can safely normalize them. |
| `host.port.closed` | Operational/security transition | Add catalog entry or explicitly classify as non-notifying. Notify only for protected/expected ports or rules; show protocol/address/port. |
| `host.user.removed` | Identity transition | Add catalog entry. Manual approval/reconciliation; show username only. |
| `host.authorized_key.removed` | Persistence transition | Add catalog entry. Show user/fingerprint; manual reconciliation. |
| `host.service.removed` | Runtime transition | Add catalog entry or rule-gate to important units; show unit. |
| `host.suid.removed` | Security transition | Add catalog entry. Show path; distinguish expected hardening from service breakage. |
| `host.perf.alert` | Actionable synthetic alert | Add catalog entry. Use metric-specific inner content: CPU explains baseline/window; memory explains pressure/window; disk explains mount/worst mount. Use `extra.message` as evidence, not as the whole notification. |

The documentation also mentions `host.cron.added` and `host.cron.removed`, but the current `hosts/diff.py` emits the normalized action `host.cron.changed` with `extra.change`. Treat the documented names as stale aliases unless a producer emits them elsewhere; add a parity test so the mismatch cannot return.

## Recommended module-specific renderer contract

The EC2 renderer should select content by exact `event.action`, then use these fixed inner rules:

- Access events lead with identity and source.
- Persistence/configuration events lead with the changed object and before/after data where actually emitted.
- FIM events lead with path, detection method, and actor when available.
- Resource alerts lead with metric, threshold, current value, and duration/baseline.
- Telemetry alerts lead with the blind spot and what cannot currently be trusted.
- Recovery events lead with what recovered and explicitly state that root cause is not known unless evidence says so.

The renderer must never substitute generic phrases such as “impact depends on the affected resource,” “review the evidence,” or “recovery is reported when available” when this matrix has a more precise sentence.

## Representative fixtures

Fixtures must be stored with the future implementation, not embedded as production defaults. These are the minimum complete/partial cases for this review.

### Complete SSH failure

```json
{
  "source": {"module": "ec2.host", "account": "095899260107", "region": "us-west-1"},
  "event_time": "2026-08-25T04:06:21.424277Z",
  "action": "host.auth.ssh.failure",
  "outcome": "failure",
  "target": {"id": "i-0abc", "type": "ec2.instance", "name": "web-01"},
  "actor": {"principal": "admin", "source_ip": "9.9.9.9"},
  "extra": {"method": "password", "tags": {"env": "prod"}}
}
```

Expected decision: determine whether `admin` from `9.9.9.9` was expected. Expected facts must not include a command, SSH port, or key fingerprint because the normalized event does not emit them.

### Partial SSH failure

```json
{
  "action": "host.auth.ssh.failure",
  "event_time": "2026-08-25T04:06:21Z",
  "target": {"id": "i-0abc", "type": "ec2.instance"},
  "actor": {"principal": null, "source_ip": null},
  "extra": {"reason": "invalid_user"}
}
```

Expected output omits user, IP, hostname, method, and any invented account identity. It says only that an invalid-user SSH authentication failure was observed on the identified instance at the supplied time.

### Complete FIM change

```json
{
  "action": "host.fim.modified",
  "event_time": "2026-08-25T04:06:21Z",
  "target": {"id": "i-0abc", "name": "web-01"},
  "actor": {"principal": "tee uid=0"},
  "extra": {
    "path": "/etc/sudoers.d/deploy",
    "change_type": "modified",
    "sha256_before": "7dd5d071...",
    "sha256_after": "998699d9...",
    "perm_before": 420,
    "perm_after": 420,
    "owner_before": "0:0",
    "owner_after": "0:0",
    "detection": "auditd",
    "actor": {"uid": 0, "pid": 8377, "comm": "tee", "exe": "/usr/bin/tee", "proctitle": "tee -a /etc/sudoers.d/deploy"}
  }
}
```

Expected decision: validate whether the exact sudoers change and actor were approved. The renderer should show the changed path and hashes, but should not claim the resulting privilege unless the file diff is available.

### Partial FIM change

```json
{
  "action": "host.fim.deleted",
  "target": {"id": "i-0abc"},
  "extra": {"path": "/etc/cron.d/job", "change_type": "deleted", "detection": "baseline"}
}
```

Expected output contains path, change type, detection, instance ID, and event time if present. It omits hashes, actor, owner, and hostname.

### Complete CPU performance alert

```json
{
  "action": "host.perf.alert",
  "target": {"id": "i-0abc", "name": "web-01"},
  "severity": "high",
  "extra": {
    "metric": "cpu_utilization_pct",
    "metric_label": "CPU utilization",
    "threshold": 80,
    "comparison": "gte",
    "current_value": 98.0,
    "window_seconds": 300,
    "min_breach_ratio": 0.6,
    "rule_name": "Web CPU above 80% for 5 minutes",
    "message": "CPU utilization ≥ 80% for 5m (current: 98.0%)"
  }
}
```

Expected decision: identify whether the sustained load is expected workload, a runaway process, or capacity pressure. Do not claim the process name because this event does not emit one.

### Partial telemetry failure

```json
{
  "action": "host.collector.stalled",
  "target": {"id": "i-0abc"},
  "extra": {"collector": "packages"}
}
```

Expected output says package inventory is stale/incomplete and names the collector. It must not claim the host is compromised or that packages changed.

## Test plan / acceptance evidence

The existing `tests/test_ec2_host.py` verifies many producer transitions, but it does not prove notification content. BW-015 should add golden tests without changing delivery routes, saved profiles, throttles, silence settings, or database behavior.

### Producer and parity tests

- Assert all adapter actions from `ec2_host.py`: heartbeat, accepted SSH, failed SSH, password SSH, sudo success, sudo failure, OOM, FIM changes, FIM coverage, and rejected snapshot.
- Assert every `diff_snapshots()` transition: port open/closed, user add/remove, key add/remove, sudoers, critical file, cron, service add/remove, SUID add/remove, packages, kernel module add/remove, disk warn/critical/recovered.
- Assert projection transitions: first seen, agent recovered, CPU anomaly/normal, memory exhausted/recovered, RPM DB corrupted/recovered, collector stalled/recovered, process first seen.
- Assert correlation transitions: brute force per source IP and per principal, including count/window/threshold/dimension.
- Add a producer/catalog parity test that classifies every emitted action as `catalogued`, `control-ui-only`, or `explicitly non-notifying`; fail on an unclassified `host.*` action.
- Add an alias test for the documentation mismatch: only `host.cron.changed` is accepted from `diff_snapshots()` unless a future producer deliberately adds the other names.

### Notification golden tests

For each event row in this document, render:

1. complete fixture to email/plain text;
2. the same fixture to one chat channel;
3. partial fixture with all absent-field branches;
4. recovery fixture for agent, CPU, disk, memory, collector, and package DB pairs;
5. one custom advanced template to prove it remains authoritative.

Assertions should check exact labels/order, no generic filler, no `unknown` placeholders, no raw unsanitized journal secrets, and no facts that are not in the normalized event.

### Required additive fields before full rollout

- `decision` content slot in the profile contract.
- Sudo failure: `reason`, `tty`, `target_user`, and safe command context where present.
- OOM: parsed `pid`, process name, command/cgroup, and memory context where present.
- Process first seen: `pid`, user, scrubbed args, executable, parent, package/version where present.
- Collector recovery/stall: last success, age, expected interval, and last error.
- Agent recovery: stale start and blind-spot duration.
- Critical file/cron/sudoers diff: before/after hashes and actor linkage where available.
- Disk/memory recovery: previous/current values and safe capacity context.
- Package changes: versions and package-manager transaction identity where available.

## Rollout decision

BW-015 should remain in review until:

1. producer-only events are classified in the catalog;
2. the decision slot is added additively;
3. event-specific preview fixtures replace the generic EC2 sample;
4. complete/partial email and chat golden tests pass for every row; and
5. the parity test proves no new `host.*` producer action can silently inherit generic notification content.

The highest-priority first implementation slice is SSH failure/success, brute-force, sudo failure/exec, authorized-key changes, and FIM changes. These are the events most likely to require an immediate human security decision. Resource and telemetry recovery pairs should follow in the same module rollout before EC2 is marked complete.
