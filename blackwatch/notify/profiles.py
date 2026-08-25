"""Beginner-friendly notification profiles.

Profiles are the product-facing layer above notification rules. They describe
one module and one alert kind in plain language, then compile to the existing
rule/template dispatch path so delivery behavior remains centralized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


PROFILE_CONTENT_FIELDS = (
    "title",
    "what_happened",
    "why_it_matters",
    "evidence",
    "monitoring_method",
    "impact",
    "next_steps",
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


def _event(
    key: str,
    label: str,
    description: str,
    severity: str = "high",
    *,
    available_fields: list[str] | None = None,
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    default_content = {
        "title": label,
        "what_happened": f"BlackWatch detected {label.lower()}.",
        "why_it_matters": "Review the evidence and confirm whether this activity was expected.",
        "evidence": "Observed signal: {evidence}.",
        "monitoring_method": "Monitored by {monitoring_method}.",
        "impact": "Impact depends on the affected resource and environment.",
        "next_steps": "Verify the resource, owner, and recent changes, then follow the runbook if action is needed.",
        "recovery": "Recovery is reported by the matching recovery event when available.",
        "runbook_url": "",
    }
    if defaults:
        default_content.update(defaults)
    return {
        "key": key,
        "label": label,
        "description": description,
        "default_severities": [severity],
        "available_fields": list(available_fields or _COMMON_AVAILABLE_FIELDS),
        "defaults": default_content,
    }


def _service_event(
    key: str,
    label: str,
    description: str,
    severity: str = "high",
    *,
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _event(
        key,
        label,
        description,
        severity,
        available_fields=_SERVICE_AVAILABLE_FIELDS,
        defaults=defaults,
    )


def _module(key: str, label: str, description: str, *events: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "label": label, "description": description, "events": list(events)}


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
        _event("iam.mfa.deactivate", "IAM MFA disabled", "Multi-factor authentication was disabled.", "critical"),
        _event("iam.role.update_trust", "Role trust policy changed", "An IAM role trust policy was changed.", "critical"),
        _event("iam.user.create", "IAM user created", "A new IAM user was created.", "medium"),
        _event("iam.user.delete", "IAM user deleted", "An IAM user was deleted.", "high"),
        _event("iam.role.create", "IAM role created", "A new IAM role was created.", "medium"),
        _event("iam.role.delete", "IAM role deleted", "An IAM role was deleted.", "high"),
        _event("iam.login_profile.create", "IAM login profile created", "A console login profile was created for an IAM user.", "high"),
        _event("iam.policy.attach", "IAM policy attached", "A policy was attached to an IAM principal.", "high"),
        _event("iam.policy.put_inline", "Inline IAM policy changed", "An inline IAM policy was added or changed.", "high"),
        _event("kms.key.disable", "KMS key disabled", "A KMS key was disabled.", "critical"),
        _event("kms.key.delete_scheduled", "KMS key deletion scheduled", "Deletion was scheduled for a KMS key.", "critical"),
        _event("kms.policy.put", "KMS key policy changed", "A KMS key policy was changed.", "high"),
        _event("kms.grant.create", "KMS grant created", "A grant was created for a KMS key.", "high"),
        _event("kms.rotation.disable", "KMS key rotation disabled", "Automatic KMS key rotation was disabled.", "critical"),
        _event("cloudtrail.trail.delete", "CloudTrail trail deleted", "A CloudTrail trail was deleted.", "critical"),
        _event("cloudtrail.logging.stop", "CloudTrail logging stopped", "CloudTrail logging was stopped.", "critical"),
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
        _event("s3.bucket.versioning.put", "S3 bucket versioning changed", "S3 bucket versioning was enabled or changed.", "medium"),
        _event("s3.bucket.versioning_off", "S3 bucket versioning disabled", "S3 bucket versioning was disabled.", "high"),
        _event("s3.bucket.logging.put", "S3 bucket logging changed", "S3 bucket access logging changed.", "high"),
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
        _event("network.sg.instance_attach", "Security group attached", "A security group attachment changed.", "high"),
        _event("posture.finding.open", "Posture finding opened", "A posture finding became active.", "high"),
        _event("aws.posture.finding.new", "New posture finding", "A new posture finding was detected.", "high"),
        _event("aws.posture.finding.resolved", "Posture finding resolved", "A posture finding was resolved.", "informational"),
    ),
    _module(
        "aws.backup", "AWS Backup", "Backup recovery-point and vault policy changes.",
        _event("backup.recovery_point.delete", "Backup recovery point deleted", "A backup recovery point was deleted.", "critical"),
        _event("backup.vault.delete", "Backup vault deleted", "A backup vault was deleted.", "critical"),
        _event("backup.vault.policy.delete", "Backup vault policy deleted", "A backup vault policy was deleted.", "high"),
        _event("backup.vault.policy.put", "Backup vault policy changed", "A backup vault policy changed.", "high"),
        _event("backup.copy_job.start", "Backup copy job started", "A backup copy job started.", "medium"),
    ),
    _module(
        "aws.efs", "AWS EFS", "File-system policy, mount target, and security-group changes.",
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
        _event("secrets.secret.create", "Secret created", "A new secret was created.", "medium"),
        _event("secrets.secret.update", "Secret updated", "A secret value or metadata was updated.", "high"),
        _event("secrets.secret.restore", "Secret restored", "A deleted secret was restored.", "medium"),
        _event("secrets.secret.delete", "Secret deleted", "A secret was deleted.", "critical"),
    ),
    _module(
        "aws.compute", "AWS Compute", "EC2, AMI, and instance security configuration changes.",
        _event("compute.imds.modify", "EC2 metadata settings changed", "Instance metadata settings changed.", "high"),
        _event("compute.ami.modify", "AMI sharing changed", "An AMI sharing or visibility setting changed.", "high"),
        _event("compute.instance.modify", "EC2 instance changed", "An EC2 instance configuration changed.", "medium"),
    ),
    _module(
        "aws.storage", "AWS Storage", "Snapshot, volume, and resource-sharing changes.",
        _event("storage.snapshot.modify", "Storage snapshot changed", "A storage snapshot sharing or configuration setting changed.", "high"),
    ),
    _module(
        "vpn.openvpn", "OpenVPN", "VPN service, authentication, sessions, and brute-force activity.",
        _event("vpn.service.down", "VPN service down", "The VPN service reported a down state.", "critical"),
        _event("vpn.auth.failure", "VPN login failed", "A VPN authentication attempt failed.", "medium"),
        _event("vpn.bruteforce", "VPN brute-force activity", "Repeated VPN authentication failures were detected.", "high"),
        _event("vpn.session.concurrent", "Concurrent VPN sessions high", "Concurrent VPN sessions crossed the configured threshold.", "medium"),
        _event("vpn.cert.expired", "VPN certificate expired", "A VPN certificate expired.", "critical"),
        _event("vpn.cert.probe.failed", "VPN certificate probe failed", "A VPN certificate check could not complete.", "high"),
        _event("vpn.cert.expiring.critical", "VPN certificate expires soon", "A VPN certificate is critically close to expiry.", "critical"),
        _event("vpn.cert.expiring.high", "VPN certificate expiry warning", "A VPN certificate is approaching expiry.", "high"),
        _event("vpn.cert.expiring.warning", "VPN certificate expiry notice", "A VPN certificate entered its warning window.", "medium"),
        _event("vpn.auth.success", "VPN login succeeded", "A VPN authentication attempt succeeded.", "informational"),
        _event("vpn.bruteforce.user", "VPN brute-force activity against a user", "Repeated VPN authentication failures targeted one user.", "high"),
        _event("vpn.service.up", "VPN service recovered", "The VPN service recovered.", "informational"),
        _event("vpn.session.start", "VPN session started", "A VPN session started.", "informational"),
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
        _event("ueba.anomaly", "Behavior anomaly detected", "Observed behavior deviated from its baseline.", "high"),
    ),
    _module(
        "findings", "Security Findings", "Malware, custom, and externally supplied security findings.",
        _event("finding.malware.detected", "Malware detected", "A malware finding was reported.", "critical"),
    ),
]


_TOKEN_MAP = {
    "{module}": "{{ event.source.module }}",
    "{alert_type}": "{{ event.action }}",
    "{target_name}": "{{ event.target.name or event.target.id or 'unknown target' }}",
    "{{target_name}}": "{{ event.target.name or event.target.id or 'unknown target' }}",
    "{severity}": "{{ event.severity or 'unscored' }}",
    "{principal}": "{{ event.actor.principal or 'unknown principal' }}",
    "{source_ip}": "{{ event.actor.source_ip or 'unknown source' }}",
    "{event_time}": "{{ event.event_time }}",
    "{evidence}": "{{ event.extra.error or event.extra.observation or event.extra.message or 'no additional evidence' }}",
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
    "{last_report}": "{{ event.extra.last_report or 'unknown' }}",
    "{agent_version}": "{{ event.extra.agent_version or 'unknown' }}",
    "{monitoring_impact}": "{{ event.extra.monitoring_impact or event.extra.impact or 'monitoring impact not specified' }}",
}


def _event_spec(module: str, event_kind: str) -> dict[str, Any] | None:
    for mod in NOTIFICATION_CATALOG:
        if mod["key"] != module:
            continue
        return next((event for event in mod["events"] if event["key"] == event_kind), None)
    return None


def build_profile_match(module: str, event_kind: str, severities: list[str]) -> dict[str, Any]:
    """Compile a profile's plain-language scope into the existing matcher."""
    clauses: list[dict[str, Any]] = [
        {"field": "action", "op": "equals", "value": event_kind},
    ]
    valid = [str(value) for value in severities if str(value) in _SEVERITIES]
    if valid:
        clauses.append({"field": "severity", "op": "in", "value": valid})
    return {"all": clauses}


def compile_message_template(content: dict[str, Any]) -> str:
    """Turn guided message fields into a safe, readable Jinja template."""
    labels = {
        "what_happened": "What happened",
        "why_it_matters": "Why it matters",
        "evidence": "Evidence",
        "monitoring_method": "Monitoring",
        "impact": "Impact",
        "next_steps": "Next steps",
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
        "updated_at": payload.get("updated_at"),
    }
