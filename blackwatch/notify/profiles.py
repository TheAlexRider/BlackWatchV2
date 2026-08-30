"""Beginner-friendly notification profiles.

Profiles are the product-facing layer above notification rules. They describe
one module and one alert kind in plain language, then compile to the existing
rule/template dispatch path so delivery behavior remains centralized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..event import Actor, Event, Outcome, Severity, Source, Target
from .content_contracts import apply_event_contracts


PROFILE_CONTENT_FIELDS = (
    "title",
    "what_happened",
    "facts",
    "decision",
    "next_steps",
    "why_it_matters",
    "evidence",
    "monitoring_method",
    "impact",
    "recovery",
    "runbook_url",
)

_SEVERITIES = {"informational", "low", "medium", "high", "critical"}

_COMMON_AVAILABLE_FIELDS = [
    "{module}",
    "{alert_type}",
    "{target_name}",
    "{severity}",
    "{principal}",
    "{source_ip}",
    "{event_time}",
    "{evidence}",
    "{monitoring_method}",
    "{impact}",
    "{recovery_event}",
]

_SERVICE_AVAILABLE_FIELDS = [
    *_COMMON_AVAILABLE_FIELDS,
    "{service_name}",
    "{vpc}",
    "{monitor_tier}",
    "{error_signal}",
    "{latency_ms}",
    "{consecutive_failures}",
    "{consecutive_successes}",
    "{downtime}",
    "{unknown_duration}",
    "{last_report}",
    "{agent_version}",
    "{monitoring_impact}",
]

_VPN_AUTH_AVAILABLE_FIELDS = [
    "{principal}",
    "{source_ip}",
    "{target_name}",
    "{event_time}",
    "{evidence}",
    "{severity}",
    "{monitoring_method}",
    "{impact}",
]

_VPN_FAILURE_FACTS = (
    "{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% endif %}"
    "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
    "VPN server: {{ event.target.name or event.target.id or 'unknown server' }}\n"
    "When: {{ event.event_time }}\n"
    "{% if event.extra.message %}Evidence: {{ event.extra.message }}{% endif %}"
)

_VPN_FAILURE_NEXT_STEPS = (
    "{% if event.actor.principal %}1. Confirm whether {{ event.actor.principal }} initiated this login.\n"
    "{% else %}1. Identify the account associated with this login.\n{% endif %}"
    "{% if event.actor.source_ip %}2. If unexpected, investigate {{ event.actor.source_ip }} and follow the configured credential-response runbook."
    "{% else %}2. If unexpected, investigate the source and follow the configured credential-response runbook.{% endif %}"
)

_VPN_SUCCESS_FACTS = (
    "{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% endif %}"
    "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
    "VPN server: {{ event.target.name or event.target.id or 'unknown server' }}\n"
    "When: {{ event.event_time }}"
)

_COMMON_FACTS_TEMPLATE = (
    "{% if event.actor.principal %}Actor: {{ event.actor.principal }}\n{% endif %}"
    "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
    "{% if event.target.name or event.target.id %}Target: {{ event.target.name or event.target.id }}\n{% endif %}"
    "When: {{ event.event_time }}\n"
    "{% if event.extra.message %}Signal: {{ event.extra.message }}\n{% endif %}"
    "{% if event.severity %}Severity: {{ event.severity }}{% endif %}"
)


def _event(
    key: str,
    label: str,
    description: str,
    severity: str = "high",
    *,
    available_fields: list[str] | None = None,
    defaults: dict[str, str] | None = None,
    content_status: str = "generic",
    preview_sample: dict[str, Any] | None = None,
    producer_status: str | None = None,
    notification_status: str = "notifying",
    producer_keys: list[str] | None = None,
) -> dict[str, Any]:
    default_content = {
        "title": label,
        "what_happened": f"BlackWatch detected {label.lower()}.",
        "facts": _COMMON_FACTS_TEMPLATE,
        "decision": "Decide whether this event is expected and whether the owner needs to act.",
        "next_steps": "Verify the affected resource, owner, and recent changes.",
        "why_it_matters": "",
        "evidence": "",
        "monitoring_method": "",
        "impact": "",
        "recovery": "",
        "runbook_url": "",
    }
    if defaults:
        default_content.update(defaults)
    result = {
        "key": key,
        "label": label,
        "description": description,
        "default_severities": [severity],
        "available_fields": list(available_fields or _COMMON_AVAILABLE_FIELDS),
        "content_fields": list(PROFILE_CONTENT_FIELDS),
        "content_status": content_status,
        "preview_sample": dict(preview_sample or {
            "target_id": "sample-target",
            "target_name": "sample-target",
            "principal": "sample-user",
            "source_ip": "192.0.2.10",
            "event_time": "2026-08-25T10:00:00Z",
            "message": "sample monitored signal",
            "extra": {
                "service_name": "sample-service",
                "vpc": "sample-vpc",
                "monitor_tier": "service",
                "error": "sample evidence from the monitored signal",
                "error_signal": "sample health-check failure",
                "observation": "sample observation",
                "latency_ms": 240,
                "consecutive_failures": 3,
                "consecutive_successes": 4,
                "downtime_seconds": 180,
                "unknown_seconds": 90,
                "last_report": "2026-08-25T10:00:00+00:00",
                "agent_version": "sample-agent-1.0",
                "monitoring_method": "the configured module monitor",
                "monitoring_impact": "sample monitoring impact",
                "impact": "sample technical impact",
                "recovery_event": "the matching recovery event",
            },
        }),
        "defaults": default_content,
    }
    if producer_status:
        result["producer_status"] = producer_status
    result["notification_status"] = notification_status
    result["content_gap"] = notification_status == "notifying" and content_status == "generic"
    if producer_keys is not None:
        result["producer_keys"] = list(producer_keys)
    return result


def _service_event(
    key: str,
    label: str,
    description: str,
    severity: str = "high",
    *,
    defaults: dict[str, str] | None = None,
    content_status: str = "generic",
    preview_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _event(
        key,
        label,
        description,
        severity,
        available_fields=_SERVICE_AVAILABLE_FIELDS,
        defaults=defaults,
        content_status=content_status,
        preview_sample=preview_sample,
    )


_MODULE_ROLLOUT: dict[str, dict[str, str]] = {
    # Rollout order is intentional: complete the operationally important
    # authentication/availability batches before expanding to the remaining
    # AWS and security-finding modules.
    "vpn.openvpn": {
        "stage": "1-vpn",
        "status": "rolled_out",
        "why": "Unexpected VPN activity can indicate credential misuse or an account takeover attempt.",
        "next_steps": "Verify the account, source, VPN server, and recent authentication changes; follow the configured runbook if unexpected.",
        "monitoring": "OpenVPN authentication, session, and service logs on the monitored VPN server.",
        "impact": "A failed login may be benign, or may indicate an unauthorized access attempt when the user or source is unfamiliar.",
        "recovery": "A matching VPN recovery or successful-authentication event is reported separately when available.",
    },
    "ec2.host": {
        "stage": "2-ec2-ssh",
        "status": "rolled_out",
        "why": "Host authentication, privilege, and integrity changes can indicate unauthorized access or host compromise.",
        "next_steps": "Verify the host, account, process, and recent privileged changes; contain the host according to the runbook if unexpected.",
        "monitoring": "EC2 host-agent telemetry, SSH/authentication logs, process activity, and file-integrity signals.",
        "impact": "The host may be exposed, unavailable, or running an unauthorized change until the signal is explained.",
        "recovery": "A matching host recovery or normal-state event is reported separately when available.",
    },
    "aws.rds": {
        "stage": "3-rds",
        "status": "rolled_out",
        "why": "Unexpected database access, schema, or configuration changes can expose data or interrupt application workloads.",
        "next_steps": "Verify the database, actor, source, and recent change window; check dependent applications and follow the database runbook.",
        "monitoring": "RDS, database-session, proxy, and CloudTrail database activity for the monitored account.",
        "impact": "The database may be exposed, degraded, or changed in a way that affects data access and application availability.",
        "recovery": "A matching database recovery or resolved-state event is reported separately when available.",
    },
    "ecs.probe": {
        "stage": "4-ecs",
        "status": "rolled_out",
        "why": "A service health change can affect customers or dependent systems before the condition becomes a full outage.",
        "next_steps": "Check the service logs, health check, dependencies, and latest deployment; follow the service runbook.",
        "monitoring": "The configured service/probe health checks and heartbeat telemetry.",
        "impact": "The service may be unavailable, degraded, or outside reliable monitoring coverage.",
        "recovery": "BlackWatch reports the matching service or probe recovery event when the healthy condition returns.",
    },
    "aws.iam": {
        "stage": "5-iam",
        "status": "planned",
        "why": "Identity and trust-policy changes can expand access or weaken account protections.",
        "next_steps": "Verify the principal, affected identity, policy or trust change, and approved change window before escalating.",
        "monitoring": "AWS CloudTrail identity, IAM, KMS, and CloudTrail-management events.",
        "impact": "An unapproved identity change may grant access, remove a control, or reduce audit visibility.",
        "recovery": "A matching identity-control recovery or follow-up change is reported separately when available.",
    },
    "aws.s3": {
        "stage": "6-s3",
        "status": "planned",
        "why": "Bucket policy, public-access, and object-access changes can expose or alter stored data.",
        "next_steps": "Verify the bucket, actor, object, and access path; remove unintended exposure according to the storage runbook.",
        "monitoring": "S3 data and bucket-management events from the configured AWS telemetry.",
        "impact": "Stored data may be publicly readable, modified, deleted, or inaccessible to expected workloads.",
        "recovery": "A matching access-restored or exposure-resolved event is reported separately when available.",
    },
    "cert": {
        "stage": "7-certificates",
        "status": "rolled_out",
        "why": "An expired or failing certificate can break secure connections and create an avoidable outage.",
        "next_steps": "Verify the endpoint, certificate chain, expiry window, and renewal owner; follow the certificate runbook.",
        "monitoring": "Configured TLS certificate probes and expiry checks.",
        "impact": "Clients may reject the endpoint or monitoring may lose confidence in the secure connection.",
        "recovery": "A matching certificate renewal or probe-recovered event is reported separately when available.",
    },
    "ueba": {
        "stage": "8-ueba",
        "status": "planned",
        "why": "Behavior that departs from the established baseline may indicate compromised credentials or an unusual workflow.",
        "next_steps": "Verify the entity, baseline deviation, source, and recent changes with the owner before escalating.",
        "monitoring": "BlackWatch behavioral baseline and anomaly analysis.",
        "impact": "The activity may represent account misuse or an unreviewed operational change.",
        "recovery": "A matching baseline-normalized event is reported separately when available.",
    },
    "findings": {
        "stage": "9-findings",
        "status": "planned",
        "why": "A security finding identifies a condition that may require containment or owner action.",
        "next_steps": "Verify the affected resource and owner, preserve evidence, and follow the approved response runbook.",
        "monitoring": "BlackWatch security-finding ingestion and correlation.",
        "impact": "Impact depends on the affected resource and finding evidence; the finding should remain traceable until resolved.",
        "recovery": "A matching finding-resolved event is reported separately when available.",
    },
    "aws.posture": {
        "stage": "10-posture",
        "status": "planned",
        "why": "Posture drift or resource exposure can weaken preventive controls even when no incident is confirmed.",
        "next_steps": "Verify the resource, control, owner, and approved exception; remediate or document the condition according to policy.",
        "monitoring": "AWS posture checks, configuration signals, and resource-exposure findings.",
        "impact": "A preventive control may be missing or a resource may be more exposed than intended.",
        "recovery": "A matching posture-resolved event is reported separately when the control returns to the expected state.",
    },
    "aws.backup": {
        "stage": "11-platform",
        "status": "planned",
        "why": "Backup or vault changes can reduce the ability to recover systems after an incident.",
        "next_steps": "Verify the vault, recovery point, actor, retention policy, and last known-good backup.",
        "monitoring": "AWS Backup recovery-point, vault, and policy events.",
        "impact": "Recovery coverage may be reduced or a recovery point may be unavailable when needed.",
        "recovery": "A matching backup-completed or recovery-point-restored event is reported separately when available.",
    },
    "aws.efs": {
        "stage": "11-platform",
        "status": "planned",
        "why": "File-system policy and mount changes can expose shared data or interrupt dependent workloads.",
        "next_steps": "Verify the file system, mount target, security group, actor, and approved change window.",
        "monitoring": "AWS EFS file-system, mount-target, policy, and security-group events.",
        "impact": "Shared data may be exposed, inaccessible, or unavailable to connected workloads.",
        "recovery": "A matching EFS configuration-restored event is reported separately when available.",
    },
    "aws.network": {
        "stage": "11-platform",
        "status": "planned",
        "why": "Network topology or ingress changes can unexpectedly expose services or break traffic paths.",
        "next_steps": "Verify the route, gateway, peering, security-group rule, actor, and approved change window.",
        "monitoring": "AWS network, gateway, peering, transit, and security-group events.",
        "impact": "Traffic may become exposed, blocked, redirected, or unavailable to dependent systems.",
        "recovery": "A matching network-change reversal or healthy-path event is reported separately when available.",
    },
    "aws.secrets": {
        "stage": "11-platform",
        "status": "rolled_out",
        "why": "Secret lifecycle changes can break consumers or alter the credentials used to access systems.",
        "next_steps": "Verify the secret, actor, consuming service, version, and approved rotation or deletion window.",
        "monitoring": "AWS Secrets Manager lifecycle and access-management events.",
        "impact": "Applications may fail authentication or an important credential may be exposed, replaced, or unavailable.",
        "recovery": "A matching secret-restored or consumer-recovered event is reported separately when available.",
    },
    "aws.compute": {
        "stage": "11-platform",
        "status": "rolled_out",
        "why": "Compute metadata, image-sharing, or instance changes can alter host access and workload trust.",
        "next_steps": "Verify the instance or image, actor, metadata setting, sharing scope, and deployment window.",
        "monitoring": "AWS EC2 instance, AMI, and metadata-management events.",
        "impact": "A workload may be exposed to credential theft, run an unexpected image, or become unavailable.",
        "recovery": "No automatic recovery is claimed; manually resolve after the approved compute configuration, image permissions, or metadata baseline is verified.",
    },
    "aws.storage": {
        "stage": "11-platform",
        "status": "rolled_out",
        "why": "Snapshot or volume-sharing changes can expose recovery data or affect restoration plans.",
        "next_steps": "Verify the snapshot or volume, sharing scope, actor, retention policy, and approved change window.",
        "monitoring": "AWS volume, snapshot, and resource-sharing events.",
        "impact": "Stored data may be exposed, deleted, or unavailable for recovery.",
        "recovery": "No automatic recovery is claimed; manually resolve after the approved sharing or volume baseline is restored and validated.",
    },
    "aws.api_gateway": {
        "stage": "6-api-gateway",
        "status": "rolled_out",
        "why": "API Gateway authentication, server errors, scanner signals, and new sources need different operator decisions.",
        "next_steps": "Use the event-specific facts and follow the API Gateway, source-validation, or service runbook as applicable.",
        "monitoring": "API Gateway access-log normalization and source/error correlation.",
        "impact": "Impact is limited to the normalized request or aggregate facts reported by the event.",
        "recovery": "Recovery is event-specific; no automatic recovery is claimed where the producer has no matching detector.",
    },
}


def _module(key: str, label: str, description: str, *events: dict[str, Any]) -> dict[str, Any]:
    rollout = _MODULE_ROLLOUT.get(key, {})
    stage = str(rollout.get("stage") or "backlog")
    status = "rolled_out" if rollout.get("status") == "rolled_out" else "generic"
    module_events: list[dict[str, Any]] = []
    for event in events:
        event["rollout_stage"] = stage
        if status == "rolled_out" and event.get("content_status") != "rolled_out":
            defaults = event["defaults"]
            defaults.update({
                "why_it_matters": rollout["why"],
                "next_steps": rollout["next_steps"],
                "monitoring_method": rollout["monitoring"],
                "impact": rollout["impact"],
                "recovery": rollout["recovery"],
            })
            event["content_status"] = "rolled_out"
            sample = dict(event.get("preview_sample") or {})
            sample["target_name"] = sample.get("target_name") or f"{label} target"
            sample["message"] = sample.get("message") or event["description"]
            sample_extra = dict(sample.get("extra") or {})
            sample_extra.setdefault("monitoring_method", rollout["monitoring"])
            sample_extra.setdefault("impact", rollout["impact"])
            sample["extra"] = sample_extra
            event["preview_sample"] = sample
        module_events.append(event)
    return {
        "key": key,
        "label": label,
        "description": description,
        "content_status": status,
        "content_rollout_stage": stage,
        "content_gap_count": sum(bool(item.get("content_gap")) for item in module_events),
        "events": module_events,
    }


NOTIFICATION_CATALOG: list[dict[str, Any]] = [
    _module(
        "ec2.host", "EC2 Hosts", "Agent, login, privilege, file, process, and host health events.",
        _event("host.agent.stale", "Host agent stopped reporting", "A host agent has gone silent.", "high"),
        _event("host.agent.recovered", "Host agent recovered", "A previously silent host agent reported again.", "informational"),
        _event("host.auth.ssh.failure", "SSH login failed", "An SSH authentication attempt failed.", "medium"),
        _event("host.auth.ssh.password.success", "SSH password login succeeded", "An SSH password authentication succeeded.", "low"),
        _event("host.auth.ssh.success", "SSH login succeeded", "An SSH authentication succeeded.", "informational"),
        _event("host.bruteforce", "SSH brute-force activity", "Repeated SSH failures crossed the detection threshold.", "high"),
        _event("host.bruteforce.user", "SSH brute-force activity against a user", "Repeated SSH failures targeted one user.", "high"),
        _event("host.sudo.failure", "Sudo attempt failed", "A privileged command attempt failed.", "high"),
        _event("host.authorized_key.added", "SSH key added", "An authorized SSH key was added to a host.", "high"),
        _event("host.user.added", "Local user added", "A local user account was created.", "medium"),
        _event("host.port.opened", "Listening port opened", "A new listening port was observed.", "medium"),
        _event("host.fim.modified", "Protected file changed", "A monitored file was modified.", "high"),
        _event("host.fim.deleted", "Protected file deleted", "A monitored file was deleted.", "high"),
        _event("host.fim.created", "Protected file created", "A monitored file was created.", "high"),
        _event("host.fim.perm_changed", "Protected file permissions changed", "Permissions on a monitored file changed.", "high"),
        _event("host.fim.owner_changed", "Protected file owner changed", "The owner of a monitored file changed.", "high"),
        _event("host.fim.coverage", "File monitoring coverage changed", "File-integrity monitoring coverage changed.", "medium"),
        _event("host.service.added", "Host service added", "A new host service was detected.", "medium"),
        _event("host.cpu.anomaly", "CPU anomaly detected", "Host CPU behavior crossed the anomaly threshold.", "medium"),
        _event("host.cpu.normal", "CPU returned to normal", "Host CPU behavior returned to its baseline.", "informational"),
        _event("host.cron.changed", "Scheduled task changed", "A monitored cron or scheduled task changed.", "high"),
        _event("host.disk.critical", "Disk space critical", "Disk usage crossed the critical threshold.", "high"),
        _event("host.disk.warn", "Disk space warning", "Disk usage crossed the warning threshold.", "medium"),
        _event("host.disk.recovered", "Disk space recovered", "Disk usage returned below the recovery threshold.", "informational"),
        _event("host.file.changed", "Monitored file changed", "A monitored file changed.", "high"),
        _event("host.memory.exhausted", "Memory exhausted", "The host reported memory exhaustion.", "high"),
        _event("host.memory.recovered", "Memory pressure recovered", "Host memory pressure returned to normal.", "informational"),
        _event("host.oom_kill", "Process killed by OOM", "The kernel killed a process because of memory pressure.", "high"),
        _event("host.collector.stalled", "Host collector stalled", "The host collector stopped producing expected telemetry.", "high"),
        _event("host.collector.recovered", "Host collector recovered", "The host collector resumed producing telemetry.", "informational"),
        _event("host.first_seen", "Host first seen", "A host was observed for the first time.", "low"),
        _event("host.kernel.module.added", "Kernel module added", "A kernel module was added.", "high"),
        _event("host.kernel.module.removed", "Kernel module removed", "A kernel module was removed.", "high"),
        _event("host.package_db.corrupted", "Package database corrupted", "The host package database could not be read safely.", "high"),
        _event("host.package_db.recovered", "Package database recovered", "The host package database became readable again.", "informational"),
        _event("host.packages.changed", "Installed packages changed", "Installed packages changed on a host.", "medium"),
        _event("host.process.first_seen", "New process observed", "A process not previously seen on the host started.", "medium"),
        _event("host.sudoers.changed", "Sudoers configuration changed", "Sudoers configuration changed.", "high"),
        _event("host.suid.added", "SUID file added", "A new SUID file was observed.", "high"),
    ),
    _module(
        "aws.rds", "AWS RDS", "Database authentication, sessions, queries, and proxy activity.",
        _event("rds.auth.failure", "Database authentication failed", "A database authentication attempt failed.", "high"),
        _event("rds.auth.burst", "Database authentication burst", "A burst of database authentication failures was detected.", "critical"),
        _event("rds.instance.create", "Database instance created", "An RDS database instance was created.", "medium"),
        _event("rds.instance.delete", "Database instance deleted", "An RDS database instance was deleted.", "critical"),
        _event("rds.instance.modify", "Database instance changed", "An RDS database instance configuration changed.", "high"),
        _event("rds.snapshot.modify", "Database snapshot changed", "An RDS database snapshot configuration or sharing setting changed.", "high"),
        _event("rds.session.concurrent", "Concurrent session threshold reached", "Concurrent database sessions crossed the configured threshold.", "medium"),
        _event("rds.session.long_idle", "Long-idle database session", "A database session remained idle longer than expected.", "medium"),
        _event("rds.query.role", "Sensitive role query", "A query associated with a sensitive database role was observed.", "high"),
        _event("rds.query.function", "Sensitive database function used", "A monitored database function was called.", "high"),
        _event("rds.error", "Database error", "A database error was observed.", "medium"),
        _event("rds.proxy.source.new", "New database proxy source", "A new source connected through the database proxy.", "medium"),
        _event("rds.proxy.client.connect", "Database proxy client connected", "A client connected through the database proxy.", "informational"),
        _event("rds.proxy.client.disconnect", "Database proxy client disconnected", "A client disconnected from the database proxy.", "informational"),
        _event("rds.proxy.backend_hba_reject", "Database proxy backend rejected a connection", "The database backend rejected a proxy connection.", "high"),
        _event("rds.proxy.misconfig", "Database proxy misconfigured", "The database proxy reported a configuration problem.", "high"),
        _event("rds.session.start", "Database session started", "A database session started.", "informational"),
        _event("rds.session.end", "Database session ended", "A database session ended.", "informational"),
        _event("rds.session.new_source", "New database session source", "A new database session source was observed.", "medium"),
        _event("rds.query.ddl", "Database schema changed", "A database DDL statement changed schema or objects.", "high"),
        _event("rds.parameter_group.modify", "Database parameter group changed", "A database parameter group security setting changed.", "high"),
        _event("rds.user.unknown", "Unknown database user", "A database user not present in the allowlist was observed.", "high"),
    ),
    _module(
        "aws.iam", "AWS IAM", "Identity, access-key, MFA, trust-policy, KMS, and CloudTrail security events.",
        _event("iam.access_key.create", "IAM access key created", "A new IAM access key was created.", "high"),
        _event("iam.access_key.update", "IAM access key changed", "An IAM access key was changed.", "high"),
        _event("iam.access_key.delete", "IAM access key deleted", "An IAM access key was deleted.", "high"),
        _event("iam.mfa.deactivate", "IAM MFA disabled", "Multi-factor authentication was disabled.", "critical"),
        _event("iam.mfa.enable", "IAM MFA enabled", "Multi-factor authentication was enabled.", "informational"),
        _event("iam.mfa.delete", "IAM MFA device deleted", "An MFA device was deleted.", "high"),
        _event("iam.role.update_trust", "Role trust policy changed", "An IAM role trust policy was changed.", "critical"),
        _event("iam.user.create", "IAM user created", "A new IAM user was created.", "medium"),
        _event("iam.user.update", "IAM user changed", "An IAM user was changed.", "high"),
        _event("iam.user.delete", "IAM user deleted", "An IAM user was deleted.", "high"),
        _event("iam.role.create", "IAM role created", "A new IAM role was created.", "medium"),
        _event("iam.role.delete", "IAM role deleted", "An IAM role was deleted.", "high"),
        _event("iam.group.create", "IAM group created", "An IAM group was created.", "medium"),
        _event("iam.group.delete", "IAM group deleted", "An IAM group was deleted.", "high"),
        _event("iam.group.add_user", "IAM user added to group", "A user was added to an IAM group.", "high"),
        _event("iam.group.remove_user", "IAM user removed from group", "A user was removed from an IAM group.", "high"),
        _event("iam.login_profile.create", "IAM login profile created", "A console login profile was created for an IAM user.", "high"),
        _event("iam.login_profile.update", "IAM login profile changed", "An IAM console login profile was changed.", "high"),
        _event("iam.login_profile.delete", "IAM login profile deleted", "An IAM console login profile was deleted.", "high"),
        _event("iam.policy.attach", "IAM policy attached", "A policy was attached to an IAM principal.", "high"),
        _event("iam.policy.detach", "IAM policy detached", "A policy was detached from an IAM principal.", "high"),
        _event("iam.policy.put_inline", "Inline IAM policy changed", "An inline IAM policy was added or changed.", "high"),
        _event("iam.policy.delete_inline", "Inline IAM policy deleted", "An inline IAM policy was deleted.", "high"),
        _event("iam.policy.create", "IAM policy created", "A managed IAM policy was created.", "high"),
        _event("iam.policy.delete", "IAM policy deleted", "A managed IAM policy was deleted.", "high"),
        _event("iam.policy.create_version", "IAM policy version created", "A managed IAM policy version was created.", "high"),
        _event("iam.policy.delete_version", "IAM policy version deleted", "A managed IAM policy version was deleted.", "high"),
        _event("iam.role.boundary.put", "IAM role permissions boundary changed", "A permissions boundary was attached to a role.", "high"),
        _event("iam.role.boundary.delete", "IAM role permissions boundary removed", "A permissions boundary was removed from a role.", "critical"),
        _event("iam.user.boundary.put", "IAM user permissions boundary changed", "A permissions boundary was attached to a user.", "high"),
        _event("iam.user.boundary.delete", "IAM user permissions boundary removed", "A permissions boundary was removed from a user.", "critical"),
        _event("kms.key.disable", "KMS key disabled", "A KMS key was disabled.", "critical"),
        _event("kms.key.create", "KMS key created", "A KMS key was created.", "high"),
        _event("kms.key.enable", "KMS key enabled", "A KMS key was enabled.", "informational"),
        _event("kms.key.delete_scheduled", "KMS key deletion scheduled", "Deletion was scheduled for a KMS key.", "critical"),
        _event("kms.key.delete_cancelled", "KMS key deletion cancelled", "Scheduled KMS key deletion was cancelled.", "informational"),
        _event("kms.policy.put", "KMS key policy changed", "A KMS key policy was changed.", "high"),
        _event("kms.grant.create", "KMS grant created", "A grant was created for a KMS key.", "high"),
        _event("kms.grant.retire", "KMS grant retired", "A KMS grant was retired.", "informational"),
        _event("kms.grant.revoke", "KMS grant revoked", "A KMS grant was revoked.", "high"),
        _event("kms.rotation.disable", "KMS key rotation disabled", "Automatic KMS key rotation was disabled.", "critical"),
        _event("kms.rotation.enable", "KMS key rotation enabled", "Automatic KMS key rotation was enabled.", "informational"),
        _event("cloudtrail.trail.delete", "CloudTrail trail deleted", "A CloudTrail trail was deleted.", "critical"),
        _event("cloudtrail.logging.stop", "CloudTrail logging stopped", "CloudTrail logging was stopped.", "critical"),
        _event("cloudtrail.logging.start", "CloudTrail logging started", "CloudTrail logging was started.", "informational"),
        _event("cloudtrail.trail.create", "CloudTrail trail created", "A CloudTrail trail was created.", "medium"),
        _event("cloudtrail.trail.update", "CloudTrail trail changed", "A CloudTrail trail configuration changed.", "high"),
        _event("auth.console.login", "AWS console login", "An AWS console login was observed.", "informational"),
        _event("auth.federated.login", "Federated AWS login", "A federated AWS login was observed.", "informational"),
    ),
    _module(
        "aws.s3", "AWS S3", "Bucket policy, public access, and object access events.",
        _event("s3.object.access.anonymous", "Anonymous S3 object access", "An S3 object was accessed anonymously.", "high"),
        _event("s3.object.access", "S3 object accessed", "An S3 object was accessed.", "informational"),
        _event("s3.bucket.create", "S3 bucket created", "An S3 bucket was created.", "informational"),
        _event("s3.bucket.delete", "S3 bucket deleted", "An S3 bucket was deleted.", "critical"),
        _event("s3.bucket.acl.put", "S3 bucket ACL changed", "An S3 bucket ACL changed.", "high"),
        _event("s3.bucket.policy.put", "S3 bucket policy changed", "An S3 bucket policy changed.", "high"),
        _event("s3.bucket.bpa.put", "S3 public access block changed", "An S3 public access block setting changed.", "high"),
        _event("s3.bucket.bpa.delete", "S3 public access block removed", "An S3 public access block setting was removed.", "critical"),
        _event("s3.bucket.public", "S3 bucket became public", "A bucket public-access control changed.", "critical"),
        _event("s3.bucket.public_removed", "S3 bucket public access removed", "A bucket was no longer publicly accessible.", "informational"),
        _event("s3.bucket.encryption.delete", "S3 bucket encryption removed", "Default encryption was removed from an S3 bucket.", "high"),
        _event("s3.bucket.encryption.put", "S3 bucket encryption changed", "Default encryption was changed on an S3 bucket.", "medium"),
        _event("s3.bucket.encryption_added", "S3 bucket encryption restored", "A bucket returned from no default encryption to an encrypted state.", "informational"),
        _event("s3.bucket.versioning.put", "S3 bucket versioning changed", "S3 bucket versioning was enabled or changed.", "medium"),
        _event("s3.bucket.versioning_suspended", "S3 bucket versioning suspended", "S3 bucket versioning was suspended.", "high"),
        _event("s3.bucket.versioning_enabled", "S3 bucket versioning enabled", "S3 bucket versioning was enabled.", "informational"),
        _event("s3.bucket.versioning_off", "S3 bucket versioning disabled", "S3 bucket versioning was disabled.", "high"),
        _event("s3.bucket.logging.put", "S3 bucket logging changed", "S3 bucket access logging changed.", "high"),
        _event("s3.bucket.logging_disabled", "S3 bucket logging disabled", "S3 bucket access logging was disabled.", "high"),
        _event("s3.bucket.policy.delete", "S3 bucket policy deleted", "An S3 bucket policy was deleted.", "high"),
        _event("s3.bucket.lifecycle.put", "S3 bucket lifecycle changed", "An S3 bucket lifecycle configuration changed.", "medium"),
        _event("s3.bucket.replication.put", "S3 bucket replication changed", "An S3 bucket replication configuration changed.", "high"),
        _event("s3.bucket.replication.delete", "S3 bucket replication removed", "An S3 bucket replication configuration was removed.", "high"),
        _event("s3.bucket.object_lock.put", "S3 object lock changed", "An S3 object-lock configuration changed.", "high"),
        _event("s3.bucket.unencrypted", "Unencrypted S3 bucket detected", "An S3 bucket was observed without expected encryption.", "high"),
        _event("s3.bucket.first_seen", "S3 bucket first seen", "An S3 bucket was observed for the first time.", "low"),
        _event("s3.bucket.disappeared", "S3 bucket disappeared", "A previously observed S3 bucket was not found.", "high"),
    ),
    _module(
        "aws.api_gateway", "API Gateway", "API authentication, errors, scanners, bursts, and new sources.",
        _event("api.auth.failure", "API authentication failed", "An API authentication request failed.", "medium"),
        _event("api.auth.burst", "API authentication burst", "A burst of API authentication failures was detected.", "high"),
        _event("api.error", "API error", "An API request returned an error.", "medium"),
        _event("api.error.burst", "API error burst", "An unusual burst of API errors was detected.", "high"),
        _event("api.scanner_ua", "Scanner user agent detected", "A known scanner-like user agent was observed.", "medium"),
        _event("api.source.new", "New API source", "A new API client source was observed.", "low"),
    ),
    _module(
        "aws.posture", "AWS Posture", "Security posture drift and resource exposure findings.",
        _event("network.sg.instance_attach", "Security group attached", "A security group attachment changed.", "high", producer_status="producer", producer_keys=["network.sg.instance_attach"]),
        _event("posture.finding.open", "Posture finding opened", "A posture finding became active.", "high", notification_status="non_notifying", producer_status="future", producer_keys=[]),
        _event("aws.posture.finding.new", "New posture finding", "A new posture finding was detected.", "high", producer_status="projection", producer_keys=["aws.posture.finding"]),
        _event("aws.posture.finding.resolved", "Posture finding resolved", "A posture finding was resolved.", "informational", producer_status="projection", producer_keys=["aws.posture.scan.completed"]),
    ),
    _module(
        "aws.backup", "AWS Backup", "Backup recovery-point and vault policy changes.",
        _event("backup.vault.create", "Backup vault created", "A backup vault was created.", "medium"),
        _event("backup.recovery_point.delete", "Backup recovery point deleted", "A backup recovery point was deleted.", "critical"),
        _event("backup.vault.delete", "Backup vault deleted", "A backup vault was deleted.", "critical"),
        _event("backup.vault.policy.delete", "Backup vault policy deleted", "A backup vault policy was deleted.", "high"),
        _event("backup.vault.policy.put", "Backup vault policy changed", "A backup vault policy changed.", "high"),
        _event("backup.copy_job.start", "Backup copy job started", "A backup copy job started.", "medium"),
    ),
    _module(
        "aws.efs", "AWS EFS", "File-system policy, mount target, and security-group changes.",
        _event("efs.filesystem.create", "EFS file system created", "An EFS file system was created.", "medium"),
        _event("efs.filesystem.policy.delete", "EFS policy deleted", "An EFS file-system policy was deleted.", "high"),
        _event("efs.filesystem.policy.put", "EFS policy changed", "An EFS file-system policy changed.", "high"),
        _event("efs.mount_target.create", "EFS mount target created", "An EFS mount target was created.", "medium"),
        _event("efs.mount_target.delete", "EFS mount target deleted", "An EFS mount target was deleted.", "high"),
        _event("efs.mount_target.sg.modify", "EFS mount security group changed", "An EFS mount target security group changed.", "high"),
        _event("efs.filesystem.delete", "EFS file system deleted", "An EFS file system was deleted.", "critical"),
    ),
    _module(
        "aws.network", "AWS Network", "Internet gateway, peering, and transit-network changes.",
        _event("network.igw.attach", "Internet gateway attached", "An internet gateway was attached.", "high"),
        _event("network.peering.accept", "Network peering accepted", "A network peering request was accepted.", "high"),
        _event("network.tgw_peering.accept", "Transit gateway peering accepted", "Transit gateway peering was accepted.", "high"),
        _event("network.sg.ingress.add", "Network ingress rule added", "An inbound security-group rule was added.", "high"),
    ),
    _module(
        "aws.secrets", "AWS Secrets", "Secrets creation, update, restore, and deletion.",
        _event("secrets.secret.create", "Secret created", "A new secret was created.", "medium", available_fields=["{secret_name}", "{secret_arn}", "{description}", "{kms_key_id}", "{version_stages}", "{change_type}", "{account}", "{region}", "{principal}", "{event_time}"], producer_status="normalized"),
        _event("secrets.secret.update", "Secret updated", "A secret value or metadata was updated.", "high", available_fields=["{secret_name}", "{secret_arn}", "{description}", "{kms_key_id}", "{version_id}", "{version_stages}", "{rotation_enabled}", "{rotation_days}", "{change_type}", "{account}", "{region}", "{principal}", "{event_time}"], producer_status="normalized"),
        _event("secrets.secret.restore", "Secret restored", "A deleted secret was restored.", "medium", available_fields=["{secret_name}", "{secret_arn}", "{recovery_window_days}", "{change_type}", "{account}", "{region}", "{principal}", "{event_time}"], producer_status="normalized"),
        _event("secrets.secret.delete", "Secret deleted", "A secret was deleted.", "critical", available_fields=["{secret_name}", "{secret_arn}", "{recovery_window_days}", "{force_delete}", "{change_type}", "{account}", "{region}", "{principal}", "{event_time}"], producer_status="normalized"),
    ),
    _module(
        "aws.compute", "AWS Compute", "EC2, AMI, and instance security configuration changes.",
        _event("compute.imds.modify", "EC2 metadata settings changed", "Instance metadata settings changed.", "high", available_fields=["{instance_id}", "{http_tokens}", "{http_endpoint}", "{http_put_response_hop_limit}", "{http_protocol_ipv4}", "{http_protocol_ipv6}", "{instance_metadata_tags}", "{imdsv1_enabled}", "{account}", "{region}", "{principal}", "{event_time}"], content_status="rolled_out", producer_status="normalized"),
        _event("compute.ami.modify", "AMI sharing or visibility changed", "An AMI sharing or visibility setting changed.", "high", available_fields=["{image_id}", "{ami_public}", "{ami_shared_accounts}", "{ami_removed_accounts}", "{ami_made_public}", "{ami_cross_account_share}", "{account}", "{region}", "{principal}", "{event_time}"], content_status="rolled_out", producer_status="normalized"),
        _event("compute.instance.modify", "EC2 instance configuration changed", "An EC2 instance configuration changed.", "medium", available_fields=["{instance_id}", "{instance_type}", "{source_dest_check}", "{account}", "{region}", "{principal}", "{event_time}"], content_status="rolled_out", producer_status="normalized"),
    ),
    _module(
        "aws.storage", "AWS Storage", "Snapshot, volume, and resource-sharing changes.",
        _event("storage.snapshot.modify", "EBS snapshot sharing changed", "An EBS snapshot sharing permission changed.", "high", available_fields=["{snapshot_id}", "{volume_id}", "{snapshot_share_scope}", "{snapshot_shared_accounts}", "{snapshot_public}", "{snapshot_removed_accounts}", "{snapshot_removed_public}", "{snapshot_share_scope_before}", "{snapshot_share_scope_current}", "{snapshot_shared_accounts_before}", "{snapshot_shared_accounts_current}", "{encrypted}", "{kms_key_id}", "{account}", "{region}", "{principal}", "{event_time}"], content_status="rolled_out", producer_status="normalized"),
    ),
    _module(
        "vpn.openvpn", "OpenVPN", "VPN service, authentication, sessions, and brute-force activity.",
        _event("vpn.service.down", "VPN service down", "The VPN service reported a down state.", "critical"),
        _event(
            "vpn.auth.failure",
            "VPN login failed",
            "A VPN authentication attempt failed.",
            "medium",
            available_fields=_VPN_AUTH_AVAILABLE_FIELDS,
            content_status="rolled_out",
            preview_sample={
                "principal": "atharva.kale",
                "source_ip": "107.197.154.253",
                "target_name": "VPN server vpn-1",
                "event_time": "2026-08-25T04:06:21.424277Z",
                "message": "VPN authentication FAILED",
            },
            defaults={
                "title": "VPN login failed · {severity}",
                "what_happened": "A VPN login failed.",
                "facts": _VPN_FAILURE_FACTS,
                "next_steps": _VPN_FAILURE_NEXT_STEPS,
                "why_it_matters": "An unexpected failure can indicate credential misuse or an attempted account takeover.",
                "monitoring_method": "OpenVPN authentication logs on the monitored VPN server.",
            },
        ),
        _event("vpn.bruteforce", "VPN brute-force activity", "Repeated VPN authentication failures were detected.", "high"),
        _event("vpn.session.concurrent", "Concurrent VPN sessions high", "Concurrent VPN sessions crossed the configured threshold.", "medium"),
        _event("vpn.cert.expired", "VPN certificate expired", "A VPN certificate expired.", "critical"),
        _event("vpn.cert.probe.failed", "VPN certificate probe failed", "A VPN certificate check could not complete.", "high"),
        _event("vpn.cert.expiring.critical", "VPN certificate expires soon", "A VPN certificate is critically close to expiry.", "critical"),
        _event("vpn.cert.expiring.high", "VPN certificate expiry warning", "A VPN certificate is approaching expiry.", "high"),
        _event("vpn.cert.expiring.warning", "VPN certificate expiry notice", "A VPN certificate entered its warning window.", "medium"),
        _event(
            "vpn.auth.success",
            "VPN login succeeded",
            "A VPN authentication attempt succeeded.",
            "informational",
            available_fields=_VPN_AUTH_AVAILABLE_FIELDS,
            content_status="rolled_out",
            preview_sample={
                "principal": "atharva.kale",
                "source_ip": "107.197.154.253",
                "target_name": "VPN server vpn-1",
                "event_time": "2026-08-25T04:06:21.424277Z",
            },
            defaults={
                "title": "VPN login succeeded",
                "what_happened": "A VPN login succeeded.",
                "facts": _VPN_SUCCESS_FACTS,
                "next_steps": "No action is required unless this login was unexpected; verify the user and source if it was not planned.",
                "monitoring_method": "OpenVPN authentication logs on the monitored VPN server.",
            },
        ),
        _event("vpn.bruteforce.user", "VPN brute-force activity against a user", "Repeated VPN authentication failures targeted one user.", "high"),
        _event("vpn.service.up", "VPN service recovered", "The VPN service recovered.", "informational"),
        _event("vpn.session.start", "VPN session started", "A VPN session started.", "informational"),
        _event("vpn.session.end", "VPN session ended", "A VPN session ended.", "informational"),
    ),
    _module(
        "ecs.probe", "Services and Probes", "Service availability, degradation, recovery, and monitoring-agent health.",
        _service_event("service.down", "Service went down", "A monitored service crossed the down threshold.", "high", defaults={
            "title": "{service_name} is down in {vpc}",
            "what_happened": "{service_name} failed its health check after {consecutive_failures} consecutive failures.",
            "why_it_matters": "Customers or dependent systems may be unable to use {service_name}.",
            "evidence": "Error signal: {error_signal}; latency: {latency_ms} ms; downtime: {downtime}.",
            "monitoring_method": "Checked by {monitoring_method} at the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Check the service logs and dependencies, confirm the failing health check, and follow the service runbook.",
            "recovery": "BlackWatch will report recovery after {consecutive_successes} consecutive successful checks.",
        }),
        _service_event("service.degraded", "Service degraded", "A monitored service reported degraded health.", "medium", defaults={
            "title": "{service_name} is degraded in {vpc}",
            "what_happened": "{service_name} is responding, but its health signal is degraded.",
            "why_it_matters": "The service may be slow or partially unavailable before a full outage.",
            "evidence": "Error signal: {error_signal}; latency: {latency_ms} ms; failures: {consecutive_failures}.",
            "monitoring_method": "Checked by {monitoring_method} at the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Review latency, errors, capacity, and dependencies before the condition becomes an outage.",
            "recovery": "BlackWatch will report recovery after {consecutive_successes} consecutive successful checks.",
        }),
        _service_event("service.unknown", "Service state unknown", "A monitored service could not be classified reliably.", "medium", defaults={
            "title": "{service_name} state is unknown in {vpc}",
            "what_happened": "BlackWatch could not determine the current state of {service_name}.",
            "why_it_matters": "Monitoring may be unable to confirm whether the service is healthy.",
            "evidence": "Last report: {last_report}; error signal: {error_signal}; unknown duration: {unknown_duration}.",
            "monitoring_method": "Checked by {monitoring_method} at the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Check the probe, service endpoint, network path, and most recent heartbeat.",
            "recovery": "BlackWatch will report a known state when a valid service result is received.",
        }),
        _service_event("service.up", "Service recovered", "A previously unhealthy service recovered.", "informational", defaults={
            "title": "{service_name} recovered in {vpc}",
            "what_happened": "{service_name} passed its health check after {consecutive_successes} consecutive successes.",
            "why_it_matters": "The monitored service is responding again, but the incident should still be reviewed.",
            "evidence": "Last report: {last_report}; latency: {latency_ms} ms; previous downtime: {downtime}.",
            "monitoring_method": "Checked by {monitoring_method} at the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Confirm the service is stable and review the incident timeline for the cause.",
            "recovery": "This is the recovery notification for the earlier service condition.",
        }),
        _service_event("probe.agent.stale", "Probe agent stopped reporting", "A probe agent stopped reporting and monitoring coverage is offline.", "critical", defaults={
            "title": "Probe agent for {service_name} is stale",
            "what_happened": "No heartbeat has been received since {last_report}.",
            "why_it_matters": "BlackWatch cannot reliably monitor {service_name} while this probe is silent.",
            "evidence": "Last report: {last_report}; monitoring method: {monitoring_method}; signal: {error_signal}.",
            "monitoring_method": "Expected heartbeat from the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Check the probe process, host connectivity, credentials, and its last reported error.",
            "recovery": "BlackWatch will report when the probe sends a heartbeat again.",
        }),
        _service_event("probe.agent.recovered", "Probe agent recovered", "A previously silent probe agent reported again.", "informational", defaults={
            "title": "Probe agent for {service_name} recovered",
            "what_happened": "The probe reported again after being silent.",
            "why_it_matters": "Monitoring coverage for {service_name} is available again.",
            "evidence": "Last report: {last_report}; agent version: {agent_version}.",
            "monitoring_method": "Heartbeat received from the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Confirm the probe remains healthy and review the silence interval if it was unexpected.",
            "recovery": "This is the recovery notification for the earlier stale-probe condition.",
        }),
        _service_event("probe.agent.first_seen", "New probe agent detected", "A probe agent reported for the first time.", "low", defaults={
            "title": "New probe agent for {service_name} detected",
            "what_happened": "A new probe heartbeat was received from {vpc}.",
            "why_it_matters": "A new monitoring source is now contributing to service coverage.",
            "evidence": "Last report: {last_report}; agent version: {agent_version}.",
            "monitoring_method": "Heartbeat received from the {monitor_tier} monitoring tier.",
            "impact": "{monitoring_impact}",
            "next_steps": "Confirm that this probe is expected and assigned to the correct service and environment.",
            "recovery": "No recovery event is required for a first-seen probe.",
        }),
    ),
    _module(
        "cert", "TLS Certificates", "Certificate expiration and probe failures.",
        _event("cert.expired", "Certificate expired", "A monitored certificate has expired.", "critical"),
        _event("cert.expiring.critical", "Certificate expires soon", "A monitored certificate is close to expiry.", "critical"),
        _event("cert.expiring.high", "Certificate expiry warning", "A monitored certificate is approaching expiry.", "high"),
        _event("cert.expiring.warning", "Certificate expiry notice", "A monitored certificate entered its warning window.", "medium"),
        _event("cert.probe.failed", "Certificate probe failed", "A certificate check could not complete.", "high"),
    ),
    _module(
        "ueba", "UEBA", "Behavior baselines and anomaly signals.",
        _event("<category>.anomaly.first_seen_*", "New behavior value observed", "A UEBA baseline observed a new category-specific value.", "high", producer_status="runtime_pattern"),
    ),
    _module(
        "findings", "Security Findings", "Malware, custom, and externally supplied security findings.",
        _event("finding.malware.detected", "Malware detected", "A malware finding was reported.", "critical"),
        _event("<finding>.detected", "Security finding detected", "A typed or custom finding/webhook reported a detected condition.", "high", producer_status="runtime_pattern"),
    ),
]

# Producer inventory is deliberately exposed to Notification Studio so a
# producer-only input cannot be mistaken for a separately notifying event.
_POSTURE_CATALOG = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.posture")
_POSTURE_CATALOG["producer_event_inventory"] = {
    "network.sg.instance_attach": "producer: notifying",
    "aws.posture.finding": "producer-only: projection input",
    "aws.posture.scan.completed": "producer-only: reconciliation input",
    "posture.finding.open": "future: not emitted by reviewed producer path",
}

# CloudTrail currently emits these network actions, but BW-027 only gives
# notifying contracts to the four high-value paths below. Keep every other
# producer action explicit so coverage cannot silently drift as the adapter
# grows; these entries are intentionally non-notifying until their contracts
# are designed and reviewed.
_NETWORK_CATALOG = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.network")
_NETWORK_CATALOG["producer_event_inventory"] = {
    "network.sg.egress.add": "future: non-notifying pending contract",
    "network.sg.ingress.remove": "future: non-notifying pending contract",
    "network.sg.egress.remove": "future: non-notifying pending contract",
    "network.sg.create": "future: non-notifying pending contract",
    "network.sg.delete": "future: non-notifying pending contract",
    "network.vpc.create": "future: non-notifying pending contract",
    "network.vpc.delete": "future: non-notifying pending contract",
    "network.vpc.modify": "future: non-notifying pending contract",
    "network.subnet.create": "future: non-notifying pending contract",
    "network.subnet.delete": "future: non-notifying pending contract",
    "network.igw.create": "future: non-notifying pending contract",
    "network.igw.delete": "future: non-notifying pending contract",
    "network.igw.detach": "future: non-notifying pending contract",
    "network.nat.create": "future: non-notifying pending contract",
    "network.nat.delete": "future: non-notifying pending contract",
    "network.route_table.create": "future: non-notifying pending contract",
    "network.route_table.delete": "future: non-notifying pending contract",
    "network.route_table.associate": "future: non-notifying pending contract",
    "network.route.create": "future: non-notifying pending contract",
    "network.route.delete": "future: non-notifying pending contract",
    "network.route.replace": "future: non-notifying pending contract",
    "network.nacl.entry.create": "future: non-notifying pending contract",
    "network.nacl.entry.replace": "future: non-notifying pending contract",
    "network.nacl.entry.delete": "future: non-notifying pending contract",
    "network.peering.create": "future: non-notifying pending contract",
    "network.peering.delete": "future: non-notifying pending contract",
    "network.tgw_peering.create": "future: non-notifying pending contract",
}

_SECRETS_CATALOG = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.secrets")
_SECRETS_CATALOG["producer_event_inventory"] = {
    "secrets.secret.get_value": "future: non-notifying raw secret access",
}

_STORAGE_CATALOG = next(item for item in NOTIFICATION_CATALOG if item["key"] == "aws.storage")
_STORAGE_CATALOG["producer_event_inventory"] = {
    "storage.volume.modify": "future: non-notifying EBS volume lifecycle/configuration action",
    "storage.volume.create": "future: non-notifying EBS volume lifecycle action",
    "storage.snapshot.delete": "future: non-notifying EBS snapshot lifecycle action",
}


# Module-level rollout metadata supplies navigation and backwards-compatible
# defaults. These event contracts are the final content authority for the
# three approved modules, so every message has its own facts, decision,
# actions, evidence, impact, and recovery semantics.
apply_event_contracts(NOTIFICATION_CATALOG, PROFILE_CONTENT_FIELDS)


_TOKEN_MAP = {
    "{module}": "{{ event.source.module }}",
    "{alert_type}": "{{ event.action }}",
    "{target_name}": "{{ event.target.name or event.target.id or 'unknown target' }}",
    "{{target_name}}": "{{ event.target.name or event.target.id or 'unknown target' }}",
    "{severity}": "{{ event.severity or 'unscored' }}",
    "{principal}": "{{ event.actor.principal or 'unknown principal' }}",
    "{source_ip}": "{{ event.actor.source_ip or 'unknown source' }}",
    "{event_time}": "{{ event.event_time }}",
    "{evidence}": "{{ event.extra.evidence or event.extra.error or event.extra.observation or event.extra.message or 'no additional evidence' }}",
    "{monitoring_method}": "{{ event.extra.monitoring_method or 'configured monitor' }}",
    "{impact}": "{{ event.extra.impact or 'impact not specified' }}",
    "{recovery_event}": "{{ event.extra.recovery_event or 'the matching recovery event' }}",
    "{service_name}": "{{ event.extra.service_name or event.target.name or event.target.id or 'unknown service' }}",
    "{vpc}": "{{ event.extra.vpc or 'unknown environment' }}",
    "{monitor_tier}": "{{ event.extra.monitor_tier or 'service' }}",
    "{error_signal}": "{{ event.extra.error_signal or event.extra.error or event.extra.observation or 'no error signal' }}",
    "{latency_ms}": "{{ event.extra.latency_ms if event.extra.latency_ms is not none else 'unknown' }}",
    "{consecutive_failures}": "{{ event.extra.consecutive_failures if event.extra.consecutive_failures is not none else 'unknown' }}",
    "{consecutive_successes}": "{{ event.extra.consecutive_successes if event.extra.consecutive_successes is not none else 'unknown' }}",
    "{downtime}": "{{ event.extra.downtime_seconds if event.extra.downtime_seconds is not none else 'unknown' }} seconds",
    "{unknown_duration}": "{{ event.extra.unknown_seconds if event.extra.unknown_seconds is not none else 'unknown' }} seconds",
    "{age_seconds}": "{{ event.extra.age_seconds if event.extra.age_seconds is not none else 'not reported' }} seconds",
    "{last_report}": "{{ event.extra.last_report or 'unknown' }}",
    "{agent_version}": "{{ event.extra.agent_version or 'unknown' }}",
    "{monitoring_impact}": "{{ event.extra.monitoring_impact or event.extra.impact or 'monitoring impact not specified' }}",
    "{server}": "{{ event.extra.server or event.target.name or event.target.id or 'unknown server' }}",
    "{previous_state}": "{{ event.extra.prev_active if event.extra.prev_active is not none else 'not reported' }}",
    "{current_state}": "{{ event.extra.active if event.extra.active is not none else 'not reported' }}",
    "{common_name}": "{{ event.extra.common_name or 'not reported' }}",
    "{identity}": "{{ event.extra.identity or event.actor.principal or 'not reported' }}",
    "{source_ips}": "{{ event.extra.source_ips | join(', ') if event.extra.source_ips else 'not reported' }}",
    "{count_in_window}": "{{ event.extra.count_in_window or event.extra.failure_count or 'not reported' }}",
    "{threshold}": "{{ event.extra.threshold or 'not reported' }}",
    "{window_seconds}": "{{ event.extra.window_seconds or 'not reported' }}",
    "{window_minutes}": "{{ event.extra.window_minutes or 'not reported' }}",
    "{certificate_subject}": "{{ event.extra.subject or 'not reported' }}",
    "{issuer}": "{{ event.extra.issuer or 'not reported' }}",
    "{sans}": "{{ event.extra.sans | join(', ') if event.extra.sans else 'not reported' }}",
    "{days_remaining}": "{{ event.extra.days_remaining if event.extra.days_remaining is not none else 'not reported' }}",
    "{not_after}": "{{ event.extra.not_after or 'not reported' }}",
    "{certificate_path}": "{{ event.extra.path or 'not reported' }}",
    "{certificate_error}": "{{ event.extra.error or 'not reported' }}",
    "{secret_name}": "{{ event.extra.secret_name or event.target.name or event.target.id }}",
    "{secret_arn}": "{{ event.extra.secret_arn or '' }}",
    "{description}": "{{ event.extra.description or '' }}",
    "{kms_key_id}": "{{ event.extra.kms_key_id or '' }}",
    "{version_id}": "{{ event.extra.version_id or '' }}",
    "{version_stages}": "{{ event.extra.version_stages | join(', ') if event.extra.version_stages else '' }}",
    "{rotation_enabled}": "{{ event.extra.rotation_enabled if event.extra.rotation_enabled is not none else '' }}",
    "{rotation_days}": "{{ event.extra.rotation_days if event.extra.rotation_days is not none else '' }}",
    "{recovery_window_days}": "{{ event.extra.recovery_window_days if event.extra.recovery_window_days is not none else '' }}",
    "{force_delete}": "{{ event.extra.force_delete if event.extra.force_delete is not none else '' }}",
    "{secret_name}": "{{ event.extra.secret_name or event.target.name or event.target.id }}",
    "{secret_arn}": "{{ event.extra.secret_arn or '' }}",
    "{description}": "{{ event.extra.description or '' }}",
    "{kms_key_id}": "{{ event.extra.kms_key_id or '' }}",
    "{version_id}": "{{ event.extra.version_id or '' }}",
    "{version_stages}": "{{ event.extra.version_stages | join(', ') if event.extra.version_stages else '' }}",
    "{rotation_enabled}": "{{ event.extra.rotation_enabled if event.extra.rotation_enabled is not none else '' }}",
    "{rotation_days}": "{{ event.extra.rotation_days if event.extra.rotation_days is not none else '' }}",
    "{recovery_window_days}": "{{ event.extra.recovery_window_days if event.extra.recovery_window_days is not none else '' }}",
    "{force_delete}": "{{ event.extra.force_delete if event.extra.force_delete is not none else '' }}",
    "{instance_id}": "{{ event.extra.instance_id or 'not reported' }}",
    "{image_id}": "{{ event.extra.image_id or '' }}",
    "{http_tokens}": "{{ event.extra.http_tokens or '' }}",
    "{http_endpoint}": "{{ event.extra.http_endpoint or '' }}",
    "{http_put_response_hop_limit}": "{{ event.extra.http_put_response_hop_limit if event.extra.http_put_response_hop_limit is not none else '' }}",
    "{http_protocol_ipv4}": "{{ event.extra.http_protocol_ipv4 or '' }}",
    "{http_protocol_ipv6}": "{{ event.extra.http_protocol_ipv6 or '' }}",
    "{instance_metadata_tags}": "{{ event.extra.instance_metadata_tags or '' }}",
    "{imdsv1_enabled}": "{{ event.extra.imdsv1_enabled if event.extra.imdsv1_enabled is not none else '' }}",
    "{ami_public}": "{{ event.extra.ami_public if event.extra.ami_public is not none else '' }}",
    "{ami_shared_accounts}": "{{ event.extra.ami_shared_accounts | join(', ') if event.extra.ami_shared_accounts else '' }}",
    "{ami_removed_accounts}": "{{ event.extra.ami_removed_accounts | join(', ') if event.extra.ami_removed_accounts else '' }}",
    "{ami_made_public}": "{{ event.extra.ami_made_public if event.extra.ami_made_public is not none else '' }}",
    "{ami_cross_account_share}": "{{ event.extra.ami_cross_account_share | join(', ') if event.extra.ami_cross_account_share else '' }}",
    "{instance_type}": "{{ event.extra.instance_type or '' }}",
    "{source_dest_check}": "{{ event.extra.source_dest_check if event.extra.source_dest_check is not none else '' }}",
    "{last_report}": "{{ event.extra.last_report or 'not reported' }}",
    "{agent_version}": "{{ event.extra.agent_version or 'not reported' }}",
    "{collector}": "{{ event.extra.collector or 'not reported' }}",
    "{user}": "{{ event.extra.user or event.actor.principal or 'not reported' }}",
    "{path}": "{{ event.extra.path or 'not reported' }}",
    "{change_type}": "{{ event.extra.change_type or 'not reported' }}",
    "{hash}": "{{ event.extra.hash or 'not reported' }}",
    "{owner}": "{{ event.extra.owner or 'not reported' }}",
    "{value}": "{{ event.extra.value if event.extra.value is not none else 'not reported' }}",
    "{baseline}": "{{ event.extra.baseline if event.extra.baseline is not none else 'not reported' }}",
    "{duration_seconds}": "{{ event.extra.duration_seconds if event.extra.duration_seconds is not none else 'not reported' }}",
    "{mount}": "{{ event.extra.mount or 'not reported' }}",
    "{process}": "{{ event.extra.process or 'not reported' }}",
    "{pid}": "{{ event.extra.pid or 'not reported' }}",
    "{kernel_module}": "{{ event.extra.module or 'not reported' }}",
    "{package}": "{{ event.extra.package or 'not reported' }}",
    "{error}": "{{ event.extra.error or 'not reported' }}",
    "{port}": "{{ event.extra.port or 'not reported' }}",
    "{service_name}": "{{ event.extra.service_name or event.extra.service or 'not reported' }}",
    "{state}": "{{ event.extra.state or 'not reported' }}",
    "{db_instance}": "{{ event.extra.db_instance or event.target.name or event.target.id or 'not reported' }}",
    "{database}": "{{ event.extra.database or event.extra.db_name or 'not reported' }}",
    "{session_id}": "{{ event.extra.session_id or 'not reported' }}",
    "{idle_hours}": "{{ event.extra.idle_hours if event.extra.idle_hours is not none else 'not reported' }}",
    "{reason}": "{{ event.extra.reason or 'not reported' }}",
    "{source_port}": "{{ event.extra.source_port or 'not reported' }}",
    "{change}": "{{ event.extra.change or event.extra.message or 'not reported' }}",
    "{query}": "{{ event.extra.query or 'not captured' }}",
    "{function}": "{{ event.extra.function or 'not reported' }}",
    "{role}": "{{ event.extra.role or 'not reported' }}",
    "{object}": "{{ event.extra.object or 'not reported' }}",
    "{trigger}": "{{ event.extra.trigger or 'not reported' }}",
    "{account}": "{{ event.source.account or event.extra.account or 'not reported' }}",
    "{region}": "{{ event.source.region or event.extra.region or 'not reported' }}",
    "{event_name}": "{{ event.extra.event_name or event.action }}",
    "{error_code}": "{{ event.extra.error_code or 'not reported' }}",
    "{mfa_used}": "{{ event.extra.mfa_used or 'not reported' }}",
    "{user_agent}": "{{ event.actor.user_agent or event.extra.user_agent or 'not reported' }}",
    "{operation}": "{{ event.extra.operation or 'not reported' }}",
    "{http_status}": "{{ event.extra.http_status or 'not reported' }}",
    "{bytes_sent}": "{{ event.extra.bytes_sent if event.extra.bytes_sent is not none else 'not reported' }}",
    "{auth_type}": "{{ event.extra.auth_type or 'not reported' }}",
    "{public}": "{{ event.extra.public if event.extra.public is not none else 'not reported' }}",
    "{public_reasons}": "{{ event.extra.public_reasons | join(', ') if event.extra.public_reasons else 'not reported' }}",
    "{encryption}": "{{ event.extra.encryption or 'not reported' }}",
    "{versioning}": "{{ event.extra.versioning or 'not reported' }}",
    "{api_name}": "{{ event.extra.api_name }}",
    "{method}": "{{ event.extra.method }}",
    "{route_key}": "{{ event.extra.route_key }}",
    "{status}": "{{ event.extra.status if event.extra.status is not none else '' }}",
    "{integration_status}": "{{ event.extra.integration_status if event.extra.integration_status is not none else '' }}",
    "{response_length}": "{{ event.extra.response_length if event.extra.response_length is not none else '' }}",
    "{response_latency_ms}": "{{ event.extra.response_latency_ms if event.extra.response_latency_ms is not none else '' }}",
    "{request_id}": "{{ event.extra.request_id }}",
    "{scanner_signature}": "{{ event.extra.scanner_signature }}",
    "{error_message}": "{{ event.extra.error_message }}",
    "{dimension}": "{{ event.extra.dimension }}",
    "{baseline_value}": "{{ event.extra.baseline_value }}",
    "{principal_type}": "{{ event.extra.principal_type }}",
    "{source_country}": "{{ event.extra.source_country }}",
    "{source_asn}": "{{ event.extra.source_asn }}",
    "{user_agent_family}": "{{ event.extra.user_agent_family }}",
    "{hour_of_day}": "{{ event.extra.hour_of_day }}",
    "{trigger_action}": "{{ event.extra.trigger_action }}",
    "{trigger_event_id}": "{{ event.extra.trigger_event_id }}",
    "{signature}": "{{ event.extra.signature }}",
    "{detection}": "{{ event.extra.detection }}",
    "{resource}": "{{ event.extra.resource or event.target.id or event.target.name }}",
    "{object_path}": "{{ event.extra.object_path }}",
    "{file_hash}": "{{ event.extra.file_hash }}",
    "{scan_time}": "{{ event.extra.scan_time }}",
    "{engine}": "{{ event.extra.engine }}",
    "{confidence}": "{{ event.extra.confidence }}",
    "{containment_state}": "{{ event.extra.containment_state }}",
    "{owner}": "{{ event.extra.owner }}",
    "{vendor}": "{{ event.source.vendor }}",
    "{finding_type}": "{{ event.extra.finding_type }}",
    "{finding_id}": "{{ event.extra.finding_id }}",
    "{recovery_point_arn}": "{{ event.extra.recovery_point_arn }}",
    "{resource_arn}": "{{ event.extra.resource_arn }}",
    "{vault_name}": "{{ event.extra.vault_name }}",
    "{vault_arn}": "{{ event.extra.vault_arn }}",
    "{source_vault_arn}": "{{ event.extra.source_vault_arn }}",
    "{destination_vault_arn}": "{{ event.extra.destination_vault_arn }}",
    "{destination_account}": "{{ event.extra.destination_account }}",
    "{destination_region}": "{{ event.extra.destination_region }}",
    "{plan_name}": "{{ event.extra.plan_name }}",
    "{recovery_point_time}": "{{ event.extra.recovery_point_time }}",
    "{retention_days}": "{{ event.extra.retention_days if event.extra.retention_days is not none else '' }}",
    "{policy_summary}": "{{ event.extra.policy_summary }}",
    "{backup_vault_policy_wildcard}": "{{ event.extra.backup_vault_policy_wildcard }}",
    "{backup_copy_dest_account}": "{{ event.extra.backup_copy_dest_account }}",
    "{snapshot_id}": "{{ event.extra.snapshot_id or event.target.id }}",
    "{volume_id}": "{{ event.extra.volume_id }}",
    "{snapshot_share_scope}": "{{ event.extra.snapshot_share_scope }}",
    "{snapshot_shared_accounts}": "{{ event.extra.snapshot_shared_accounts | join(', ') if event.extra.snapshot_shared_accounts else '' }}",
    "{snapshot_public}": "{{ event.extra.snapshot_public if event.extra.snapshot_public is not none else '' }}",
    "{snapshot_removed_accounts}": "{{ event.extra.snapshot_removed_accounts | join(', ') if event.extra.snapshot_removed_accounts else '' }}",
    "{snapshot_removed_public}": "{{ 'yes' if event.extra.snapshot_removed_public else '' }}",
    "{snapshot_share_scope_before}": "{{ event.extra.snapshot_share_scope_before }}",
    "{snapshot_share_scope_current}": "{{ event.extra.snapshot_share_scope_current }}",
    "{snapshot_shared_accounts_before}": "{{ event.extra.snapshot_shared_accounts_before | join(', ') if event.extra.snapshot_shared_accounts_before else '' }}",
    "{snapshot_shared_accounts_current}": "{{ event.extra.snapshot_shared_accounts_current | join(', ') if event.extra.snapshot_shared_accounts_current else '' }}",
    "{encrypted}": "{{ event.extra.encrypted if event.extra.encrypted is not none else '' }}",
    "{kms_key_id}": "{{ event.extra.kms_key_id }}",
    "{vpc_id}": "{{ event.extra.vpc_id }}",
    "{subnet_id}": "{{ event.extra.subnet_id }}",
    "{gateway_id}": "{{ event.extra.gateway_id }}",
    "{peering_id}": "{{ event.extra.peering_id }}",
    "{source_vpc_id}": "{{ event.extra.source_vpc_id }}",
    "{destination_vpc_id}": "{{ event.extra.destination_vpc_id }}",
    "{source_account}": "{{ event.extra.source_account }}",
    "{destination_account}": "{{ event.extra.destination_account }}",
    "{source_region}": "{{ event.extra.source_region }}",
    "{destination_region}": "{{ event.extra.destination_region }}",
    "{security_group_id}": "{{ event.extra.security_group_id }}",
    "{protocol}": "{{ event.extra.protocol }}",
    "{from_port}": "{{ event.extra.from_port }}",
    "{to_port}": "{{ event.extra.to_port }}",
    "{cidrs}": "{{ event.extra.cidrs | join(', ') if event.extra.cidrs else '' }}",
    "{public_exposure}": "{{ event.extra.public_exposure }}",
    "{risky_exposure}": "{{ event.extra.risky_exposure }}",
    "{efs_filesystem_id}": "{{ event.extra.efs_filesystem_id }}",
    "{efs_filesystem_name}": "{{ event.extra.efs_filesystem_name }}",
    "{efs_mount_target_id}": "{{ event.extra.efs_mount_target_id }}",
    "{efs_subnet_id}": "{{ event.extra.efs_subnet_id }}",
    "{efs_availability_zone}": "{{ event.extra.efs_availability_zone }}",
    "{efs_ip_address}": "{{ event.extra.efs_ip_address }}",
    "{efs_security_groups}": "{{ event.extra.efs_security_groups | join(', ') if event.extra.efs_security_groups else '' }}",
    "{efs_policy_summary}": "{{ event.extra.efs_policy_summary }}",
    "{efs_policy_wildcard}": "{{ event.extra.efs_policy_wildcard }}",
}


def _event_spec(module: str, event_kind: str) -> dict[str, Any] | None:
    for mod in NOTIFICATION_CATALOG:
        if mod["key"] != module:
            continue
        for event in mod["events"]:
            key = str(event.get("key"))
            if key == event_kind:
                return event
            if module == "ueba" and (
                key == "<category>.anomaly.first_seen_*"
                and (event_kind == "ueba.anomaly" or ".anomaly.first_seen_" in event_kind)
            ):
                return event
            if module == "findings" and key == "<finding>.detected" and event_kind.startswith("finding.") and event_kind.endswith(".detected"):
                return event
        return None
    return None


def build_profile_match(module: str, event_kind: str, severities: list[str]) -> dict[str, Any]:
    """Compile a profile's plain-language scope into the existing matcher."""
    action_clause = (
        {"field": "action", "op": "icontains", "value": ".anomaly.first_seen_"}
        if module == "ueba" and event_kind in {"ueba.anomaly", "<category>.anomaly.first_seen_*"}
        else {"field": "action", "op": "regex", "value": r"^finding(?:\..+)?\.detected$"}
        if module == "findings" and event_kind in {"<finding>.detected", "finding.detected"}
        else {"field": "action", "op": "equals", "value": event_kind}
    )
    clauses: list[dict[str, Any]] = [action_clause]
    valid = [str(value) for value in severities if str(value) in _SEVERITIES]
    if valid:
        clauses.append({"field": "severity", "op": "in", "value": valid})
    return {"all": clauses}


def compile_message_template(content: dict[str, Any]) -> str:
    """Turn guided message fields into a safe, readable Jinja template."""
    labels = {
        "what_happened": "What happened",
        "facts": "Facts",
        "decision": "Decision",
        "next_steps": "Next steps",
        "why_it_matters": "Why it matters",
        "evidence": "Evidence",
        "monitoring_method": "Monitoring",
        "impact": "Impact",
        "recovery": "Recovery",
        "runbook_url": "Runbook",
    }
    lines: list[str] = []
    for key in PROFILE_CONTENT_FIELDS:
        value = str(content.get(key) or "").strip()
        if not value:
            continue
        for token in sorted(_TOKEN_MAP, key=len, reverse=True):
            replacement = _TOKEN_MAP[token]
            value = value.replace(token, replacement)
        if key == "title":
            lines.append(value)
        elif key == "evidence" and value.startswith("{% if "):
            # Conditional evidence must not leave an empty `Evidence:` row.
            # Put the label inside the producer's condition instead of
            # prefixing the whole Jinja expression unconditionally.
            lines.append(value.replace("%}", "%}Evidence: ", 1))
        else:
            lines.append(f"{labels[key]}: {value}")
    return "\n".join(lines)


def profile_id(module: str, event_kind: str) -> str:
    return f"profile:{module}:{event_kind}"


def normalize_profile(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload.get("module") or "").strip()
    event_kind = str(payload.get("event_kind") or "").strip()
    spec = _event_spec(module, event_kind)
    if spec is None:
        raise ValueError(f"unsupported notification profile: {module}/{event_kind}")
    if spec.get("notification_status") != "notifying":
        raise ValueError(f"event is not a notifying profile: {module}/{event_kind}")

    raw_content = payload.get("content")
    content = dict(spec.get("defaults") or {})
    if isinstance(raw_content, dict):
        content.update({key: raw_content.get(key) for key in PROFILE_CONTENT_FIELDS if key in raw_content})
    else:
        content.update({key: payload.get(key) for key in PROFILE_CONTENT_FIELDS if key in payload})

    severities = [str(value) for value in (payload.get("severities") or spec.get("default_severities") or ["high"]) if str(value) in _SEVERITIES]
    if not severities:
        severities = list(spec.get("default_severities") or ["high"])
    channels = [str(value).strip() for value in (payload.get("channels") or []) if str(value).strip()]
    advanced = str(payload.get("advanced_template") or "").strip() or None
    return {
        "id": str(payload.get("id") or profile_id(module, event_kind)),
        "module": module,
        "event_kind": event_kind,
        "label": str(payload.get("label") or spec["label"]),
        "description": str(payload.get("description") or spec["description"]),
        "enabled": bool(payload.get("enabled", False)),
        "severities": severities,
        "channels": channels,
        "throttle_seconds": max(0, int(payload.get("throttle_seconds") or 0)),
        "digest_window_seconds": max(0, int(payload.get("digest_window_seconds") or 0)),
        "silence_until": payload.get("silence_until"),
        "content": content,
        "advanced_template": advanced,
        "message_template": advanced or compile_message_template(content),
        "content_fields": list(spec.get("content_fields") or PROFILE_CONTENT_FIELDS[2:]),
        "content_status": str(spec.get("content_status") or "generic"),
        "preview_sample": dict(spec.get("preview_sample") or {}),
        "updated_at": payload.get("updated_at"),
    }


def build_preview_event(profile: dict[str, Any]) -> Event:
    """Build a representative event from the selected catalog contract.

    Preview data is deliberately kept in the catalog so the UI and notifier
    exercise the same event-specific fields. It is never used for delivery.
    """
    sample = profile.get("preview_sample") or {}
    event_time = sample.get("event_time")
    parsed_time = None
    if isinstance(event_time, str) and event_time.strip():
        try:
            parsed_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            parsed_time = None

    severity_value = str((profile.get("severities") or [""])[-1])
    severity = Severity(severity_value) if severity_value in _SEVERITIES else None
    outcome_value = str(sample.get("outcome") or "unknown")
    outcome = Outcome(outcome_value) if outcome_value in {item.value for item in Outcome} else Outcome.unknown
    extra = dict(sample.get("extra") or {}) if isinstance(sample.get("extra"), dict) else {}
    for key in ("message", "log_line", "server"):
        if sample.get(key) is not None:
            extra[key] = sample[key]

    preview_action = str(profile.get("event_kind") or "generic.event")
    if preview_action in {"ueba.anomaly", "<category>.anomaly.first_seen_*"}:
        preview_action = "iam.anomaly.first_seen_source_ip"
    return Event(
        source=Source(module=str(profile.get("module") or "unknown")),
        action=preview_action,
        event_time=parsed_time or datetime.now().astimezone(),
        severity=severity,
        outcome=outcome,
        actor=Actor(
            principal=sample.get("principal"),
            source_ip=sample.get("source_ip"),
        ),
        target=Target(
            id=sample.get("target_id") or "sample-target",
            name=sample.get("target_name") or "sample target",
        ),
        extra=extra,
    )
