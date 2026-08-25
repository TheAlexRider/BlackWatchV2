# BW-016 — RDS notification content review

Status: reviewed

This review covers the RDS notification surface across PostgreSQL logs, RDS
Proxy logs, stateful projections/staleness, and AWS CloudTrail control-plane
events. It preserves the shared outer notification shape while defining a
different inner contract for every event kind.

## Review conclusion

RDS is not one notification family. It contains at least six operator
decisions:

1. Was a database authentication attempt expected?
2. Is an existing session anomalous, abandoned, or being shared?
3. Is the RDS Proxy itself exposing a new client or failing to reach the
   backend?
4. Did a query change data, schema, permissions, or execute a sensitive
   function?
5. Is the engine reporting an operational failure that needs DBA action?
6. Did an AWS control-plane action change availability, exposure, recovery, or
   security configuration?

The outer structure should remain:

```text
[short event-specific headline]
What happened: [one precise sentence]
Facts: [only the fields needed to decide]
Decision: [the first question the recipient must answer]
Next steps: [ordered action, containment, or owner handoff]
Evidence: [traceable source/message/query/event identifier]
Recovery: [matching recovery condition, or manual resolution]
```

Do not render generic `Impact depends...`, `Review the evidence...`, or
`matching recovery event...` sections when the producer does not provide those
facts. Omit unavailable values and omit the entire optional line. A notification
must never invent a user, source IP, database name, threshold, query text,
recovery event, or owner.

## Producer inventory and actual normalized fields

### PostgreSQL log adapter: `blackwatch/modules/aws_rds.py`

Every emitted adapter event has these normalized values when available:

```text
source.module       = aws.rds
source.transport    = queue or the connector transport
event_time          = SQS event timestamp
action              = event-specific rds.* action
outcome             = success or failure
actor.principal     = database user when the log line identifies one
actor.source_ip     = parsed client/remote IP when present
target.id/name      = db_instance
target.type         = rds.db
extra.db_instance
extra.source_type   = postgres or rds_proxy
extra.user
extra.database
extra.source_ip
extra.source_port
extra.tags           = env, db_instance, source
```

The adapter suppresses session start/end events for AWS system users.
Authentication failures for those users are retained.

PostgreSQL-specific extras:

```text
rds.session.start  -> backend_pid, session_key, optional real_client_ip,
                      real_client_port, proxy_ip, proxy_port, session_id
rds.session.end    -> backend_pid, duration_seconds, host, session_id
rds.auth.failure   -> reason (invalid_password or no_pg_hba_entry), backend_pid
rds.query.*        -> backend_pid, audit_class, command, statement (max 500
                      chars), scope, session_id
rds.error           -> severity (FATAL or PANIC), message (max 500 chars)
```

The pgaudit parser reads object type and object name positions but currently
does not emit them. That is a material notification gap for DDL and role
events: `ALTER TABLE` without the table name is not sufficiently actionable.

RDS Proxy-specific extras:

```text
rds.proxy.client.connect      -> proxy_endpoint, client_connection,
                                 source_ip/source_port
rds.proxy.client.disconnect   -> proxy_endpoint, client_connection,
                                 optional cached source_ip/source_port
rds.auth.failure              -> reason=invalid_credentials,
                                 proxy_endpoint, client_connection, optional
                                 cached source_ip/source_port, message
rds.proxy.backend_hba_reject  -> reason=backend_hba_missing, db_connection,
                                 database, service-account user, proxy ENI IP,
                                 message
rds.proxy.misconfig            -> reason=multiple_auth_entries, database user,
                                 message
```

The proxy correlation cache is best-effort. A missing cached IP must be shown
as “source IP unavailable from the proxy log”, not as an invented source.

### Stateful RDS projection and staleness

`blackwatch/rds/projection.py` and `blackwatch/rds/staleness.py` emit derived
events with these fields:

```text
rds.auth.burst             -> db_instance, user, failure_count,
                              window_minutes, source_ips, message
rds.session.concurrent     -> db_instance, user, source_ips, message
rds.proxy.source.new       -> db_instance, source_ip, message
rds.session.new_source     -> db_instance, user, source_ip, message
rds.user.unknown           -> db_instance, user, trigger, message
rds.session.long_idle      -> db_instance, user, database, source_ip,
                              session_id, idle_hours, connected_at, message
```

Derived events do not currently include every comparison detail needed for a
perfect explanation: previous source set, active-session count, exact failure
timestamps, allowlist version, backend PID, or proxy endpoint. Those should be
additive producer fields, not values reconstructed by notification rendering.

### CloudTrail RDS control-plane events

`blackwatch/modules/aws_cloudtrail.py` maps these RDS operations:

```text
rds.instance.create, rds.instance.delete, rds.instance.modify,
rds.instance.reboot, rds.instance.start, rds.instance.stop,
rds.instance.restore, rds.instance.restore_pit,
rds.snapshot.create, rds.snapshot.delete, rds.snapshot.modify,
rds.snapshot.copy,
rds.parameter_group.create, rds.parameter_group.delete,
rds.parameter_group.modify, rds.parameter_group.reset,
rds.subnet_group.modify,
rds.cluster.create, rds.cluster.delete, rds.cluster.modify,
rds.cluster_snapshot.modify
```

The common CloudTrail envelope exposes actor, source IP, user agent, account,
region, event time, event name/source, error fields, and a target ID selected
from RDS request parameters. RDS-specific extras currently include:

```text
rds_publicly_accessible
rds_backups_disabled
rds_deletion_protection_off
rds_master_password_change
rds_iam_auth_disabled
rds_unencrypted_at_creation
rds_snapshot_made_public
rds_snapshot_cross_account_share
rds_security_params_changed
extra.message for some public/backups/deletion-protection/password/snapshot flags
```

The full request parameters are retained in `event.raw`, but notification code
must not parse raw payloads. Add named normalized change fields before claiming
complete lifecycle coverage.

## Event-by-event message matrix

The following matrix is the content contract. “Omit” means the field is not
printed when absent; it does not mean a placeholder should be printed.

The common body labels remain `What happened`, `Facts`, `Decision`, `Next
steps`, `Evidence`, and `Recovery`. Only the inner wording and selected facts
change per event.

### Authentication and identity anomalies

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.auth.failure` | `RDS login failed · {user or account unavailable}`. A database login attempt failed on `{db_instance}`. | User if present; source IP/port if present; database; reason (`invalid password` or `pg_hba entry missing`); source type; time; proxy endpoint if present. | Was this an expected retry, a broken client, or an unauthorized access attempt? | 1. Confirm user and source with the owner. 2. If unexpected, inspect nearby failures and rotate/disable credentials under the DB runbook. 3. If `no_pg_hba_entry`, route to the DBA/network owner instead of treating it as a password incident. | No automatic recovery from one successful login. Close manually after the attempt is explained or credentials/network policy are corrected. |
| `rds.auth.burst` | `RDS authentication burst · {user}`. At least `{failure_count}` database logins for `{user}` failed within `{window_minutes}` minutes. | User; database; failure count; window; distinct source IPs; current source IP if present; latest time; source type if retained. | Brute force, credential stuffing, or a legitimate service retry loop? | 1. Verify the user and all source IPs. 2. Check deployment/secret rotation. 3. If unauthorized, contain the source and rotate/disable the credential. 4. Preserve the failure window. | No success-based closure. Resolve when the owner confirms cause and the retry/attack stops; a quiet-period detector may be added later. |
| `rds.user.unknown` | `Unknown RDS user attempted access · {user or unavailable}`. A database authentication event used a username not on the configured allowlist. | User; database; source IP if present; triggering event; time; source type; allowlist decision. | Expected newly provisioned/service user, stale credential, or unauthorized account? | 1. Check allowlist and change ticket. 2. Confirm whether the user should exist. 3. If not expected, disable/remove the DB user and rotate dependent secrets. 4. Add the user only after ownership is confirmed. | Manual resolution after the allowlist and database account are corrected. A later successful login is not recovery. |

### Session lifecycle and session anomalies

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.session.start` | `RDS session started · {user}`. A database session was established on `{db_instance}`. | User; database; client/source IP/port; real client IP if proxy correlation succeeded; session ID; backend PID; time; source type. | Is this session expected and is the source attributable? | 1. Verify owner/source for unfamiliar sessions. 2. Check deployment, pool, or maintenance activity. 3. If suspicious, terminate the session and investigate the credential. | Pair with `rds.session.end` using `session_id`. Informational by itself. |
| `rds.session.end` | `RDS session ended · {user}`. A database session ended on `{db_instance}`. | User; database; source IP; session ID; backend PID; duration; log host; time. | Did the session end normally, and was its duration consistent with the workload? | 1. Compare duration with expected pool/query behavior. 2. Link it to the start event when investigating. 3. Escalate only if duration/disconnect behavior is abnormal. | This closes the matching `rds.session.start` when the same `session_id` is present. It does not close auth or query alerts. |
| `rds.session.concurrent` | `RDS user connected from multiple IPs · {user}`. The same database user is active from multiple source IPs at the same time. | User; database; all observed source IPs; current source IP; event time; count if added; source type if available. | Normal pool/multi-device use or credential sharing/theft? | 1. Identify each source owner/network. 2. Compare with app pool topology and deployment timing. 3. If unexplained, terminate unauthorized sessions and rotate the credential. | Manual resolution after the extra source is explained or removed. A session end is evidence, not guaranteed closure. |
| `rds.session.new_source` | `New source for RDS user · {user}`. A known user authenticated from a source IP never previously associated with that user. | User; new source IP; database; proxy correlation state; time; source type; prior-known status. | New legitimate workstation/pod/VPN address or stolen credential? | 1. Confirm source owner/change window. 2. Compare network/VPN context. 3. If unexpected, terminate the session and rotate the user credential. | Manual resolution after confirmation or containment. A later session from the same IP is not recovery. |
| `rds.session.long_idle` | `RDS session idle for {idle_hours}h · {user}`. A database session remained open without a disconnect for `{idle_hours}` hours. | User; database; source IP; session ID; connected-at time; idle age; DB instance; backend PID if added. | Forgotten operator session, leaked credential, or broken connection pool? | 1. Identify owner/workload. 2. Check active queries/locks and pool health. 3. Terminate only after confirming it is safe. 4. Investigate credential exposure if ownership is unclear. | A matching disconnect/closed-session state should close it. Until `rds.session.end` or explicit operator action, keep it open. |

### RDS Proxy events

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.proxy.client.connect` | `RDS Proxy client connected · {source IP}`. A client opened a connection to the RDS Proxy. | Real client IP/port if present; proxy endpoint; client connection ID; DB instance; time. Omit user because the producer does not know it. | Is this source expected to use the proxy? | 1. Confirm source belongs to an expected app, pod, VPN, or operator. 2. Correlate with auth/session events if attribution is needed. 3. Investigate/restrict an unknown source. | Pair with `rds.proxy.client.disconnect` by client connection ID when available. Informational unless a detector escalates it. |
| `rds.proxy.client.disconnect` | `RDS Proxy client disconnected · {source IP or source unavailable}`. A client connection to the RDS Proxy closed. | Source IP/port if cache still has it; proxy endpoint; client connection ID; time. | Normal close, client failure, or lost proxy correlation? | 1. Correlate with connect/auth events. 2. Investigate only if the close follows errors or abnormal churn. | Closes the matching proxy client transition. It does not close auth, HBA, or new-source alerts. |
| `rds.proxy.source.new` | `New source connected to RDS Proxy · {source IP}`. A source IP never seen before opened a connection to the proxy. | New source IP; DB instance; proxy endpoint if added; first-seen time; event time; source port if present. | New legitimate infrastructure or unfamiliar access path? | 1. Identify source owner/network. 2. Compare deployment/VPN/pod changes. 3. If unexpected, restrict the source and investigate credentials. | Manual resolution after source ownership is confirmed or access is contained. A later connection is not recovery. |
| `rds.proxy.backend_hba_reject` | `RDS Proxy cannot reach PostgreSQL · pg_hba reject`. The backend rejected the proxy service connection because its host-based access rule did not allow the proxy ENI. | DB instance; database; proxy ENI IP; proxy service-account user; DB connection ID if present; reason; exact log message; time. | Planned pg_hba change or production connectivity outage? | 1. Route to DBA/database-network owner. 2. Verify proxy ENI IPs and backend access policy. 3. Apply the smallest approved allow rule. 4. Test a connection and watch for recovery. | Manual resolution after a test connection succeeds and the owner confirms the policy. No automatic recovery is currently emitted. |
| `rds.proxy.misconfig` | `RDS Proxy credential mapping conflict · {user}`. The proxy found multiple authentication entries for the same database user. | Database user; proxy identity/endpoint if available; reason `multiple_auth_entries`; exact message; DB instance; time. | Which secret mapping is authoritative, and is access blocked? | 1. Inspect proxy authentication entries. 2. Identify duplicate secrets and owner. 3. Remove the unintended mapping/correct configuration. 4. Test authentication. | Manual resolution after the duplicate mapping is corrected and a test login succeeds. |

### Query/audit events

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.query.ddl` | `RDS schema change · {command}`. A pgaudit DDL statement ran against `{database}`. | DB instance/database; user; source IP; command; object type/name; statement, redacted/truncated; session ID/backend PID; scope; time. | Approved migration or unauthorized/destructive schema change? | 1. Compare statement/object with change ticket. 2. Check whether it is destructive/security-sensitive. 3. If unexpected, preserve evidence and follow rollback/containment runbook. | Manual resolution after migration is explained and rollback/data-integrity review completes. |
| `rds.query.role` | `RDS permission change · {command}`. A pgaudit role/permission statement changed database access. | User; database; command; affected role/object; statement; source IP; session ID/backend PID; time. | Approved access-management change or persistence/privilege escalation? | 1. Identify grantor and affected principal. 2. Compare with approval. 3. Revoke/rollback unapproved access and rotate credentials if needed. 4. Review subsequent role use. | Manual resolution after access is corrected and resulting permissions are confirmed. |
| `rds.query.read` | `RDS read query observed · {user}`. A pgaudit read statement ran against `{database}`. | User; database; command; statement if policy allows; object type/name; source IP; session ID/backend PID; scope; time. | Expected workload, diagnostic query, or sensitive/bulk read? | 1. Compare actor/query with workload and ticket. 2. If sensitive access is suspected, preserve evidence and investigate the session. 3. Escalate only when data policy requires it. | Manual review; no automatic recovery. |
| `rds.query.write` | `RDS write query observed · {user}`. A pgaudit write statement changed database data. | User; database; command; statement; object type/name; source IP; session ID/backend PID; time. | Expected application write, migration, or unauthorized data change? | 1. Identify application/change owner. 2. Check affected object and transaction context. 3. Preserve evidence and follow data-integrity/rollback runbook if unexpected. | Manual resolution after the change is validated or reverted. |
| `rds.query.function` | `RDS function executed · {function if available}`. A monitored database function was executed. | User; database; function/object name; command; statement; source IP; session ID/backend PID; time. | Expected application function or privileged/security-definer execution? | 1. Verify function and caller. 2. Check whether it can modify data, permissions, or external state. 3. Review adjacent queries if unexpected. | Manual review; no automatic recovery. |
| `rds.query.misc` | `RDS audited query · {command or class}`. A pgaudit statement outside specialized query classes was observed. | User; database; audit class; command; statement; object type/name; source IP; session ID/backend PID; time. | Does this statement represent a relevant security or operational change? | 1. Identify the statement and owner. 2. Classify it as read/write/role/DDL/function if parser missed the class. 3. Add a dedicated rule only if meaningful. | Manual review; no automatic recovery. |

The query matrix requires additive `object_type` and `object_name` producer
fields. If statement text is truncated or unavailable, show command/class and
evidence source rather than pretending the object is known.

### Engine errors

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.error` | `RDS engine error · {severity}`. PostgreSQL emitted a `{FATAL/PANIC}` error on `{db_instance}`. | Engine severity; exact message; database/user if present; source IP; backend PID; event time; source log/stream. | Transient connection failure, resource exhaustion, corruption, or security-relevant engine condition? | 1. Check exact error and DB health. 2. Correlate with deploys, storage, locks, and connection failures. 3. Route to DBA/on-call; preserve message and event ID. 4. Apply recovery only through the approved DBA runbook. | Manual resolution or separately observed healthy engine condition. Current producer emits no typed `rds.error.recovered`. |

### RDS lifecycle and security configuration events

These are CloudTrail events, not PostgreSQL log events. They require actor,
account, region, target, event name, and the exact change signal. A generic
“database configuration changed” message is insufficient.

| Event | Short headline / What happened | Facts to show, in order | Decision | Ordered next steps | Recovery / closure |
|---|---|---|---|---|---|
| `rds.instance.create` | `RDS instance created · {target}`; specialize to public, unencrypted, or IAM-auth-disabled when flags exist. | Actor/account/region; instance ID; engine/cluster if normalized; public/encryption/IAM-auth flags; backups/deletion protection; time; event name. | Approved provision or insecure creation? | 1. Verify owner/ticket. 2. Check exposure, encryption, backups, deletion protection, and IAM auth. 3. Remediate insecure settings before production use. | Manual resolution after approval and control verification. |
| `rds.instance.delete` | `RDS instance deleted · {target}`. An RDS instance was deleted. | Actor/account/region; instance ID; deletion-protection state if known; final-backup/snapshot setting if available; time; event ID. | Approved decommission or destructive action? | 1. Confirm owner immediately. 2. Verify final snapshot/recovery point. 3. Invoke recovery/data-protection runbook if unapproved. | Manual resolution after decommission or recovery investigation. |
| `rds.instance.modify` | `RDS instance security setting changed · {target}`; specialize public access, backups, deletion protection, master password, IAM auth, or ordinary modification. | Actor/account/region; instance ID; exact changed setting(s); before/after values when available; time; event ID. | Approved maintenance or security/availability regression? | 1. Identify changed control and owner. 2. Compare with change window. 3. Restore safe value if unapproved. 4. Verify connectivity/protection. | Manual resolution after intended setting and verification are confirmed. |
| `rds.instance.reboot` | `RDS instance reboot requested · {target}`. An operator requested an RDS instance reboot. | Actor/account/region; instance ID; force/failover flag if present; time; reason if available. | Planned maintenance/failover or unexpected availability action? | 1. Confirm maintenance window. 2. Check application impact/failover. 3. Verify healthy state after reboot. | Close after healthy state and owner confirmation. |
| `rds.instance.start` | `RDS instance started · {target}`. An RDS instance was started. | Actor/account/region; instance ID; prior state if available; time. | Expected schedule/recovery or unauthorized availability change? | 1. Verify owner/schedule. 2. Check cost/exposure concerns. 3. Confirm healthy state. | Manual healthy-state confirmation. |
| `rds.instance.stop` | `RDS instance stopped · {target}`. An RDS instance was stopped. | Actor/account/region; instance ID; prior state; time. | Planned shutdown or service-impacting action? | 1. Confirm owner/window. 2. Check application dependencies/outage impact. 3. Start/restore only under approved runbook. | Manual resolution after intentional stop or restoration is confirmed. |
| `rds.instance.restore` | `RDS instance restored from snapshot · {target}`. An instance was restored from a snapshot. | Actor/account/region; new instance ID; source snapshot ID; engine/region; encryption/network settings; time. | Approved recovery/test copy or unexpected data duplication? | 1. Verify source/destination. 2. Check access controls, encryption, public exposure, and secrets. 3. Confirm owner and cleanup plan. | Manual resolution after copy is approved and secured/decommissioned. |
| `rds.instance.restore_pit` | `RDS instance restored to point in time · {target}`. An instance was restored to a point in time. | Actor/account/region; new instance ID; source instance; restore timestamp; network/security settings; time. | Approved recovery or unauthorized data copy? | 1. Verify ticket and recovery timestamp. 2. Check access/encryption. 3. Confirm owner and disposition. | Manual resolution after recovery validation and copy disposition. |
| `rds.snapshot.create` | `RDS snapshot created · {target}`. A database snapshot was created. | Actor/account/region; snapshot ID; source DB/cluster; encryption/region; time. | Approved backup/recovery action or untracked data copy? | 1. Verify actor/backup policy. 2. Check sharing/encryption/retention. 3. Confirm snapshot owner. | Manual review; retention or explicit deletion is not automatic recovery. |
| `rds.snapshot.delete` | `RDS snapshot deleted · {target}`. A database snapshot was deleted. | Actor/account/region; snapshot ID; source DB; remaining recovery coverage if available; time. | Approved cleanup or loss of recovery capability? | 1. Verify owner/exception. 2. Check remaining recovery points. 3. Invoke recovery runbook if unapproved. | Manual resolution after deletion is explained or coverage restored. |
| `rds.snapshot.modify` | `RDS snapshot sharing changed · {target}`; specialize public or cross-account when flags exist. | Actor/account/region; snapshot ID; public flag; destination account IDs; attribute name; time; event ID. | Approved sharing or data-exposure event? | 1. Identify recipients/`all`. 2. Confirm approval/data classification. 3. Remove unintended sharing and audit restores/access. | Manual resolution after sharing and exposure review. |
| `rds.snapshot.copy` | `RDS snapshot copied · {target}`. A database snapshot was copied. | Actor/account/region; source snapshot; destination snapshot/region/account; encryption/KMS key; time. | Approved backup/region copy or unauthorized data movement? | 1. Verify destination owner/account/region. 2. Check encryption/sharing. 3. Confirm retention/cleanup. | Manual resolution after ownership and security are confirmed. |
| `rds.parameter_group.create` | `RDS parameter group created · {target}`. A database parameter group was created. | Actor/account/region; group name/family/engine; security parameters if available; time. | Approved configuration rollout or preparation to weaken controls? | 1. Verify owner/family. 2. Review security parameters before attachment. 3. Record approved change. | Manual review; no automatic recovery. |
| `rds.parameter_group.delete` | `RDS parameter group deleted · {target}`. A database parameter group was deleted. | Actor/account/region; group name; attached instances if available; time. | Approved cleanup or configuration loss? | 1. Confirm no production resource depends on it. 2. Verify replacement group. 3. Restore/recreate only under change control. | Manual resolution after dependencies are verified. |
| `rds.parameter_group.modify` | `RDS security parameter changed · {target}`. Security-relevant database parameters changed. | Actor/account/region; parameter group; names in `rds_security_params_changed`; before/after values if added; engine/family; time. | Did the change strengthen or weaken TLS, logging, or audit coverage? | 1. Inspect each parameter/effective apply status. 2. Compare with approved change. 3. Restore secure values if unexpected. 4. Verify TLS/logging behavior. | Manual resolution after effective values and monitoring are verified. |
| `rds.parameter_group.reset` | `RDS parameter group reset · {target}`. Database parameters were reset to defaults. | Actor/account/region; group; parameter names if available; attached resources; time. | Was the reset approved, and did it remove security controls? | 1. Compare reset set with secure baseline. 2. Restore required controls. 3. Verify effective configuration/logging. | Manual resolution after baseline verification. |
| `rds.subnet_group.modify` | `RDS subnet group changed · {target}`. The network placement set for an RDS resource changed. | Actor/account/region; subnet group; added/removed subnet IDs; VPC; actor/time; before/after if added. | Approved network change or new exposure/availability path? | 1. Verify subnets/VPC/routes/security groups. 2. Check public/private placement/dependencies. 3. Validate connectivity. | Manual resolution after network path is approved and healthy. |
| `rds.cluster.create` / `rds.cluster.modify` | `RDS cluster created/changed · {target}`; specialize public, backups, deletion protection, encryption, or IAM-auth flags. | Actor/account/region; cluster ID; members; exact security flags; engine; time. | Approved cluster lifecycle or security regression? | 1. Verify owner/change. 2. Review exposure, encryption, backups, deletion protection, auth. 3. Check member health. | Manual resolution after configuration and member health are confirmed. |
| `rds.cluster.delete` | `RDS cluster deleted · {target}`. An RDS cluster was deleted. | Actor/account/region; cluster ID; final snapshot/recovery point if available; members; time. | Approved decommission or destructive action? | 1. Confirm owner immediately. 2. Verify final snapshot/recovery. 3. Invoke recovery runbook if unapproved. | Manual resolution only. |
| `rds.cluster_snapshot.modify` | `RDS cluster snapshot sharing changed · {target}`; specialize public/cross-account. | Actor/account/region; cluster snapshot ID; `all` or destination accounts; attribute; time. | Approved data sharing or exposure? | 1. Verify recipients/data classification. 2. Remove unintended sharing. 3. Audit restores/access. | Manual resolution after access/exposure review. |
| `rds.instance.state` | `RDS instance state changed · {target}`. The inventory/posture collector observed a state transition. | Instance ID; previous/current state; account/region; observation time; collector/source; age since last observation. | Real resource state change or stale/incomplete inventory? | 1. Confirm directly against AWS/RDS. 2. Check dependent-service impact. 3. Investigate collector freshness if uncertain. | Close when a fresh matching state is observed and owner confirms transition. |

## Missing catalog and producer gaps

The current notification catalog in `blackwatch/notify/profiles.py` contains
only a subset of the RDS producer actions. These are producer/catalog gaps and
must be made explicit before BW-016 is marked rolled out:

### Missing from the RDS catalog

```text
rds.query.read
rds.query.write
rds.query.misc
rds.instance.reboot
rds.instance.start
rds.instance.stop
rds.instance.restore
rds.instance.restore_pit
rds.snapshot.create
rds.snapshot.delete
rds.snapshot.copy
rds.parameter_group.create
rds.parameter_group.delete
rds.parameter_group.reset
rds.subnet_group.modify
rds.cluster.create
rds.cluster.delete
rds.cluster.modify
rds.cluster_snapshot.modify
rds.instance.state
```

`rds.instance.state` comes from the RDS posture/inventory connector rather than
the CloudTrail adapter. It must not be silently treated as the same event as
`rds.instance.modify`.

### Fields that should be added additively

1. PostgreSQL pgaudit: `object_type`, `object_name`, and a safe statement
   preview/redaction marker. Keep the existing 500-character statement field.
2. Projection alerts: `previous_source_ips`, `active_session_count`, exact
   `failure_times` or first/last failure time, and `allowlist_version` where
   applicable.
3. Proxy alerts: `proxy_endpoint` on backend-HBA/misconfiguration events,
   `client_connection` where available, and a correlation status such as
   `source_ip_resolution=correlated|unavailable`.
4. CloudTrail RDS events: a typed `rds_change_summary` containing changed
   setting, before/after value where available, resource ARN/name, request ID,
   and a redacted request summary. Notification code must not parse `event.raw`.
5. CloudTrail lifecycle: source snapshot, source instance, destination
   account/region, final snapshot setting, and effective apply status where
   AWS provides them.
6. Recovery/correlation: `recovery_of_event_id` or an equivalent explicit
   correlation field for events that genuinely close an earlier condition.

### Semantics that need correction

- `rds.auth.failure` is cataloged at high severity but the current rule marks a
  single failure low. Content must display assessed severity and not infer
  threat level from the event label.
- `rds.proxy.client.connect` and `disconnect` are informational transitions;
  they should not use incident language unless a detector escalates them.
- Module rollout metadata can mark RDS events rolled out through shared prose.
  BW-016 should set event-level readiness only after each event has its own
  contract and fixture.
- CloudTrail `rds.instance.modify` has multiple meanings. Public access,
  backup disablement, deletion-protection removal, password change, IAM-auth
  disablement, and ordinary maintenance must render as separate variants or
  separate normalized actions.

## Representative complete and partial fixtures

Fixtures should be normalized `Event`-shaped payloads, not raw log strings
only. The raw input should also be retained for adapter tests.

### Complete PostgreSQL auth failure

```json
{
  "action": "rds.auth.failure",
  "event_time": "2026-08-25T04:06:21.424277Z",
  "outcome": "failure",
  "actor": {"principal": "app_user", "source_ip": "198.51.100.24"},
  "target": {"id": "prod-orders", "name": "prod-orders", "type": "rds.db"},
  "extra": {
    "db_instance": "prod-orders",
    "source_type": "postgres",
    "user": "app_user",
    "database": "orders",
    "source_ip": "198.51.100.24",
    "source_port": 54321,
    "reason": "invalid_password",
    "backend_pid": "0"
  }
}
```

### Complete CloudTrail public-access change

```json
{
  "action": "rds.instance.modify",
  "event_time": "2026-08-25T10:00:00Z",
  "actor": {
    "principal": "arn:aws:iam::111122223333:user/operator",
    "source_ip": "198.51.100.30",
    "user_agent": "console.amazonaws.com"
  },
  "target": {"id": "prod-orders", "type": "aws.rds"},
  "extra": {
    "event_name": "ModifyDBInstance",
    "event_source": "rds.amazonaws.com",
    "rds_publicly_accessible": true,
    "message": "RDS instance set to publicly accessible",
    "rds_change_summary": {
      "setting": "publiclyAccessible",
      "after": true
    }
  }
}
```

Expected headline: `RDS instance exposed publicly · prod-orders`. Actor,
account, region, setting, target, and event ID remain visible in evidence.

### Partial lifecycle fixture

```json
{
  "action": "rds.instance.delete",
  "actor": {"principal": "arn:aws:iam::111122223333:role/unknown"},
  "target": {"id": "prod-orders", "type": "aws.rds"},
  "extra": {
    "event_name": "DeleteDBInstance",
    "event_source": "rds.amazonaws.com"
  }
}
```

Expected output shows actor and target, omits source IP, final-snapshot status,
region, and reason, and asks the operator to verify recovery coverage. It must
not claim that a final snapshot was or was not taken.

## Required tests before BW-016 rollout

There is currently no `tests/test_aws_rds.py` file in the repository. That is a
coverage gap, not evidence that the adapter is correct. Add tests without
changing existing data or notification routes.

### Adapter tests

Create focused parser fixtures for:

1. PostgreSQL auth failure with invalid password.
2. PostgreSQL auth failure with missing `pg_hba` entry.
3. PostgreSQL session start/end, including duration and session ID.
4. PostgreSQL pgaudit DDL, role, read, write, function, and unknown class.
5. PostgreSQL FATAL and PANIC errors.
6. Proxy connect/disconnect with and without cache correlation.
7. Proxy auth failure with cached and uncached source IP.
8. Proxy backend HBA rejection.
9. Bare proxy credential-mapping misconfiguration.
10. AWS system-user session suppression while retaining auth failure.

### Projection/staleness tests

Test exact field sets and boundaries for:

1. Fifth auth failure in five minutes emits one burst; sixth does not re-fire
   the same threshold event.
2. Concurrent sessions include all distinct source IPs.
3. First proxy source emits `rds.proxy.source.new`; repeated source does not.
4. First `(user, real_client_ip)` emits `rds.session.new_source`.
5. Unknown user is emitted once per user/database/day and carries its trigger.
6. Long-idle threshold is strictly older than 24 hours and includes connected-
   at time and session ID.
7. Session start/end projection uses the same session ID and closes the row.

### Rendering golden tests

For every event row in this review, render a complete fixture to email/plain
text, a partial fixture with omitted optional fields, and one chat-channel
representation. Also test:

- high/critical variants where severity changes wording;
- advanced-template override, proving saved custom templates remain
  authoritative;
- evidence containing event ID/source/action without dumping raw secrets;
- absent fields and unsupported recovery claims being omitted;
- session end being the only automatic closure for matching session start;
- query, lifecycle, proxy configuration, and security-control events remaining
  manual-resolution events;
- no generic module-wide content appearing in an approved RDS event.

### Catalog and parity tests

Add a parity test comparing the union of actions emitted by `aws_rds.py`,
`rds/projection.py`, `rds/staleness.py`, the RDS portion of
`aws_cloudtrail.py`, and the RDS posture/inventory connector with the RDS
notification catalog. Every difference must be classified as `profiled`,
`non_notifying_by_design`, or `producer_gap`; an unclassified producer action
must fail the test.

## Extra notification-content agents

To implement BW-014/BW-015/BW-016 consistently, use these bounded reviewers
for every module. They should write only their assigned review artifact or
test plan until the coding gate is explicitly opened:

1. **Producer Field Agent** — inventories actual normalized fields, optionality,
   truncation, redaction, correlation, and producer/catalog parity.
2. **Operator Decision Agent** — defines the first decision, false-positive
   branches, safe containment, owner handoff, and manual versus automatic
   recovery for each event.
3. **Message Design Agent** — writes headline, What happened, Facts, Decision,
   Next steps, Evidence, and Recovery copy while enforcing omission rules and
   keeping the outer structure unchanged.
4. **Fixture Agent** — creates complete, partial, malformed, and boundary
   fixtures from real producer shapes without inventing unavailable fields.
5. **Renderer QA Agent** — reviews email/plain-text/chat output, golden tests,
   severity changes, truncation, escaping, and advanced-template precedence.
6. **Coverage Reconciler** — compares producer actions, rules, catalog entries,
   routes, and UI rollout status; it blocks “rolled out” when any event is
   generic or unclassified.

The coordinator should reconcile disagreements in this order: producer truth,
operator safety, event-specific actionability, then wording preference. Agents
must not refresh or modify application code during planning/review, and none
may silently discard an event because it is inconvenient to render.

## Recommended BW-016 implementation sequence

1. Add missing RDS catalog event keys and mark each event generic until its own
   contract exists.
2. Add additive producer fields for pgaudit object identity, CloudTrail RDS
   change summaries, and proxy correlation status.
3. Implement event-specific profile defaults from this matrix; preserve saved
   profiles, advanced templates, routes, channels, throttles, audit history,
   and database data.
4. Add adapter, projection, staleness, rendering, and catalog-parity tests.
5. Expose event-level content readiness in Notification Studio.
6. Mark only events with complete contracts and passing golden tests as rolled
   out; keep remaining RDS events visibly pending.


Expected facts: user, source IP/port, database, reason, instance, and time.
Do not add proxy endpoint or session ID because this fixture does not contain
them.

### Partial proxy auth failure with no cached source

```json
{
  "action": "rds.auth.failure",
  "event_time": "2026-08-25T04:06:21Z",
  "outcome": "failure",
  "actor": {"principal": "reporting_user"},
  "target": {"id": "prod-orders", "type": "rds.db"},
  "extra": {
    "db_instance": "prod-orders",
    "source_type": "rds_proxy",
    "user": "reporting_user",
    "reason": "invalid_credentials",
    "proxy_endpoint": "default",
    "client_connection": "1234",
    "message": "Proxy authentication failed"
  }
}
```

Expected output says the source IP was unavailable from proxy correlation. It
must not render `unknown source` as if it were a fact.

### Complete auth burst

```json
{
  "action": "rds.auth.burst",
  "actor": {"principal": "app_user", "source_ip": "198.51.100.24"},
  "target": {"id": "prod-orders", "name": "prod-orders"},
  "extra": {
    "db_instance": "prod-orders",
    "user": "app_user",
    "failure_count": 5,
    "window_minutes": 5,
    "source_ips": ["198.51.100.24", "198.51.100.25"],
    "message": "5+ failed logins for app_user in 5 min"
  }
}
```

Expected decision: attack versus broken secret retry loop. The notification
must not say “brute force confirmed.”

### Complete concurrent session

```json
{
  "action": "rds.session.concurrent",
  "actor": {"principal": "admin", "source_ip": "203.0.113.10"},
  "target": {"id": "prod-orders", "name": "prod-orders"},
  "extra": {
    "db_instance": "prod-orders",
    "user": "admin",
    "source_ips": ["203.0.113.10", "203.0.113.11"],
    "message": "admin is connected from multiple IPs simultaneously"
  }
}
```

### Complete pgaudit DDL fixture after additive fields

```json
{
  "action": "rds.query.ddl",
  "actor": {"principal": "deploy_role", "source_ip": "10.0.10.15"},
  "target": {"id": "prod-orders", "name": "prod-orders"},
  "extra": {
    "db_instance": "prod-orders",
    "database": "orders",
    "user": "deploy_role",
    "audit_class": "DDL",
    "command": "ALTER TABLE",
    "object_type": "TABLE",
    "object_name": "orders",
    "statement": "ALTER TABLE orders ADD COLUMN risk_flag boolean",
    "scope": "SESSION",
    "backend_pid": "4451",
    "session_id": "pg:prod-orders:4451"
  }
}
```
