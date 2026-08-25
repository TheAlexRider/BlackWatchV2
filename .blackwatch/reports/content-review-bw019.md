# BW-019 content review: S3 object access, exposure, and lifecycle

Status: content review complete. This report is evidence-backed and proposes the notification contract; it does not change the catalog, producers, rules, tests, deployment, or storage.

## Decision

Use the existing outer notification shape in this order: **unique headline → What happened → Facts → Decision → ordered Next steps → Why it matters/Impact → Evidence → Monitoring → Recovery or manual resolution**.

The S3 module is not ready to be marked rolled out. `aws.s3` is `planned` in the module rollout metadata (`blackwatch/notify/profiles.py:242-249`), every current S3 catalog event is still `generic`, and there is no S3 entry in `blackwatch/notify/content_contracts.py` (`apply_event_contracts` only finds contracts in `_ALL`, which currently covers VPN, host, RDS, and services). The catalog has 17 S3 alert kinds (`blackwatch/notify/profiles.py:473-490`), but the producers emit 25 distinct notifying bucket actions plus two object actions. The missing ten bucket actions must be cataloged or explicitly marked future; they must not be treated as covered by a generic bucket template.

Keep raw `s3.object.access` non-notifying by default because it is high-volume and is listed in `_PROJECTION_ONLY_ACTIONS` (`blackwatch/pipeline.py:57-78`). Keep `s3.bucket.snapshot` and `s3.scan.completed` projection-only inputs. Notify on `s3.object.access.anonymous`, CloudTrail management actions when a rule routes them, and projection-derived state changes. Make the non-notifying/future status visible in Notification Studio so “not routed” is not confused with “no contract.”

## Evidence inventory

### Normalized envelope available to every contract

The safe common fields are `event.action`, `event.event_id`, `event.event_time`, `event.outcome`, `event.severity`, `event.source.module`, `event.source.account`, `event.source.region`, `event.source.transport`, `event.actor.principal`, `event.actor.type`, `event.actor.is_root`, `event.actor.via_role`, `event.actor.source_ip`, `event.actor.user_agent`, `event.target.id`, `event.target.type`, `event.target.name`, and named `event.extra` keys. These are the fields in `blackwatch/event.py:90-149`.

Do not render `event.raw` directly. CloudTrail retains raw request parameters in `raw`, but the normalized event only exposes the named signal fields described below (`blackwatch/modules/aws_cloudtrail.py:949-997,1067-1100`). If a fact is not in the envelope or a named `extra` key, the current contract cannot safely promise it.

### Actual producer actions and ownership

| Source | Actual action(s) | Current delivery meaning |
|---|---|---|
| `blackwatch/modules/aws_s3_access.py:15-26,132-224` | `s3.object.access` | One event per parsed access-log line; projection-only, feeds enrichment/UEBA, not stored or notified by default. |
| Same adapter | `s3.object.access.anonymous` | Same shape, but `Requester` is `-`; stored and alertable. |
| Same adapter | `s3.object.access.error_burst` | Documentation placeholder only; not emitted because no S3 access correlation exists. Mark future/non-notifying. |
| `blackwatch/modules/aws_s3.py:62-129` | `s3.bucket.snapshot`, `s3.scan.completed` | Inventory inputs; both are projection-only (`blackwatch/pipeline.py:45-78`). They are not notification events. |
| `blackwatch/modules/aws_cloudtrail.py:90-108,860-1100` | `s3.bucket.create`, `delete`, `acl.put`, `policy.put`, `policy.delete`, `bpa.put`, `bpa.delete`, `encryption.put`, `encryption.delete`, `versioning.put`, `logging.put`, `lifecycle.put`, `replication.put`, `replication.delete`, `object_lock.put` | Control-plane events. S3 management actions are normalized by the CloudTrail producer, not by `aws_s3.py`. |
| `blackwatch/s3/projection.py:41-183` | `s3.bucket.first_seen`, `public`, `unencrypted`, `versioning_off`, `public_removed`, `encryption_added`, `versioning_suspended`, `versioning_enabled`, `logging_disabled`, `disappeared` | Derived state/reconciliation events. They are processed after projection-only snapshots and are stored/notified if not muted. |

Ownership must be explicit: object access has source module `aws.s3.access`, while bucket inventory has source module `aws.s3`; CloudTrail bucket management has source module `aws.cloudtrail`. The operator-facing profile may remain `aws.s3`, but its description, routes, coverage, and preview data must say that it owns all three producer paths. `coverage.py:16-33` maps `aws_s3_drift` to `aws.s3` but has no `aws_s3_access_logs` mapping, so access-log connector coverage is currently invisible in collector coverage.

### Current catalog/rule gaps

- The catalog has object access and 15 bucket entries, but does not catalog `s3.bucket.policy.delete`, `s3.bucket.encryption.put`, `s3.bucket.lifecycle.put`, `s3.bucket.replication.put`, `s3.bucket.replication.delete`, `s3.bucket.object_lock.put`, `s3.bucket.encryption_added`, `s3.bucket.versioning_suspended`, `s3.bucket.versioning_enabled`, or `s3.bucket.logging_disabled`.
- `rules/s3.yaml` covers the public/BPA/encryption/versioning/logging signals and inventory transitions, but has no rule for policy deletion, encryption put, lifecycle, replication, object lock, encryption added, versioning enabled, or the projection’s distinct versioning/logging transition actions (`rules/s3.yaml:8-159`).
- The current S3 rules intentionally route access-log threat-intel/Tor enrichments for both object actions (`rules/s3.yaml:161-208`), but the content layer has no fields or conditional language for `event.extra.intel.feeds` and `event.extra.intel.is_tor`.
- `blackwatch/api.py:1363-1383` exposes only a subset of S3 exposure actions in the storage view. This is a UI surface gap, not evidence that unlisted producer actions are safe or absent.
- `tests/test_notification_rendering.py:54-61` checks unique content only for VPN, EC2, and RDS; S3 is excluded. S3 tests cover selected detectors and adapter outputs (`tests/test_aws_s3.py:18-173`) plus complete/partial inventory adapter behavior (`tests/test_aws_s3.py:175-225`), but there is no `AwsS3AccessAdapter` test, no S3 projection test, no producer-to-catalog parity test, and no S3 plain-text/chat golden render.

## Contract-wide omission and safety rules

1. Omit unavailable facts and the whole labeled line; do not print `unknown`, `not reported`, empty lists, false defaults, or a named actor merely to fill space. A deliberate producer default is not the same as observed evidence.
2. Render `event.source.account` and `event.source.region` only when present. Access-log events currently set both to `None`; do not borrow the log bucket’s region or invent the source account.
3. Use “requester” for a non-anonymous S3 access principal. The access adapter maps every named requester to `ActorType.user`, even when the value is an ARN; do not call it a human user unless the principal is known to be one.
4. For anonymous access, say **anonymous / no authenticated requester**. Never render `Requester="-"` as a user, ARN, role, or “AWS anonymous user.” A source IP, when present, identifies the network source only.
5. `s3.object.access.anonymous` means the access log had no authenticated requester; it does not by itself prove that the bucket is publicly reachable or that data was returned. Show HTTP status when present and phrase impact conditionally.
6. `public_acl`, `public_policy`, and `bpa_weakened` are signal booleans. `public_acl` means a public canned ACL or `AllUsers`/`AuthenticatedUsers` grant; `public_policy` means an Allow wildcard principal without a scoping Condition; `bpa_weakened` means at least one of the four BPA booleans is false or absent. BPA weakened is a precursor, not proof of public readability.
7. Inventory `public` means the drift scan found BPA not fully on plus a public ACL or unscoped public policy. `public_reasons` is only populated with the ACL/policy reasons when `public` is true; it is not a full before/after explanation.
8. `public_removed` means the latest completed drift scan no longer met the public test. It is not proof that no data was accessed while the bucket was public.
9. Do not call an inventory observation “became public” unless a prior private state is actually present. The current projection also emits `s3.bucket.public` on first sight when the bucket is already public (`blackwatch/s3/projection.py:82-99`).
10. Distinguish control-plane actor evidence from scan-state evidence. CloudTrail actions have actor/source/user-agent fields when CloudTrail supplied them; derived inventory events generally do not have a changing actor.
11. Do not state a successful request when `http_status` is absent. The adapter currently maps absent status to `Outcome.success` (`blackwatch/modules/aws_s3_access.py:165-173`); this is a producer ambiguity that the content must not amplify.
12. Never expose full request URI, full object key, or raw policy in notification text. The access adapter intentionally redacts object keys after the first path segment by default (`blackwatch/modules/aws_s3_access.py:120-129`), and projection truncates policies at 16,000 characters (`blackwatch/s3/projection.py:59-63`).

## Proposed event contracts

Each row below is a separate content contract. The “Facts” list is the complete set of facts the renderer may show for that event; absent values are omitted under the rules above.

### Object access family

#### `s3.object.access.anonymous`

- Headline: **Anonymous S3 request · `<bucket>/<redacted key>`**. Add “from Tor” or “from threat-intel match” only when the enrichment flags are actually present; do not claim that from the action alone.
- What happened: An S3 server access log recorded a request with no authenticated requester (`Requester="-"`).
- Facts: bucket from `event.target.id` before the first `/`; redacted object key when present; operation; access-log event time; HTTP status; bytes sent; source IP; user agent; auth type; TLS version; error code; log bucket and log key; optional `event.extra.intel.feeds`/`is_tor` enrichment. Omit the requester/principal line entirely. Account and region are currently unavailable.
- Decision: Decide whether anonymous access is an approved public or presigned-URL workflow; do not treat it as an identified actor or as proof of a successful read without status/bytes.
- Next steps: (1) Check the bucket’s current public/BPA/policy state and whether the object path is intended to be public. (2) Use status, operation, bytes, source IP, and user-agent to determine whether a read/write/error occurred. (3) If unexpected, remove the exposure or rotate/revoke the relevant presigned-URL workflow, preserve the access-log evidence, and review nearby requests from the same source. (4) If `is_tor` or a threat-intel feed is present, escalate as active suspicious access.
- Evidence: The normalized access-log fields plus the matching rule (`s3-object-access-anonymous`, or the specific Tor/intel rule) and `event.event_id`.
- Impact: Potential unauthenticated access to the bucket/object; actual data return is unknown unless status/bytes support it.
- Recovery/manual resolution: No automatic recovery event. Close only after the exposure/workflow is explained or contained and the bucket/object access path is rechecked. Do not close because a later authenticated request succeeds.

#### `s3.object.access`

- Headline: **S3 object request · `<bucket>/<redacted key>`**.
- What happened: A logged S3 request was observed with a named requester when the requester field was present.
- Facts: requester/principal, source IP, bucket and redacted key, operation, access-log time, HTTP status, bytes sent, user agent, auth type, TLS version, error code, log bucket, log key, and optional intel/Tor enrichment. Omit account/region because the adapter sets them to `None`; omit a missing requester rather than converting the event to anonymous.
- Decision: This is normally telemetry, not a notification. If a rule elevated it for Tor, threat-intel, or a downstream UEBA signal, decide whether the source and operation are expected for that bucket.
- Next steps: (1) Identify the requester and source using only the fields present. (2) Correlate the object path, operation, status, and bytes with the workload/change window. (3) For intel/Tor matches, contain or investigate the source and review adjacent access. (4) Leave ordinary high-volume requests in the event/UEBA path rather than paging.
- Evidence: Access-log fields and the exact enrichment/rule match; do not cite the raw URI or full object key.
- Impact: A single named request may be benign; an elevated match may indicate attempted or completed data access. State the uncertainty when status/bytes are absent.
- Recovery/manual resolution: No paired recovery. Resolution is an explained request, a closed intel finding, or documented containment. Keep this action explicitly non-notifying by default.

#### `s3.object.access.error_burst` (future/non-emitting)

- Headline if implemented: **S3 object access error burst · `<bucket or source>`**.
- Current status: The adapter documents this as a placeholder and emits no such action (`blackwatch/modules/aws_s3_access.py:25-26`). There is no S3 entry in `correlation.py`; its watch maps contain only host SSH and VPN failures (`blackwatch/correlation.py:44-52`). Do not create a profile or preview that implies it exists.
- Required future facts: aggregation dimension, count, threshold, window, source IP/principal when known, bucket, representative operation/status/error, and trigger event ID. Recovery is a quiet window or manual explanation, never a generic “recovered.”

### Bucket control-plane family

The CloudTrail rows below share the envelope facts `bucket target`, actor, source IP, user-agent, account, region, event time, outcome, CloudTrail event name, error fields, and the signal-specific `extra` flag. The per-row facts below identify what is unique and what must not be invented.

#### `s3.bucket.create`

- Headline: **S3 bucket created · `<bucket>`**.
- What happened: CloudTrail recorded `CreateBucket`.
- Facts: bucket target, actor/type/root/via-role when present, source IP/user-agent, account, region, event time, outcome, and CloudTrail event ID. Do not claim encryption, BPA, logging, tags, or region-specific configuration from this event; the current adapter does not normalize them.
- Decision: Decide whether the new bucket is approved and whether it is allowed to exist before data is placed in it.
- Next steps: (1) Verify owner, account, region, and change window. (2) Run or await a complete inventory scan. (3) Confirm BPA, encryption, versioning/MFA Delete, logging, tags, and policy. (4) If unauthorized, quarantine access and preserve the CloudTrail event; do not delete data as an automatic response.
- Evidence: CloudTrail `CreateBucket`, actor, target, and subsequent inventory state if available.
- Impact: A new storage resource exists and may be unmanaged or misconfigured; no data exposure is proven.
- Recovery/manual resolution: Manual owner approval, hardening verification, or an approved deletion with data-preservation review. No automatic recovery.

#### `s3.bucket.delete`

- Headline: **S3 bucket deletion requested · `<bucket>`**.
- What happened: CloudTrail recorded `DeleteBucket`.
- Facts: bucket, actor/type/root/via-role, source IP/user-agent, account, region, event time, outcome, error code/message, and CloudTrail event ID. Do not say that all objects were deleted or that deletion completed unless the producer supplies that fact.
- Decision: Treat as urgent; decide whether the deletion is approved and whether recovery evidence is preserved.
- Next steps: (1) Check the change ticket and actor immediately. (2) Verify bucket/object-version retention, replication, and last known-good recovery path. (3) Stop or contain the operation when unauthorized if AWS still permits it. (4) Record the final AWS outcome and preserve CloudTrail/access evidence.
- Evidence: CloudTrail management event and outcome/error fields; an inventory disappearance is separate evidence.
- Impact: The bucket may become unavailable and recovery may depend on versioning, replication, or backups.
- Recovery/manual resolution: Manual cancellation where possible, or approved restore/rebuild verification. `s3.bucket.disappeared` must not be used as proof that this delete succeeded.

#### `s3.bucket.acl.put`

- Headline: **S3 bucket ACL grants public access · `<bucket>`** when `extra.public_acl` is true; otherwise **S3 bucket ACL changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketAcl`; the public variant means a public canned ACL or public grantee was detected.
- Facts: bucket, actor, source IP/user-agent, account/region/time/outcome, `public_acl` when true, error fields, and event ID. Omit ACL mode/grantee details because they are not normalized; do not say “private” when the public flag is absent.
- Decision: If `public_acl` is true, decide whether public or authenticated-global access is approved; otherwise decide whether the ACL change is expected and compatible with BPA.
- Next steps: (1) Confirm the intended ACL and owner. (2) Check current BPA and policy state. (3) Remove the public grant or restore the approved ACL if unapproved. (4) Run an inventory scan and review object access during the exposed interval.
- Evidence: CloudTrail event plus `public_acl` detector and the current bucket posture; the detector treats `AuthenticatedUsers` as public (`blackwatch/modules/aws_cloudtrail.py:331-340`).
- Impact: Public or broadly authenticated access may expose bucket contents; an ACL change without the flag has unknown exposure until posture is checked.
- Recovery/manual resolution: Manual ACL restoration plus a completed posture/access review. `s3.bucket.public_removed` is a later scan state, not proof that all prior access was harmless.

#### `s3.bucket.policy.put`

- Headline: **S3 bucket policy allows public access · `<bucket>`** when `extra.public_policy` is true; otherwise **S3 bucket policy changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketPolicy`; the public variant means an Allow statement with wildcard principal and no scoping Condition was detected.
- Facts: bucket, actor, source IP/user-agent, account/region/time/outcome, `public_policy` when true, error fields, and event ID. Do not render the raw policy, actions, resources, or conditions; those are not normalized safely.
- Decision: Decide whether the policy’s reach is approved, and whether this is exposure or a scoped policy change whose public signal is absent.
- Next steps: (1) Inspect the full policy through the controlled AWS/UI path. (2) Verify the intended principal, resource, condition, and change ticket. (3) Remove or narrow an unapproved wildcard grant. (4) Re-run posture and review access-log activity while it was active.
- Evidence: CloudTrail event and `public_policy` detector; a missing flag is not proof of a private policy because scoped policies are intentionally not flagged.
- Impact: A wildcard Allow may expose object data or write paths; the exact impact depends on the policy actions/resources.
- Recovery/manual resolution: Manual policy correction followed by a completed scan. Do not claim automatic recovery when `public_removed` later appears.

#### `s3.bucket.policy.delete`

- Headline: **S3 bucket policy removed · `<bucket>`**.
- What happened: CloudTrail recorded `DeleteBucketPolicy`.
- Facts: bucket, actor, source IP/user-agent, account/region/time/outcome/error, and event ID. The adapter exposes no before-policy summary or resulting access state.
- Decision: Decide whether removal narrowed access as intended or removed a required deny/guardrail.
- Next steps: (1) Inspect the prior approved policy and current ACL/BPA. (2) Check whether application access, logging, or deny controls changed. (3) Restore the approved policy if unauthorized. (4) Run posture/access validation.
- Evidence: CloudTrail event only unless a later scan or access record supplies state evidence.
- Impact: Access may be reduced, broadened through another control, or fail for expected workloads.
- Recovery/manual resolution: Manual policy restore or approved replacement; no automatic recovery.

#### `s3.bucket.bpa.put`

- Headline: **S3 Block Public Access weakened · `<bucket>`** when `extra.bpa_weakened` is true; otherwise **S3 Block Public Access configured · `<bucket>`**.
- What happened: CloudTrail recorded `PutPublicAccessBlock`.
- Facts: bucket, actor/source/account/region/time/outcome, `bpa_weakened` when true, error, and event ID. The producer does not expose which of the four booleans changed, so omit a per-setting list.
- Decision: If weakened, decide whether the reduction is approved and whether any ACL/policy grants are now effective. If not weakened, confirm the change is the intended hardening.
- Next steps: (1) Inspect all four BPA settings. (2) Check ACL and policy exposure. (3) Restore all required blocks if unapproved. (4) Verify with a completed inventory scan and, if exposure existed, review access logs.
- Evidence: `bpa_weakened` detector; false/absent is not a full before/after record.
- Impact: Public controls may be less effective; weakening alone does not prove public readability.
- Recovery/manual resolution: Manual restoration of the approved four-setting posture plus scan verification. No automatic recovery event.

#### `s3.bucket.bpa.delete`

- Headline: **S3 Block Public Access removed · `<bucket>`**.
- What happened: CloudTrail recorded `DeletePublicAccessBlock`.
- Facts: bucket, actor/source/account/region/time/outcome/error, and event ID. Do not state the resulting ACL/policy reach without a scan.
- Decision: Treat as a high-risk exposure precursor and decide whether the removal was explicitly approved.
- Next steps: (1) Inspect current ACL and bucket policy immediately. (2) Restore BPA if the change is not approved. (3) Run a complete scan. (4) Review access logs for the interval after removal.
- Evidence: CloudTrail `DeletePublicAccessBlock`; the absence of a BPA configuration is not itself proof of a public grant.
- Impact: Existing or future public ACL/policy permissions may become effective.
- Recovery/manual resolution: Manual BPA restore and completed posture review; no automatic recovery.

#### `s3.bucket.encryption.put`

- Headline: **S3 default encryption configured · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketEncryption`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID. Omit algorithm/KMS key because the adapter does not normalize them.
- Decision: Decide whether encryption was added or changed to the approved algorithm/key and whether existing data needs separate treatment.
- Next steps: (1) Inspect the resulting encryption configuration through the controlled AWS path. (2) Compare the algorithm/key with policy. (3) Verify a completed scan and application write/read behavior.
- Evidence: CloudTrail event; later `s3.bucket.encryption_added` is scan evidence, not proof of this exact API call.
- Impact: Default protection may have improved or changed, but this event alone does not prove existing objects are encrypted.
- Recovery/manual resolution: Manual configuration validation or approved rollback; no automatic recovery.

#### `s3.bucket.encryption.delete`

- Headline: **S3 default encryption removed · `<bucket>`**.
- What happened: CloudTrail recorded `DeleteBucketEncryption`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID, and the friendly message when present. No previous/current algorithm is normalized.
- Decision: Treat as a control weakening until the approved exception is confirmed.
- Next steps: (1) Verify the actor and change window. (2) Restore approved default encryption. (3) Check write paths and object-level encryption state. (4) Run a completed scan and document any unencrypted interval.
- Evidence: CloudTrail event; correlate with `s3.bucket.unencrypted` only as separate later scan evidence.
- Impact: New objects may lack expected default encryption; existing objects are not automatically changed by this event.
- Recovery/manual resolution: Manual reconfiguration plus scan/write-path verification. No automatic recovery.

#### `s3.bucket.versioning.put`

- Headline: **S3 bucket versioning suspended · `<bucket>`** when `extra.versioning_suspended`; **S3 MFA Delete disabled · `<bucket>`** when `extra.mfa_delete_disabled`; otherwise **S3 bucket versioning changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketVersioning`.
- Facts: bucket, actor/source/account/region/time/outcome, `versioning_suspended` and/or `mfa_delete_disabled` when true, error, event ID. Omit current status when neither signal is present.
- Decision: Decide whether the integrity/recovery control was intentionally changed and whether destructive operations remain safe.
- Next steps: (1) Inspect current versioning and MFA Delete state. (2) Verify the approved change window. (3) Re-enable the required control if unauthorized. (4) Check object-delete activity and recovery points during the weakened interval.
- Evidence: CloudTrail flags; no before/after status is currently normalized.
- Impact: Suspension or MFA Delete removal can reduce rollback and anti-forensics protection; a normal enable/change may be operational.
- Recovery/manual resolution: Manual restoration and verified current state; `s3.bucket.versioning_enabled` is a separate projection event and is not a guaranteed pair to this control-plane event.

#### `s3.bucket.logging.put`

- Headline: **S3 bucket access logging disabled · `<bucket>`** when `extra.logging_disabled`; otherwise **S3 bucket access logging changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketLogging`.
- Facts: bucket, actor/source/account/region/time/outcome, `logging_disabled` when true, error, event ID. Omit target bucket/prefix because they are not normalized.
- Decision: Decide whether forensic coverage was intentionally changed and whether the destination is approved.
- Next steps: (1) Inspect the resulting logging destination. (2) Restore the approved target if disabled/unapproved. (3) Verify new logs arrive in the destination. (4) Record any visibility gap and use CloudTrail/other telemetry for the interval.
- Evidence: CloudTrail event and `logging_disabled` signal; projection `logging_disabled` is a separate inventory-state observation.
- Impact: S3 server access evidence may be unavailable or redirected.
- Recovery/manual resolution: Manual logging restore and receipt verification; no automatic recovery.

#### `s3.bucket.lifecycle.put`

- Headline: **S3 bucket lifecycle configuration changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketLifecycleConfiguration`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID. Do not invent expiration, transition, noncurrent-version, or filter details; they are only in raw request parameters today.
- Decision: Decide whether retention/deletion/transition behavior is approved for the bucket’s data class.
- Next steps: (1) Inspect the full lifecycle rules. (2) Compare expiration and transition timing with retention/legal requirements. (3) Revert or narrow unauthorized rules. (4) Verify versioned/noncurrent-object behavior.
- Evidence: CloudTrail event; exact lifecycle diff is a producer gap.
- Impact: Objects or versions may be deleted or transitioned earlier/later than intended.
- Recovery/manual resolution: Manual lifecycle correction and retention/recovery verification.

#### `s3.bucket.replication.put`

- Headline: **S3 bucket replication configured · `<bucket>`**.
- What happened: CloudTrail recorded `PutBucketReplication`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID. Omit destination, role, filters, encryption, and RTC details until normalized.
- Decision: Decide whether the replication destination and data movement are approved.
- Next steps: (1) Inspect destination account/region and filters. (2) Verify encryption, ownership, and retention at the destination. (3) Confirm RPO/DR expectations. (4) Correct or remove unauthorized replication.
- Evidence: CloudTrail event only plus later posture/state evidence.
- Impact: Data may be copied cross-region/account or recovery coverage may change.
- Recovery/manual resolution: Manual replication correction followed by a controlled test or approved DR validation.

#### `s3.bucket.replication.delete`

- Headline: **S3 bucket replication removed · `<bucket>`**.
- What happened: CloudTrail recorded `DeleteBucketReplication`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID. Destination and last replicated object are not normalized.
- Decision: Decide whether replication removal is approved and whether the bucket has lost required recovery or data-distribution coverage.
- Next steps: (1) Check the prior destination and DR/RPO requirement. (2) Confirm the change window. (3) Restore approved replication if unauthorized. (4) Measure the replication gap and preserve evidence.
- Evidence: CloudTrail event; no automatic statement about already replicated data.
- Impact: Future writes may stop copying and recovery objectives may be missed.
- Recovery/manual resolution: Manual replication restore and catch-up/DR verification.

#### `s3.bucket.object_lock.put`

- Headline: **S3 Object Lock configuration changed · `<bucket>`**.
- What happened: CloudTrail recorded `PutObjectLockConfiguration`.
- Facts: bucket, actor/source/account/region/time/outcome/error, event ID. Omit default retention mode/days and legal-hold details because they are not normalized.
- Decision: Decide whether immutability/retention protections were strengthened or weakened within policy.
- Next steps: (1) Inspect default retention and governance/compliance mode. (2) Verify legal-hold/retention requirements. (3) Restore approved protection if unauthorized. (4) Check affected object versions and deletion behavior.
- Evidence: CloudTrail event; the exact lock configuration is a producer gap.
- Impact: Retention, deletion, and recovery guarantees may have changed.
- Recovery/manual resolution: Manual configuration correction and object-level retention verification; no automatic recovery.

### Bucket inventory and projection family

#### `s3.bucket.snapshot` (projection-only input)

- Headline: No notification. It is a scan sample, not an operator alert.
- Actual facts: bucket name/id, region, account, created date, public boolean/reasons, encryption, versioning, MFA Delete boolean, four BPA booleans when supplied, logging block, policy, tags, scan timestamp, and the scanner version only on the separate `s3.scan.completed` event (`blackwatch/modules/aws_s3.py:85-127`).
- Important omission: the adapter drops connector `bucket.errors`, does not carry `scan_complete` into the snapshot, and applies defaults (`public=False`, `encryption="none"`, `versioning="Disabled"`, `mfa_delete=False`). The connector explicitly permits per-bucket failures while returning `scan_complete=True` (`blackwatch/connectors/aws_s3_drift.py:21-23,99-214,236-255`). These defaults must not be rendered as observed posture without an additive error/field-validity contract.
- Resolution: Use only to drive projection; if partial bucket results are exposed later, label them “incomplete scan data,” not a posture finding.

#### `s3.scan.completed` (projection-only reconciliation input)

- Headline: No notification. It is the gate that makes disappearance reconciliation safe.
- Actual facts: account, bucket-name list, scanner version, scan timestamp, and source/transport.
- Partial behavior: The adapter emits this only when `scan_complete` is true (`blackwatch/modules/aws_s3.py:110-128`). A false/absent completion signal produces snapshots but no completion event, so the projection must not infer disappearance. This is tested in `tests/test_aws_s3.py:207-220`.
- Resolution: Surface scan health in collector/coverage status, not as a bucket security alert. A complete scan is evidence for the next state event, not itself evidence of a bucket change.

#### `s3.bucket.first_seen`

- Headline: **S3 bucket first observed by BlackWatch · `<bucket>`**.
- What happened: The projection had no retained status row for the bucket and saw it in inventory.
- Facts: bucket, account/region when present, observed scan time, current public/encryption/versioning values when passed by the projection, and event ID. Omit “created at” unless `created_date` is preserved on the derived event; current derived extras do not carry it.
- Decision: Decide whether this is an approved/newly onboarded bucket or an unexpected resource.
- Next steps: (1) Verify owner/account/region and creation/change records. (2) Complete posture checks for BPA, ACL, policy, encryption, versioning, logging, tags, and retention. (3) Route to the owner or onboarding workflow. (4) Escalate if the bucket is public or lacks required controls.
- Evidence: Inventory projection state, not proof of AWS creation time. The current code emits first-seen even on the first observed row (`blackwatch/s3/projection.py:82-89`), despite comments describing a silent baseline.
- Impact: A previously untracked bucket may hold data outside governance; no malicious creation is proven.
- Recovery/manual resolution: Manual owner confirmation/onboarding. It is not a recovery event and does not close a create alert.

#### `s3.bucket.public`

- Headline: **S3 bucket is publicly reachable by current drift checks · `<bucket>`**.
- What happened: The inventory projection observed the bucket in a public state, either on first sight or after a private-to-public transition.
- Facts: bucket, account/region when present, observed time, `public_reasons`, current public state if added, and event ID. Do not title it “became public” without a prior-state field.
- Decision: Decide whether the exposure is approved; for a private-data bucket treat as urgent.
- Next steps: (1) Inspect ACL, policy, BPA, and intended public workflow. (2) Remove unintended public grants or restore BPA. (3) Review access logs for exposure period. (4) Re-scan and verify the state is private/approved.
- Evidence: Drift scan plus reasons; current reasons identify ACL/policy paths, while BPA may be the enabling condition.
- Impact: Anonymous or broadly public reads/writes may be possible; actual access requires access-log evidence.
- Recovery/manual resolution: Paired only with a later `s3.bucket.public_removed` state observation, which must be verified. No automatic remediation.

#### `s3.bucket.public_removed`

- Headline: **S3 bucket is no longer public · `<bucket>`**.
- What happened: A later completed scan no longer met the public-access test.
- Facts: bucket, account/region, observation time, and event ID. Current projection does not carry the prior public reasons or the control that removed exposure.
- Decision: Decide whether the exposure was intentionally remediated and whether historical access still needs investigation.
- Next steps: (1) Confirm current ACL/policy/BPA. (2) Review access logs during the public interval. (3) Verify no alternate public path remains. (4) Close the earlier exposure only after evidence is documented.
- Evidence: Projection state transition; not evidence that data was not accessed.
- Impact: Current public reachability appears removed, but historical exposure may remain.
- Recovery/manual resolution: This is the potential recovery state for `s3.bucket.public`; it is not a guarantee of containment.

#### `s3.bucket.unencrypted`

- Headline: **S3 bucket observed without default encryption · `<bucket>`**.
- What happened: Inventory observed encryption `none`, either initially or after a transition from an encrypted state.
- Facts: bucket, region/account when present, observed time, previous encryption only when `extra.prev_encryption` exists, and event ID. Omit the current algorithm because the derived event does not carry it.
- Decision: Decide whether the absence is an approved exception and whether sensitive objects require remediation.
- Next steps: (1) Inspect current default encryption and object-level encryption. (2) Restore the approved setting. (3) Identify writes during the unencrypted interval. (4) Re-scan and document the resulting posture.
- Evidence: Inventory projection; `prev_encryption` is present only for a transition to none (`blackwatch/s3/projection.py:110-117`).
- Impact: New objects may lack expected default protection; the event does not prove existing objects are unencrypted.
- Recovery/manual resolution: Manual encryption configuration and data review; `s3.bucket.encryption_added` is a state improvement, not proof every object is remediated.

#### `s3.bucket.encryption_added`

- Headline: **S3 default encryption restored · `<bucket>`**.
- What happened: Inventory observed a transition from `none` to an encryption value.
- Facts: bucket, region, new encryption value when present in `extra.encryption`, observation time, and event ID. Account is only available if the projection is changed to retain it on this derived action.
- Decision: Confirm that the approved algorithm/key is now active and that the earlier unencrypted interval was reviewed.
- Next steps: (1) Validate the actual setting and key policy. (2) Check object-level encryption and writes made before remediation. (3) Re-scan and close the unencrypted review only when both posture and data handling are understood.
- Evidence: Projection transition with `extra.encryption`; not an object-by-object encryption proof.
- Impact: Default protection improved; prior exposure may remain.
- Recovery/manual resolution: Potential recovery for `s3.bucket.unencrypted`, correlated by bucket and state timeline, with manual closure.

#### `s3.bucket.versioning_off`

- Headline: **S3 bucket versioning is off · `<bucket>`**.
- What happened: Inventory observed `Disabled` or `Suspended` versioning, including initial observation.
- Facts: bucket, region, `extra.current` when present, observation time, and event ID. Current derived event lacks the full current versioning/MFA Delete state; omit absent values.
- Decision: Decide whether version history is required for this data and whether the state is an approved exception.
- Next steps: (1) Inspect versioning and MFA Delete. (2) Enable the required state if unapproved. (3) Review object deletes/overwrites during the unversioned interval. (4) Re-scan and verify recovery coverage.
- Evidence: Inventory projection; initial state and changed state are not currently distinguished.
- Impact: Recovery from object deletion/overwrite may be limited.
- Recovery/manual resolution: Manual enablement and verification; `versioning_enabled` is a separate projection event, not guaranteed for every repair.

#### `s3.bucket.versioning_suspended`

- Headline: **S3 bucket versioning suspended · `<bucket>`**.
- What happened: Projection saw a transition from `Enabled` to `Suspended`.
- Facts: bucket, region, observation time, and event ID. The current event does not carry explicit previous/current values beyond the action name.
- Decision: Treat as an integrity/recovery-control weakening unless approved.
- Next steps: (1) Confirm the change and current status. (2) Re-enable versioning if unauthorized. (3) Review deletes/overwrites and recovery points during the suspension. (4) Document the approval or incident.
- Evidence: Projection comparison at `blackwatch/s3/projection.py:119-124`.
- Impact: New object versions may not be retained for rollback.
- Recovery/manual resolution: Manual restoration; correlate to `versioning_enabled` only when the later event is actually observed.

#### `s3.bucket.versioning_enabled`

- Headline: **S3 bucket versioning enabled · `<bucket>`**.
- What happened: Projection saw a transition into `Enabled`.
- Facts: bucket, region, observation time, and event ID. Current event does not carry the previous state or MFA Delete.
- Decision: Confirm the recovery-control change is approved and that the bucket now meets the required state.
- Next steps: (1) Verify versioning and MFA Delete directly. (2) Check whether data lost during the off interval needs separate recovery. (3) Confirm future deletes create recoverable versions. (4) Close the earlier versioning review manually.
- Evidence: Projection comparison at `blackwatch/s3/projection.py:119-124`.
- Impact: Future rollback coverage improves; the event does not restore deleted data.
- Recovery/manual resolution: Potential recovery for `versioning_off`/`versioning_suspended`, with manual verification.

#### `s3.bucket.logging_disabled`

- Headline: **S3 bucket access logging target removed · `<bucket>`**.
- What happened: Projection saw a previously configured logging target disappear.
- Facts: bucket, region, previous target from `extra.prev_target`, observation time, and event ID. Omit the new target because it is absent by definition.
- Decision: Decide whether forensic logging was intentionally removed and whether the visibility gap is acceptable.
- Next steps: (1) Restore the approved logging target. (2) Verify delivery to the log bucket. (3) Record the gap and use CloudTrail/other telemetry for the interval. (4) Re-scan and confirm logging state.
- Evidence: Projection comparison at `blackwatch/s3/projection.py:126-128`.
- Impact: Future object access may lack server access-log evidence.
- Recovery/manual resolution: Manual logging restoration and delivery verification; do not claim recovery from a generic `s3.bucket.logging.put` event without a completed scan.

#### `s3.bucket.disappeared`

- Headline: **S3 bucket absent from completed inventory scan · `<bucket>`**.
- What happened: A bucket tracked for this account was absent from a scan that emitted `s3.scan.completed`.
- Facts: bucket, account, region, `was_public`, `last_scan`, current scan time, and event ID. Omit deletion language, actor, and cause; the projection does not know whether the bucket was deleted, renamed/impossible for S3, hidden by permissions, or missed by a bad complete-looking scan.
- Decision: Decide whether the absence is an approved deletion or a visibility/inventory problem.
- Next steps: (1) Verify with AWS `ListBuckets` and the account/credentials used by the scanner. (2) Check CloudTrail for `DeleteBucket` and connector errors. (3) If it still exists, restore/repair inventory coverage and re-scan. (4) If deleted, verify the approved change and recovery evidence; preserve the disappearance event.
- Evidence: The completed scan gate and tracked `last_scan`; `s3.scan.completed` is intentionally absent on partial scans, tested at `tests/test_aws_s3.py:207-220`.
- Impact: The bucket may be gone, unavailable to the scanner, or outside current governance; data loss is not proven.
- Recovery/manual resolution: Manual re-scan/credential repair or approved deletion review. Never auto-close as deleted and never auto-delete state in response to an incomplete scan.

## Complete and partial fixture plan

These are the fixtures the BW-019 implementation should add; none are currently present as S3 notification-rendering goldens.

| Fixture | Complete input and expected facts | Partial input and expected omission/behavior |
|---|---|---|
| Object access, named requester | Batch envelope with `kind=s3_access_log_batch`, `log_bucket`, `log_key`, `source_bucket`, and a full access-log row containing requester ARN, operation, redacted key, remote IP, status `200`, bytes, user-agent, auth type, TLS, error `-`, and timestamp. Expected actor principal/source IP, target bucket/prefix, operation, status, bytes, log provenance, and no raw URI/full key. | Row with requester `-`, remote IP `-`, status `-`, bytes `-`, and only the first eight positional fields. Expected anonymous action, no principal/source IP/status/bytes; retain bucket/operation if parseable. A line with fewer than eight tokens is dropped entirely by `_parse_line` (`aws_s3_access.py:91-98`) and must not produce a notification. |
| Object access, enrichment | Same object action with `extra.intel.feeds=[...]` or `extra.intel.is_tor=true`. Expected conditional evidence/headline modifier only when the enrichment exists. | Same action without `intel` keys. It must not render “threat-intel” or “Tor.” |
| Inventory complete | Existing fixture shape at `tests/test_aws_s3.py:177-204`: two buckets, account, regions, public reasons, AES256/none encryption, versioning, BPA, scanner version, `scan_complete=true`. Expected two snapshots plus one scan-complete projection input; later projection contracts may emit state transitions. | Existing fixture shape at `tests/test_aws_s3.py:207-220`: one bucket, `scan_complete=false`. Expected snapshots only, no `s3.scan.completed`, no disappearance reconciliation, and no “bucket deleted” alert. |
| Inventory per-bucket failure | Connector fixture with a bucket containing `errors=["GetBucketPolicy: AccessDenied"]` plus other observed fields. Expected explicit incomplete-field state and an omitted/qualified public-policy conclusion. | Current behavior drops `errors` in `AwsS3Adapter` and defaults missing values; this is a producer gap that must be fixed additively before using such a fixture as a posture notification. |
| CloudTrail public ACL/policy | Existing fixtures at `tests/test_aws_s3.py:117-150`: full actor/account/region/source and `PutBucketAcl`/`PutBucketPolicy`; expected action plus `public_acl=true` or `public_policy=true`. | Missing actor/source/request parameters: action may still be known, but omit identity, source, and signal-specific claims; render a manual review of the control-plane event. |
| CloudTrail controls | Existing BPA/versioning/delete fixtures at `tests/test_aws_s3.py:153-173`; expected exact signal flags and action. | Missing signal detail: do not infer current BPA/versioning/logging/encryption state from the API name alone. |

Golden rendering must cover plain text/email and one chat channel for at least: anonymous access, named access with intel, public policy, BPA deletion, encryption removal, versioning suspension, first seen, public removed, unencrypted, encryption added, logging disabled, disappeared after complete scan, and a partial scan that produces no disappearance. Assert that anonymous output contains no `principal`/`user` label and that absent fields do not leave empty labels or fabricated defaults.

## Producer and projection changes required before rollout

All changes below should be additive and data-preserving.

1. Preserve source ownership and scan provenance: add normalized `scan_id`/`scanner_version`, `scan_complete`, per-bucket `scan_errors`/field-validity, and account/region to every derived inventory event where available.
2. Do not map per-bucket access failures to `public=false`, `encryption=none`, `versioning=Disabled`, or `mfa_delete=false` without a validity marker. The connector already records errors, but `AwsS3Adapter` drops them.
3. Add control-plane summaries for fields the content needs: ACL mode/public grant kind, policy public-signal summary (not raw policy), BPA before/current booleans, encryption algorithm/key reference, versioning/MFA Delete current state, logging target/prefix, lifecycle summary, replication destination/account/region, and Object Lock mode/retention. Keep secrets, full URIs, full PHI-bearing object keys, and raw policy out of notification text.
4. Add stable transition metadata: `previous_state`, `current_state`, `state_origin` (`transition`, `first_observed`, `baseline`), `prior_scan_at`, and a bucket correlation key. This is required to distinguish a first-public observation from a public transition and to pair recovery wording safely.
5. Fix the documented/code mismatch for first sight: the projection comment says baseline is silent, but code emits `first_seen` and initial public/unencrypted/versioning events (`blackwatch/s3/projection.py:82-100`). Choose and test one behavior; the recommended behavior is `first_seen` plus a qualified state observation, with `state_origin=first_observed`, not a false “became” headline.
6. Add an explicit S3 access connector entry to collector coverage and document that `aws.s3.access` is owned by the `aws.s3` notification module while remaining a distinct source module.
7. Add rules or explicit future status for the ten currently unprofiled bucket actions. Do not route lifecycle/replication/object-lock changes through the public-exposure copy; their impact and recovery differ.

## Recommended rollout gate

Mark BW-019 rolled out only when: every actual action has a unique contract or an explicit `projection_only`, `non_notifying_high_volume`, or `future/not_emitted` classification; the catalog and rules expose the same ownership map; complete/partial fixtures pass; all listed golden renders pass; anonymous/public semantics are asserted; and the per-bucket error/partial-scan behavior cannot create a false disappearance or false secure posture.

## Graph context and review limits

The existing Graphify graph was used read-only with the vocabulary terms `object`, `access`, `bucket`, `public`, `projection`, `correlation`, `catalog`, `notification`, `scan`, `partial`, and `aws`. It connected the S3 adapter, drift scanner, projection, public-signal detectors, and S3 tests, but it did not replace source-level inspection. The configured Graphify interpreter could not start in this environment (`Access is denied`), no Graphify refresh was run, and no Graphify output was modified.
