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


def _event(key: str, label: str, description: str, severity: str = "high") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "description": description,
        "default_severities": [severity],
        "defaults": {
            "title": label,
            "what_happened": f"BlackWatch detected {label.lower()}.",
            "why_it_matters": "Review the evidence and confirm whether this activity was expected.",
            "evidence": "Observed signal: {evidence}.",
            "monitoring_method": "Monitored by {monitoring_method}.",
            "impact": "Impact depends on the affected resource and environment.",
            "next_steps": "Verify the resource, owner, and recent changes, then follow the runbook if action is needed.",
            "recovery": "Recovery is reported by the matching recovery event when available.",
            "runbook_url": "",
        },
    }


def _module(key: str, label: str, description: str, *events: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "label": label, "description": description, "events": list(events)}


NOTIFICATION_CATALOG: list[dict[str, Any]] = [
    _module(
        "ec2.host", "EC2 Hosts", "Agent, login, privilege, file, process, and host health events.",
        _event("host.agent.stale", "Host agent stopped reporting", "A host agent has gone silent.", "high"),
        _event("host.auth.ssh.failure", "SSH login failed", "An SSH authentication attempt failed.", "medium"),
        _event("host.bruteforce", "SSH brute-force activity", "Repeated SSH failures crossed the detection threshold.", "high"),
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
        _event("host.disk.critical", "Disk space critical", "Disk usage crossed the critical threshold.", "high"),
        _event("host.memory.exhausted", "Memory exhausted", "The host reported memory exhaustion.", "high"),
        _event("host.oom_kill", "Process killed by OOM", "The kernel killed a process because of memory pressure.", "high"),
        _event("host.collector.stalled", "Host collector stalled", "The host collector stopped producing expected telemetry.", "high"),
    ),
    _module(
        "aws.rds", "AWS RDS", "Database authentication, sessions, queries, and proxy activity.",
        _event("rds.auth.failure", "Database authentication failed", "A database authentication attempt failed.", "high"),
        _event("rds.auth.burst", "Database authentication burst", "A burst of database authentication failures was detected.", "critical"),
        _event("rds.session.concurrent", "Concurrent session threshold reached", "Concurrent database sessions crossed the configured threshold.", "medium"),
        _event("rds.session.long_idle", "Long-idle database session", "A database session remained idle longer than expected.", "medium"),
        _event("rds.query.role", "Sensitive role query", "A query associated with a sensitive database role was observed.", "high"),
        _event("rds.query.function", "Sensitive database function used", "A monitored database function was called.", "high"),
        _event("rds.error", "Database error", "A database error was observed.", "medium"),
        _event("rds.proxy.source.new", "New database proxy source", "A new source connected through the database proxy.", "medium"),
        _event("rds.user.unknown", "Unknown database user", "A database user not present in the allowlist was observed.", "high"),
    ),
    _module(
        "aws.iam", "AWS IAM", "Identity, access-key, MFA, trust-policy, KMS, and CloudTrail security events.",
        _event("iam.access_key.create", "IAM access key created", "A new IAM access key was created.", "high"),
        _event("iam.mfa.deactivate", "IAM MFA disabled", "Multi-factor authentication was disabled.", "critical"),
        _event("iam.role.update_trust", "Role trust policy changed", "An IAM role trust policy was changed.", "critical"),
        _event("iam.user.create", "IAM user created", "A new IAM user was created.", "medium"),
        _event("iam.role.create", "IAM role created", "A new IAM role was created.", "medium"),
        _event("kms.key.disable", "KMS key disabled", "A KMS key was disabled.", "critical"),
        _event("cloudtrail.trail.delete", "CloudTrail trail deleted", "A CloudTrail trail was deleted.", "critical"),
        _event("cloudtrail.logging.stop", "CloudTrail logging stopped", "CloudTrail logging was stopped.", "critical"),
    ),
    _module(
        "aws.s3", "AWS S3", "Bucket policy, public access, and object access events.",
        _event("s3.object.access.anonymous", "Anonymous S3 object access", "An S3 object was accessed anonymously.", "high"),
        _event("s3.bucket.public", "S3 bucket became public", "A bucket public-access control changed.", "critical"),
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
    ),
    _module(
        "aws.backup", "AWS Backup", "Backup recovery-point and vault policy changes.",
        _event("backup.recovery_point.delete", "Backup recovery point deleted", "A backup recovery point was deleted.", "critical"),
        _event("backup.vault.delete", "Backup vault deleted", "A backup vault was deleted.", "critical"),
        _event("backup.vault.policy.delete", "Backup vault policy deleted", "A backup vault policy was deleted.", "high"),
    ),
    _module(
        "aws.efs", "AWS EFS", "File-system policy, mount target, and security-group changes.",
        _event("efs.filesystem.policy.delete", "EFS policy deleted", "An EFS file-system policy was deleted.", "high"),
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
    ),
    _module(
        "aws.secrets", "AWS Secrets", "Secrets creation, update, restore, and deletion.",
        _event("secrets.secret.create", "Secret created", "A new secret was created.", "medium"),
        _event("secrets.secret.update", "Secret updated", "A secret value or metadata was updated.", "high"),
        _event("secrets.secret.restore", "Secret restored", "A deleted secret was restored.", "medium"),
        _event("secrets.secret.delete", "Secret deleted", "A secret was deleted.", "critical"),
    ),
    _module(
        "vpn.openvpn", "OpenVPN", "VPN service, authentication, sessions, and brute-force activity.",
        _event("vpn.service.down", "VPN service down", "The VPN service reported a down state.", "critical"),
        _event("vpn.auth.failure", "VPN login failed", "A VPN authentication attempt failed.", "medium"),
        _event("vpn.bruteforce", "VPN brute-force activity", "Repeated VPN authentication failures were detected.", "high"),
        _event("vpn.session.concurrent", "Concurrent VPN sessions high", "Concurrent VPN sessions crossed the configured threshold.", "medium"),
        _event("vpn.cert.expired", "VPN certificate expired", "A VPN certificate expired.", "critical"),
    ),
    _module(
        "ecs.probe", "Services and Probes", "Service availability, degradation, recovery, and monitoring-agent health.",
        _event("service.down", "Service went down", "A monitored service crossed the down threshold.", "high"),
        _event("service.degraded", "Service degraded", "A monitored service reported degraded health.", "medium"),
        _event("service.up", "Service recovered", "A previously unhealthy service recovered.", "informational"),
        _event("probe.agent.stale", "Probe agent stopped reporting", "A probe agent stopped reporting and monitoring coverage is offline.", "critical"),
        _event("probe.agent.recovered", "Probe agent recovered", "A previously silent probe agent reported again.", "informational"),
        _event("probe.agent.first_seen", "New probe agent detected", "A probe agent reported for the first time.", "low"),
    ),
    _module(
        "cert", "TLS Certificates", "Certificate expiration and probe failures.",
        _event("cert.expired", "Certificate expired", "A monitored certificate has expired.", "critical"),
        _event("cert.expiring.critical", "Certificate expires soon", "A monitored certificate is close to expiry.", "critical"),
        _event("cert.expiring.high", "Certificate expiry warning", "A monitored certificate is approaching expiry.", "high"),
        _event("cert.probe.failed", "Certificate probe failed", "A certificate check could not complete.", "high"),
    ),
    _module(
        "ueba", "UEBA", "Behavior baselines and anomaly signals.",
        _event("ueba.anomaly", "Behavior anomaly detected", "Observed behavior deviated from its baseline.", "high"),
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
