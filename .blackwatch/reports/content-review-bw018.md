# BW-018 content review

## Decision

Use one stable outer notification shape for every in-scope action:

1. unique headline
2. What happened
3. Facts
4. Decision
5. ordered Next steps
6. Why it matters
7. Evidence
8. Monitoring
9. Impact
10. Recovery

The canonical operator-facing owner is aws.iam. The actual producer remains
aws.cloudtrail. Do not duplicate profile IDs. Show both labels in previews and
evidence: “Owner: AWS IAM; produced by aws.cloudtrail.”

BW-018 is not complete. The producer maps 49 unique in-scope actions; the
catalog has 20. Twenty-nine producer actions are unprofiled. The existing IAM
contracts in blackwatch/notify/content_contracts.py:312-395 are a useful
baseline, but they share generic facts/evidence, use “not reported” filler,
omit request scope, and use generic recovery text.

## Evidence reviewed

- blackwatch/modules/aws_cloudtrail.py:35-232, 685-826, 859-1110
- blackwatch/event.py:80-139 and docs/EVENT_SCHEMA.md:38-129
- blackwatch/notify/profiles.py:106-149, 220-378, 450-470, 704
- blackwatch/notify/content_contracts.py:312-395, 534-623
- blackwatch/notify/catalog.py:36-208
- blackwatch/notify/routes_view.py:36-106
- rules/aws_iam.yaml:18-187
- tests/test_aws_cloudtrail.py:1-110
- tests/test_aws_posture.py:148-190, 267-343
- tests/test_notification_catalog.py, tests/test_notification_rendering.py,
  tests/test_notification_profiles.py
- scripts/iam_test_drive.py:166-389

## Actual producer fields

AwsCloudTrailAdapter accepts a CloudTrail record or an EventBridge envelope
with the record under detail. Non-dicts and records without eventName are
dropped.

| Field | Actual behavior and omission rule |
|---|---|
| source.module | Always aws.cloudtrail. |
| source.vendor | Always aws. |
| source.account | raw.account, else detail.recipientAccountId; absent if both are missing. |
| source.region | raw.region, else detail.awsRegion; absent if missing. |
| source.transport | Context transport when recognized, else queue. |
| event_time | detail.eventTime, else raw.time. Invalid/missing input silently becomes current time; this is a producer accuracy gap. |
| event_id | UUID5 from detail.eventID when present; otherwise generated UUID. Only label it a source event ID when detail.eventID exists. |
| category | IAM/KMS=iam; auth=auth; CloudTrail=audit. Category is not UI ownership. |
| outcome | ConsoleLogin is success only when responseElements.ConsoleLogin is success; otherwise failure. Other actions are failure iff errorCode exists, otherwise success. Missing ConsoleLogin response is indistinguishable from explicit failure. |
| raw | Original record; preserve for evidence, never render wholesale. |
| target.id | First present of policyArn, roleName, userName, groupName, accessKeyId, service IDs, keyId, or CloudTrail name when eventSource starts with cloudtrail. |
| target.type | aws.<service>; never a precise iam.user/role/policy type. |
| target.name | Never populated by this adapter. |
| actor.principal | userIdentity.arn, else userIdentity.userName, else root for Root; absent otherwise. |
| actor.type | Root=root, IAMUser=user, AssumedRole=role, AWSService/AWSAccount=service; other types absent. |
| actor.is_root | True only for Root. Show only when true. |
| actor.source_ip | sourceIPAddress only when the simple IP regex accepts it. |
| actor.user_agent | userAgent when present. |
| actor.via_role | Never populated, even when sessionContext.sessionIssuer exists. |
| observables | Actor ARN, accepted IP, policyArn, accessKeyId, and userName when present. |

Common extra fields are event_name, event_source, mfa_used, error_code, and
error_message; None values are removed. Conditional extras are:

- wildcard_policy=true for the IAM wildcard policy detector.
- login_kind=root or iam for auth.console.login.
- login_kind=sso for auth.federated.login.
- kms_wildcard_policy=true for an unconstrained wildcard KMS principal.
- Other positive security flags belong to other module families.

## Rendering contract and omissions

Render only supplied facts. Never render “not reported,” “unknown identity,” or
a guessed principal, source, impact, threshold, or recovery.

Always render action, outcome, event name, and What happened. Render actor,
source IP, user agent, account, region, target, MFA, login kind, errors, and
event ID only when present. Render MFA No when explicitly supplied; omit MFA
when absent. Absence of a positive flag means “not detected by this parser,”
not “safe.” Never render raw requestParameters, policy documents, passwords,
tokens, or secret values. Do not claim the fallback current time is the AWS
event time.

The producer should add only additive, allowlisted extras when request
parameters exist:

- affected_resource, affected_resource_type
- affected_principal, affected_principal_type
- request_scope, as a short redacted summary
- policy_arn, policy_name, role_arn, group_name, access_key_id, key_id
- grantee_principal, grant_operations, grant_constraints
- pending_window_days
- trail_name, trail_change_summary
- login_provider, login_role_arn
- via_role and source_time_present

## Action inventory and contracts

Each row uses the common facts above plus its action-specific fields. Each
headline must be rendered from the action contract, not from generic fallback.

### IAM identity, credential, and group actions

| Action | Catalog | Headline | Decision and ordered next steps | Impact / recovery |
|---|---|---|---|---|
| iam.user.create | yes | IAM user created — affected user | Verify owner/ticket; review groups, policies, profile, MFA, keys; disable only if unauthorized. | New persistent access. Manual approval or disable/delete; no automatic recovery. |
| iam.user.update | gap | IAM user changed — affected user | Obtain changed-attribute scope; check nearby credentials/policies; revert only unauthorized fields. | Identity access may change. Manual rollback. |
| iam.user.delete | yes | IAM user deleted — affected user | Confirm ticket; check automation and ownership transfer; restore only with approval. | Access/automation or audit ownership may break. Manual replacement. |
| iam.role.create | yes | IAM role created — role | Review trust principals, external IDs, policies, owner; remove/constrain if unapproved. | New privilege/cross-account path. Manual repair/deletion. |
| iam.role.delete | yes | IAM role deleted — role | Confirm ticket; check callers/dependencies; recreate only with approval. | Workloads/access may fail. Manual recreation. |
| iam.role.update_trust | yes | IAM role trust policy changed — role | Compare trust diff; validate every principal/account/condition; remove unintended trust and test. | Cross-account/workload access can expand. Manual rollback. |
| iam.role.boundary.put | gap | IAM role permissions boundary set — role | Verify boundary/ticket; evaluate effective permissions; restore approved boundary if unexpected. | Guardrail changes. Manual correction. |
| iam.role.boundary.delete | gap | IAM role permissions boundary removed — role | Treat as privilege-control change; review effective permissions and nearby policies; reapply if unauthorized. | Role may exceed its prior guardrail. Manual reapplication. |
| iam.group.create | gap | IAM group created — group | Verify owner; review group policies and intended membership; keep/remove under change control. | New group-based access path. Manual removal. |
| iam.group.delete | gap | IAM group deleted — group | Check members/policies; confirm replacement access; restore only if approved. | Users may lose access or policy history. Manual recreation. |
| iam.group.add_user | gap | IAM user added to group — user to group | Review inherited permissions; validate user/ticket; remove membership if unauthorized. | Immediate inherited access. Manual removal or approval. |
| iam.group.remove_user | gap | IAM user removed from group — user from group | Confirm ticket; check dependent jobs; restore only with approval. | Access/automation may be interrupted. Manual re-add/replacement. |
| iam.login_profile.create | yes | IAM console login profile created — user | Verify console approval; require MFA; review policies and password handling. | New interactive credential. Manual deletion/rotation. |
| iam.login_profile.update | gap | IAM console login profile changed — user | Verify owner/change; check MFA and recent logins; rotate/revoke if unexplained. | Interactive credential changed. Manual reset/deletion. |
| iam.login_profile.delete | gap | IAM console login profile removed — user | Confirm deprovisioning; check recent access/dependencies; recreate only through approved request. | Console access removed. Manual recreation. |
| iam.access_key.create | yes | IAM access key created — user | Identify owner; check scope/last use; set expiry/rotate or disable if unapproved. | Long-lived programmatic access. Manual rotation/disable/delete. |
| iam.access_key.update | gap | IAM access key changed — key | Verify owner/ticket; check last use/consumers; restore status or rotate if unexpected. | Credential state changed. Manual correction. |
| iam.access_key.delete | gap | IAM access key deleted — key | Check consumers and replacement; restore service only through controlled rotation. | Automation may stop; deletion may be containment. Manual replacement. |
| iam.mfa.enable | gap | IAM MFA enabled — identity | Verify owner/device enrollment; review nearby login/profile changes. | Protection improves, but rogue enrollment is possible. Manual device review. |
| iam.mfa.deactivate | yes | IAM MFA disabled — identity | Verify approver; re-enable MFA; review recent logins, keys, and profiles. | Takeover resistance drops. Paired enable when observed; otherwise manual re-enrollment. |
| iam.mfa.delete | gap | IAM virtual MFA device deleted — identity/device | Confirm deprovisioning; review login/recovery activity; re-enroll through the approved process. | Protection/recovery path may weaken. Manual re-enrollment. |

### IAM policy actions

All policy contracts add policy ARN/name, affected principal, and an
allowlisted permission summary. The current target.id may be policyArn; it
does not identify the affected user/role/group separately.

| Action | Catalog | Headline | Decision and ordered next steps | Impact / recovery |
|---|---|---|---|---|
| iam.policy.attach | yes | IAM policy attached — policy to principal | Verify policy/principal/ticket; evaluate effective access/admin; detach/restrict if unauthorized. | Permissions take effect immediately. Manual detach/replacement. |
| iam.policy.detach | gap | IAM policy detached — policy from principal | Confirm ticket; check dependent services; restore only approved attachment. | Access/automation may be interrupted. Manual reattach. |
| iam.policy.put_inline | yes | Inline IAM policy changed — principal | Review redacted diff, wildcard flag, and escalation actions; remove unauthorized statements. | Silent broad access possible. Manual rollback. |
| iam.policy.delete_inline | gap | Inline IAM policy removed — principal | Identify deleted policy; check dependent calls; restore only approved policy. | Access/control may be removed. Manual re-add. |
| iam.policy.create | gap | Managed IAM policy created — policy | Review summary, owner, versions, and scope; keep/delete under change control. | New reusable permission set. Manual deletion after dependency review. |
| iam.policy.delete | gap | Managed IAM policy deleted — policy | List attachments; confirm replacement; recreate/reattach only under approval. | Multiple principals/workloads may change. Manual recreation. |
| iam.policy.create_version | gap | IAM policy version created — policy | Compare diff/default-version transition; set approved version or remove bad one. | All attachments may change behavior. Manual version rollback/delete. |
| iam.policy.delete_version | gap | IAM policy version deleted — policy | Verify version/ticket; check default/remaining versions; recreate approved version if needed. | Rollback options may be reduced. Manual recreation. |

### KMS actions

| Action | Catalog | Headline | Decision and ordered next steps | Impact / recovery |
|---|---|---|---|---|
| kms.key.create | gap | KMS key created — key | Verify owner/alias; review policy/rotation; tag and baseline before use. | New crypto boundary. Manual retirement/deletion after dependency review. |
| kms.key.enable | gap | KMS key enabled — key | Verify owner/ticket; test crypto paths; review why it was disabled. | Encrypted operations may resume. Manual review, not automatic closure. |
| kms.key.disable | yes | KMS key disabled — key | Identify production/encryption/backup dependencies; re-enable if unauthorized; test paths. | Encrypted data may be inaccessible. Paired enable plus successful test. |
| kms.rotation.disable | yes | KMS automatic rotation disabled — key | Check compliance/owner; re-enable or document exception; record risk acceptance. | Key-material lifetime/exposure increases. Paired rotation enable or approved exception. |
| kms.rotation.enable | gap | KMS automatic rotation enabled — key | Verify key/owner; check prior exception; confirm rotation and consumers. | Protection improves but still needs validation. Manual review. |
| kms.policy.put | yes | KMS key policy changed — key | Review principals, conditions, cross-account access, and wildcard flag; restore least privilege and test. | Crypto use/admin access can expand. Manual rollback. |
| kms.key.delete_scheduled | yes | KMS key deletion scheduled — key | Inventory dependencies/backups; cancel if unauthorized; record pending window and owner plan. | Data may become permanently unreadable. Paired key deletion cancelled before deadline. |
| kms.key.delete_cancelled | gap | KMS key deletion cancelled — key | Verify state; determine why deletion was scheduled; close only after crypto-path validation. | Deletion risk reduced; prior intent remains. Manual closure. |
| kms.grant.create | yes | KMS grant created — key to grantee | Inspect grantee, operations, constraints, lifetime, workload/account; retire if unapproved. | Direct crypto use may be granted. Paired retire/revoke when observed. |
| kms.grant.retire | gap | KMS grant retired — key/grantee | Identify grant/workload; confirm ticket; restore only via a new approved grant. | Dependent crypto access may fail. Manual new grant. |
| kms.grant.revoke | gap | KMS grant revoked — key/grantee | Confirm containment versus unauthorized removal; check recent use; reissue only with approval. | Dependent operations may fail. Manual new grant and validation. |

### CloudTrail control-plane actions

| Action | Catalog | Headline | Decision and ordered next steps | Impact / recovery |
|---|---|---|---|---|
| cloudtrail.logging.start | gap | CloudTrail logging started — trail | Verify trail/account/region; confirm delivery/retention; record blind interval; close after test event. | Visibility may return but prior events may be missing. Manual validation. |
| cloudtrail.logging.stop | yes | CloudTrail logging stopped — trail | Confirm maintenance or restore urgently; restart; verify delivery; record blind interval. | Actions may go unrecorded. Paired logging start plus delivery test. |
| cloudtrail.trail.create | gap | CloudTrail trail created — trail | Verify owner, selectors, destination, encryption, retention, access; baseline before relying on it. | New coverage may be incomplete. Manual validation. |
| cloudtrail.trail.delete | yes | CloudTrail trail deleted — trail | Treat as tampering until approved; restore/replace; verify delivery, retention, and gap. | Audit visibility/evidence continuity may be lost. Manual restoration. |
| cloudtrail.trail.update | yes | CloudTrail trail configuration changed — trail | Obtain request diff; verify destination/selectors/encryption/retention/access; restore controls and test. | Coverage can weaken without stopping. Manual rollback/validation. |

### Login actions

| Action | Headline | Decision and ordered next steps | Impact / recovery |
|---|---|---|---|
| auth.console.login | AWS console login succeeded/failed — principal | Verify identity, source, MFA, user agent, account/region, outcome, and window; review nearby failures, keys, roles, and MFA; protect/revoke only when unexpected. Evidence is ConsoleLogin, login_kind, MFA, outcome/error, event ID. | Success establishes interactive access; failure does not. No automatic recovery; later success is separate evidence. |
| auth.federated.login | Federated AWS login succeeded/failed — principal and SAML/WebIdentity event | Verify IdP sign-in, provider, role/session target, source, account/region, and window; review role session; revoke IdP/session if unexpected. Evidence is AssumeRoleWithSAML or AssumeRoleWithWebIdentity, login_kind=sso, and outcome/error. | Temporary control-plane access may be granted. No automatic recovery; manual IdP/session closure. |

## Ownership, catalog, and rule gaps

The 20 current catalog actions are the two auth actions, three CloudTrail
actions, ten IAM actions, and five KMS actions listed above. Producer-only
actions are:

cloudtrail.logging.start, cloudtrail.trail.create,
iam.access_key.delete, iam.access_key.update,
iam.group.add_user, iam.group.create, iam.group.delete, iam.group.remove_user,
iam.login_profile.delete, iam.login_profile.update,
iam.mfa.delete, iam.mfa.enable,
iam.policy.create, iam.policy.create_version, iam.policy.delete,
iam.policy.delete_inline, iam.policy.delete_version, iam.policy.detach,
iam.role.boundary.delete, iam.role.boundary.put,
iam.user.boundary.delete, iam.user.boundary.put, iam.user.update,
kms.grant.retire, kms.grant.revoke, kms.key.create,
kms.key.delete_cancelled, kms.key.enable, kms.rotation.enable.

Required parity test: extract normalized actions from _ACTION_MAP, subtract an
explicit future/non-notifying set, and require exactly one profile contract for
each remaining action. New producer actions must fail closed.

The existing catalog alias at notify/catalog.py:36-38 correctly lets aws.iam
coverage match both source.module=aws.iam and source.module=aws.cloudtrail.
routes_view.py:91-92 maps a direct CloudTrail source route to the IAM display
bucket. Remaining gaps:

1. routes_view._ACTION_PREFIX_TO_MODULE has aws.cloudtrail. but no iam., kms.,
   cloudtrail., or auth. prefixes, so custom rules for producer-only normalized
   actions fall into the custom bucket.
2. Producer-only actions have no module_for_event_kind result, profile ID, or
   UI content status.
3. _MODULE_ROLLOUT marks aws.iam planned/generic while apply_event_contracts
   marks the 20 existing rows rolled_out; module and event rollout metadata
   disagree.
4. AlertWizard offers only one aws.cloudtrail sample, iam_key_created; it needs
   event-specific previews and complete/partial samples for all families.
5. rules/aws_iam.yaml detects some unprofiled actions, including
   iam.policy.create_version, iam.mfa.delete, and IAM boundary changes. Detection
   coverage is not content coverage.
6. scripts/iam_test_drive.py uses stale synthetic cloudtrail.trail.stop; the
   producer emits cloudtrail.logging.stop.

## Fixtures and test plan

Use fake IDs, accounts, and IPs.

Complete IAM attachment fixture: account 123456789012, region us-east-1,
eventID evt-iam-attach-001, eventSource iam.amazonaws.com, eventName
AttachRolePolicy, AssumedRole actor with ARN and sessionIssuer ARN, source IP,
user agent, requestParameters roleName=deploy-prod and policyArn=ReadOnlyAccess.
Assert iam.policy.attach, actor/source/account/region, policy target, and event
ID. Assert via_role and affected principal remain absent until added by the
producer.

Complete KMS policy fixture: eventSource kms.amazonaws.com, eventName
PutKeyPolicy, keyId, wildcard Principal=* policy, IAMUser actor, account/region,
source IP, and event ID. Assert kms.policy.put, kms_wildcard_policy=true, key
target, and no rendered policy body. Also test condition-scoped and
account-root policies: wildcard flag absent and no “safe” claim.

Complete CloudTrail stop fixture: eventSource cloudtrail.amazonaws.com,
eventName StopLogging, root actor, requestParameters name=security-audit,
account/region, source IP, and event ID. Assert cloudtrail.logging.stop,
trail target, root fact, and recovery cloudtrail.logging.start plus delivery
test.

Complete console fixture: eventName ConsoleLogin, IAMUser actor, MFAUsed=Yes,
ConsoleLogin=Success, source IP, user agent, account/region, and event ID.
Assert auth.console.login, success, login_kind=iam, MFA Yes, and no target line.
Add root failure with MFA No.

Complete federated fixture: eventName AssumeRoleWithSAML, eventSource
sts.amazonaws.com, SAMLUser, source IP, roleArn request parameter, account/region,
and event ID. Assert auth.federated.login, success, login_kind=sso, event_name,
and no fabricated role target until roleArn is promoted.

Partial fixture: only eventName=CreateUser, eventSource=iam.amazonaws.com, and
requestParameters userName=new-user. Render the unique headline and user target
if available; omit actor, source, account, region, event ID, error, and MFA.
Do not invent approval, root cause, impact, or recovery.

Tests required before rollout:

1. Parity for all 49 actions, with explicit future/non-notifying allowlist.
2. Complete producer fixtures for IAM identity/policy, KMS key/grant, CloudTrail,
   console, and federated login.
3. Partial fixtures for missing actor/target/account/region/event ID/MFA/request
   parameters/errors; assert omission and no placeholders.
4. Wildcard IAM, wildcard KMS, condition-scoped, account-root, and explicit
   failure fixtures.
5. Plain/email golden render for every BW-018 contract, complete and partial.
6. One chat golden render for every contract family.
7. Recovery assertions only for:
   cloudtrail.logging.stop -> cloudtrail.logging.start;
   kms.key.disable -> kms.key.enable;
   kms.key.delete_scheduled -> kms.key.delete_cancelled;
   kms.rotation.disable -> kms.rotation.enable; and MFA disable -> enable when
   observed. One-shot identity/policy changes are manual. Logins have no
   automatic recovery.
8. Ownership/UI tests for source aws.cloudtrail to owner aws.iam, visible
   producer-only gaps, unique IDs, and event-specific previews.
9. Regression tests for saved profile IDs, routes, channels, throttle/silence,
   advanced-template precedence, audit history, and existing database data.
   Producer changes must be additive.

Keep BW-018 planned until these checks pass. Then mark module and rows rolled
out together, recompute module content_gap_count after contract application,
and show producer aws.cloudtrail beside canonical owner aws.iam.

No application source, tests, rules, deployment, database, or secret files were
changed by this review; this report is the only intended artifact.

