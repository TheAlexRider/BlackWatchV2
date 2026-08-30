"""Event-level notification content contracts.

The catalog owns routing and profile defaults; this module owns the small,
event-specific language layer for the first three notification modules.  It is
deliberately data-only so content reviewers can improve wording without
touching delivery, persistence, or matching behavior.
"""

from __future__ import annotations

from typing import Any, Iterable


def _contract(
    *,
    title: str,
    what_happened: str,
    facts: str,
    decision: str,
    next_steps: str,
    why_it_matters: str,
    evidence: str,
    monitoring_method: str,
    impact: str,
    recovery: str,
    preview_extra: dict[str, Any] | None = None,
    preview_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "what_happened": what_happened,
        "facts": facts,
        "decision": decision,
        "next_steps": next_steps,
        "why_it_matters": why_it_matters,
        "evidence": evidence,
        "monitoring_method": monitoring_method,
        "impact": impact,
        "recovery": recovery,
        "preview_extra": dict(preview_extra or {}),
        "preview_sample": dict(preview_sample or {}),
    }


_VPN = {
    "vpn.service.down": _contract(
        title="VPN service down · {{ event.target.name or event.target.id or 'unknown server' }}",
        what_happened="The monitored OpenVPN service changed from up to down.",
        facts=("Server: {{ event.target.name or event.target.id or event.extra.server or 'unknown' }}\n"
               "Detected: {{ event.event_time }}\n"
               "Previous state: {{ event.extra.prev_active if event.extra.prev_active is not none else 'not reported' }}\n"
               "Current state: {{ event.extra.active if event.extra.active is not none else 'down' }}\n"
               "{% if event.extra.hostname %}Host: {{ event.extra.hostname }}{% endif %}"),
        decision="Contain or restore the VPN service unless this transition is approved maintenance.",
        next_steps="1. Confirm the maintenance or change window.\n2. Check the OpenVPN process, listener, host health, and recent certificate/configuration changes.\n3. Restore service or escalate with the VPN outage runbook.",
        why_it_matters="Remote access may be unavailable, and an unexplained stop can hide a host or configuration problem.",
        evidence="The service transition was derived from the VPN health heartbeat; the previous and current states are shown above.",
        monitoring_method="OpenVPN health heartbeats and the VPN service-state projection.",
        impact="VPN users may be unable to connect until the service is restored.",
        recovery="This condition is recovered only when vpn.service.up is observed; do not close it on a later login alone.",
        preview_extra={"prev_active": True, "active": False, "server": "vpn-1"},
    ),
    "vpn.service.up": _contract(
        title="VPN service recovered · {{ event.target.name or event.target.id or 'unknown server' }}",
        what_happened="The VPN service is active again after a down transition, or this is its first active heartbeat.",
        facts=("Server: {{ event.target.name or event.target.id or event.extra.server or 'unknown' }}\n"
               "Detected: {{ event.event_time }}\n"
               "Previous state: {{ event.extra.prev_active if event.extra.prev_active is not none else 'first seen' }}\n"
               "Current state: {{ event.extra.active if event.extra.active is not none else 'active' }}"),
        decision="Confirm stability before closing the earlier outage; treat a first-seen heartbeat as onboarding, not recovery.",
        next_steps="1. Check that consecutive healthy heartbeats continue.\n2. Review active sessions and the outage timeline.\n3. Close the earlier incident only after the cause and stability are understood.",
        why_it_matters="Connectivity has returned, but a brief recovery does not explain why the service stopped.",
        evidence="The VPN service-state projection observed an active heartbeat and recorded the prior state above.",
        monitoring_method="OpenVPN health heartbeats and the VPN service-state projection.",
        impact="Users can connect again; instability may still cause repeated access failures.",
        recovery="This is the recovery event for vpn.service.down when Previous state is false; first-seen events have no prior incident.",
        preview_extra={"prev_active": False, "active": True, "server": "vpn-1"},
    ),
    "vpn.session.start": _contract(
        title="VPN session started · {{ event.actor.principal or event.extra.common_name or 'unidentified client' }}",
        what_happened="A client appeared in the latest VPN status snapshot and was not present in the previous snapshot.",
        facts=("{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% elif event.extra.common_name %}Client name: {{ event.extra.common_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "Server: {{ event.target.name or event.target.id or 'unknown' }}\nDetected: {{ event.event_time }}"),
        decision="Decide whether this connection is expected for this identity and source.",
        next_steps="1. Confirm the user and source IP are expected.\n2. Check the corresponding authentication event if available.\n3. Investigate concurrent or unusual access if the connection is not approved.",
        why_it_matters="A newly observed session confirms access, but the status diff alone does not prove that access was authorized.",
        evidence="This event was derived from a change between two VPN status snapshots; it is not an authentication result.",
        monitoring_method="OpenVPN client-status snapshots and the VPN session projection.",
        impact="An unexpected session can provide active access to the private network.",
        recovery="vpn.session.end closes the observed session trail; it is not proof that the session was authorized.",
        preview_extra={"common_name": "alice", "server": "vpn-1", "derived": True},
    ),
    "vpn.session.end": _contract(
        title="VPN session ended · {{ event.actor.principal or event.extra.common_name or 'unidentified client' }}",
        what_happened="A client present in the previous VPN status snapshot is no longer present.",
        facts=("{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% elif event.extra.common_name %}Client name: {{ event.extra.common_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Last observed source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "Server: {{ event.target.name or event.target.id or 'unknown' }}\nDetected: {{ event.event_time }}"),
        decision="Decide whether the session ended normally or disappeared unexpectedly.",
        next_steps="1. Compare the end time with the user's expected work window.\n2. Check OpenVPN and authentication logs for disconnect or failure evidence.\n3. Close the session trail only when the end is expected or explained.",
        why_it_matters="An unexpected disappearance can indicate a dropped connection, forced termination, or incomplete telemetry.",
        evidence="This event is the end counterpart to vpn.session.start and was derived from the status-snapshot diff.",
        monitoring_method="OpenVPN client-status snapshots and the VPN session projection.",
        impact="The client is no longer observed, but the reason for disconnect is not known from this event alone.",
        recovery="There is no automatic remediation; manual resolution is an operator explanation or closure of the session trail.",
        preview_extra={"common_name": "alice", "server": "vpn-1", "derived": True},
    ),
    "vpn.session.concurrent": _contract(
        title="Concurrent VPN sessions · {{ event.extra.identity or event.actor.principal or 'unidentified user' }}",
        what_happened="The same VPN identity was observed from more than one source IP at the same time.",
        facts=("Identity: {{ event.extra.identity or event.actor.principal or 'not reported' }}\n"
               "Source IPs: {{ event.extra.source_ips | join(', ') if event.extra.source_ips else event.actor.source_ip or 'not reported' }}\n"
               "Server: {{ event.target.name or event.target.id or 'unknown' }}\nDetected: {{ event.event_time }}"),
        decision="Treat this as possible credential sharing or compromise until the identity owner confirms both sessions.",
        next_steps="1. Confirm whether the user intentionally has multiple connections.\n2. Compare the sources with known devices, locations, and authentication history.\n3. Revoke or rotate credentials/certificates if either connection is unauthorized.\n4. Record the owner's decision.",
        why_it_matters="Simultaneous access from distinct sources can indicate shared credentials or an account takeover.",
        evidence="The session projection found more than one distinct source IP for one identity in the same snapshot.",
        monitoring_method="OpenVPN status snapshots and concurrent-identity correlation.",
        impact="An unauthorized concurrent session may provide active network access while the legitimate user is connected.",
        recovery="No automatic recovery exists; resolution is owner confirmation, session termination, and credential action when required.",
        preview_extra={"identity": "alice", "source_ips": ["192.0.2.10", "198.51.100.20"], "server": "vpn-1", "derived": True},
    ),
    "vpn.auth.failure": _contract(
        title="VPN login failed · {{ event.actor.principal or event.actor.source_ip or 'unknown source' }}",
        what_happened="A VPN authentication attempt failed.",
        facts=("{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "Server: {{ event.target.name or event.target.id or 'unknown' }}\nWhen: {{ event.event_time }}"),
        decision="Decide whether the failed attempt was expected; one failure alone is not proof of an attack.",
        next_steps="1. Confirm whether the user initiated the attempt.\n2. If unexpected, investigate the source IP and recent account activity.\n3. Escalate or follow the credential-response runbook if failures continue.",
        why_it_matters="An unexplained failure may be a mistyped password or an attempted account takeover.",
        evidence="{% if event.extra.message %}{{ event.extra.message }}{% endif %}{% if event.extra.log_line %}\nLog: {{ event.extra.log_line }}{% endif %}",
        monitoring_method="OpenVPN authentication logs on the monitored VPN server.",
        impact="This attempt did not establish access; repeated failures can precede credential abuse.",
        recovery="There is no automatic recovery. A later successful login is separate context and must not silently close this failure.",
        preview_extra={"server": "vpn-1", "message": "VPN authentication FAILED"},
    ),
    "vpn.auth.success": _contract(
        title="VPN login succeeded · {{ event.actor.principal or event.actor.source_ip or 'unknown identity' }}",
        what_happened="A VPN authentication attempt succeeded.",
        facts=("{% if event.actor.principal %}User: {{ event.actor.principal }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "Server: {{ event.target.name or event.target.id or 'unknown' }}\nWhen: {{ event.event_time }}"),
        decision="Decide whether the successful login matches the user's expected access.",
        next_steps="1. If expected, no action is required.\n2. If unexpected, verify the user and source and review recent failures or concurrent sessions.\n3. Escalate only when corroborating evidence exists.",
        why_it_matters="A successful login confirms access and is useful context when it follows failures or unusual activity.",
        evidence="{% if event.extra.message %}{{ event.extra.message }}{% endif %}{% if event.extra.log_line %}\nLog: {{ event.extra.log_line }}{% endif %}",
        monitoring_method="OpenVPN authentication logs on the monitored VPN server.",
        impact="The account established VPN access from the recorded source.",
        recovery="This event has no recovery semantics and does not close a previous failed-login alert.",
        preview_extra={"server": "vpn-1", "message": "VPN login"},
    ),
    "vpn.bruteforce": _contract(
        title="VPN brute-force activity · {{ event.actor.source_ip or 'unknown source' }}",
        what_happened="The configured threshold of failed VPN logins was reached from one source within the detection window.",
        facts=("{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.actor.principal %}Targeted user: {{ event.actor.principal }}\n{% endif %}"
               "Count: {{ event.extra.count_in_window or 'not reported' }}\nThreshold: {{ event.extra.threshold or 'not reported' }}\nWindow: {{ event.extra.window_seconds or 'not reported' }} seconds\nServer: {{ event.target.name or event.target.id or 'unknown' }}"),
        decision="Treat this as active suspicious authentication activity unless the source is an approved scanner or gateway.",
        next_steps="1. Verify whether the source is an approved NAT, scanner, or corporate gateway.\n2. Check targeted users and successful logins in the same window.\n3. Block or rate-limit the source and protect affected accounts according to the runbook.",
        why_it_matters="Repeated failures from one source can be password spraying, credential stuffing, or a noisy trusted gateway.",
        evidence="The correlation count, threshold, window, and source dimension are the detection evidence; the trigger event remains an audit link.",
        monitoring_method="VPN authentication-failure correlation by source IP.",
        impact="Accounts may be under active attack even though these attempts did not authenticate.",
        recovery="No automatic recovery exists; resolution is containment plus documenting why the source is trusted or blocked.",
        preview_extra={"count_in_window": 12, "threshold": 10, "window_seconds": 300, "server": "vpn-1"},
    ),
    "vpn.bruteforce.user": _contract(
        title="VPN credential-stuffing activity · {{ event.actor.principal or 'unknown user' }}",
        what_happened="The configured threshold of failed VPN logins targeted one username within the detection window.",
        facts=("User: {{ event.actor.principal or 'not reported' }}\n"
               "{% if event.actor.source_ip %}Observed source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "Count: {{ event.extra.count_in_window or 'not reported' }}\nThreshold: {{ event.extra.threshold or 'not reported' }}\nWindow: {{ event.extra.window_seconds or 'not reported' }} seconds\nServer: {{ event.target.name or event.target.id or 'unknown' }}"),
        decision="Treat this as possible credential stuffing unless the account is a known test target.",
        next_steps="1. Confirm the account owner and whether a password-reset or test explains the pattern.\n2. Review all source IPs and any successful login in the same window.\n3. Lock, rotate, or step-up-protect the account if unauthorized.\n4. Record the resolution.",
        why_it_matters="Repeated attempts against one identity can expose a weak or reused credential even when sources vary.",
        evidence="The correlation count, threshold, window, and principal dimension are the detection evidence.",
        monitoring_method="VPN authentication-failure correlation by username.",
        impact="The targeted account may be at risk of takeover.",
        recovery="No automatic recovery exists; resolution is account protection and owner confirmation.",
        preview_extra={"count_in_window": 9, "threshold": 8, "window_seconds": 600, "server": "vpn-1"},
    ),
}


_SERVICE = {
    "service.down": _contract(
        title="{{ event.extra.service_name or event.target.name or event.target.id or 'service' }} is down · {{ event.extra.vpc or 'unknown environment' }}",
        what_happened="The service failed the configured health check after the required consecutive failures.",
        facts=("Service: {{ event.extra.service_name or event.target.name or event.target.id or 'not reported' }}\n"
               "Environment/VPC: {{ event.extra.vpc or 'not reported' }}\n"
               "Probe tier: {{ event.extra.monitor_tier or event.extra.tier or 'not reported' }}\n"
               "Failures: {{ event.extra.consecutive_failures or 'not reported' }}\n"
               "{% if event.extra.error %}Probe error: {{ event.extra.error }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Treat this as an outage unless an approved maintenance window explains it.",
        next_steps="1. Check the service logs, endpoint, dependencies, and latest deployment.\n2. Confirm whether the failing tier is network, HTTP, or ECS health.\n3. Restore the service or escalate with the service outage runbook.",
        why_it_matters="Customers or dependent systems may be unable to use the service.",
        evidence="The transition was emitted after the configured failure hysteresis; the probe signal and failure count are shown above.",
        monitoring_method="The configured service probe and service-state projection.",
        impact="Requests may fail until the service and its dependencies recover.",
        recovery="service.up is the recovery event; do not close this alert after a single successful probe.",
        preview_extra={"service_name": "payments-api", "vpc": "prod", "monitor_tier": "http_alive", "consecutive_failures": 2, "error_signal": "timeout", "down_seconds": 180},
    ),
    "service.degraded": _contract(
        title="{{ event.extra.service_name or event.target.name or event.target.id or 'service' }} is degraded · {{ event.extra.vpc or 'unknown environment' }}",
        what_happened="The service is responding, but its health signal crossed the degraded threshold.",
        facts=("Service: {{ event.extra.service_name or event.target.name or event.target.id or 'not reported' }}\n"
               "Environment/VPC: {{ event.extra.vpc or 'not reported' }}\n"
               "Probe tier: {{ event.extra.monitor_tier or event.extra.tier or 'not reported' }}\n"
               "{% if event.extra.latency_ms is not none %}Latency: {{ event.extra.latency_ms }} ms\n{% endif %}"
               "{% if event.extra.error %}Probe error: {{ event.extra.error }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Decide whether the degradation is an early outage signal, capacity pressure, or an approved change.",
        next_steps="1. Review latency, errors, capacity, and dependencies.\n2. Compare the signal with deployments and application metrics.\n3. Reduce the impact before the service crosses the down threshold.",
        why_it_matters="The service may be slow or partially unavailable before a full outage is declared.",
        evidence="The service projection observed the degraded result and retained the raw probe signal and latency.",
        monitoring_method="The configured service probe and service-state projection.",
        impact="Some requests or users may experience errors or increased latency.",
        recovery="service.up is the recovery event after the configured successful-probe threshold; continued degradation is not resolved by one good sample.",
        preview_extra={"service_name": "payments-api", "vpc": "prod", "monitor_tier": "http_alive", "latency_ms": 850, "error_signal": "HTTP 503"},
    ),
    "service.unknown": _contract(
        title="Unable to verify {{ event.extra.service_name or event.target.name or event.target.id or 'service' }}",
        what_happened="BlackWatch could not determine the service state for the configured unknown-state interval.",
        facts=("Service: {{ event.extra.service_name or event.target.name or event.target.id or 'not reported' }}\n"
               "Environment/VPC: {{ event.extra.vpc or 'not reported' }}\n"
               "Probe tier: {{ event.extra.monitor_tier or event.extra.tier or 'not reported' }}\n"
               "{% if event.extra.unknown_seconds %}Unknown for: {{ event.extra.unknown_seconds }} seconds\n{% endif %}"
               "{% if event.extra.error %}Reason: {{ event.extra.error }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Treat service health as unverified until the probe path or service result is restored.",
        next_steps="1. Check the probe agent, endpoint, DNS, network path, and credentials.\n2. Determine whether the service is healthy independently of the probe.\n3. Restore monitoring coverage and record any blind interval.",
        why_it_matters="BlackWatch cannot confirm availability while the service state is unknown.",
        evidence="The projection sustained an unknown result beyond its configured interval; the available probe reason is shown above.",
        monitoring_method="The configured service probe and unknown-state projection.",
        impact="The service may be healthy, degraded, or down while monitoring is unable to distinguish the state.",
        recovery="A valid service result clears this state; service.up is only a recovery for an emitted unknown alert when the projection confirms it.",
        preview_extra={"service_name": "payments-api", "vpc": "prod", "monitor_tier": "tcp", "unknown_seconds": 900, "error_signal": "DNS lookup failed"},
    ),
    "service.up": _contract(
        title="{{ event.extra.service_name or event.target.name or event.target.id or 'service' }} recovered · {{ event.extra.vpc or 'unknown environment' }}",
        what_happened="The service passed the configured successful-probe threshold after a previous unhealthy or unknown state.",
        facts=("Service: {{ event.extra.service_name or event.target.name or event.target.id or 'not reported' }}\n"
               "Environment/VPC: {{ event.extra.vpc or 'not reported' }}\n"
               "Probe tier: {{ event.extra.monitor_tier or event.extra.tier or 'not reported' }}\n"
               "{% if event.extra.down_seconds %}Previous downtime: {{ event.extra.down_seconds }} seconds\n{% endif %}"
               "{% if event.extra.unknown_seconds %}Previous unknown interval: {{ event.extra.unknown_seconds }} seconds\n{% endif %}"
               "{% if event.extra.latency_ms is not none %}Current latency: {{ event.extra.latency_ms }} ms\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Confirm stability and review the earlier outage or monitoring gap before closing the incident.",
        next_steps="1. Verify consecutive healthy probes and dependent services.\n2. Review the incident timeline, deployment, and failing signal.\n3. Close the earlier alert only when the cause and stability are understood.",
        why_it_matters="Availability has returned, but the recovery event does not explain the cause of the interruption.",
        evidence="The service projection observed the configured recovery threshold and includes the measured downtime or unknown interval when available.",
        monitoring_method="The configured service probe and service-state projection.",
        impact="Requests are succeeding again; instability may still cause another interruption.",
        recovery="This is the recovery event for service.down, service.degraded, or an emitted service.unknown state as applicable.",
        preview_extra={"service_name": "payments-api", "vpc": "prod", "monitor_tier": "http_alive", "consecutive_successes": 2, "down_seconds": 180, "latency_ms": 42},
    ),
    "probe.agent.stale": _contract(
        title="Probe agent stale · {{ event.extra.service_name or event.target.name or event.target.id or 'monitoring scope' }}",
        what_happened="The probe agent stopped reporting within its expected heartbeat window.",
        facts=("Scope/VPC: {{ event.extra.vpc or event.target.name or event.target.id or 'not reported' }}\n"
               "Last report: {{ event.extra.last_report or 'not reported' }}\n"
               "{% if event.extra.age_seconds %}Silent for: {{ event.extra.age_seconds }} seconds\n{% endif %}"
               "{% if event.extra.agent_version %}Agent version: {{ event.extra.agent_version }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Restore monitoring coverage or explicitly accept the blind interval; do not treat silence as proof that services are down.",
        next_steps="1. Check the probe process, host connectivity, credentials, and last error.\n2. Independently check critical services during the blind interval.\n3. Restore the agent and verify a fresh heartbeat.",
        why_it_matters="BlackWatch cannot reliably monitor the affected services while the probe is silent.",
        evidence="The staleness detector exceeded the heartbeat threshold using the last reported timestamp.",
        monitoring_method="Probe-agent heartbeat and staleness monitoring.",
        impact="Service outages or security-relevant changes may go undetected in the affected scope.",
        recovery="probe.agent.recovered is the monitoring-coverage recovery event; service.up is a separate service-health event.",
        preview_extra={"vpc": "prod", "last_report": "2026-08-25T09:55:00Z", "age_seconds": 600, "agent_version": "1.0"},
    ),
    "probe.agent.recovered": _contract(
        title="Probe agent recovered · {{ event.extra.vpc or event.target.name or event.target.id or 'monitoring scope' }}",
        what_happened="The previously silent probe agent reported again.",
        facts=("Scope/VPC: {{ event.extra.vpc or event.target.name or event.target.id or 'not reported' }}\n"
               "Report: {{ event.event_time }}\n"
               "{% if event.extra.last_report %}Previous report: {{ event.extra.last_report }}\n{% endif %}"
               "{% if event.extra.agent_version %}Agent version: {{ event.extra.agent_version }}{% endif %}"),
        decision="Confirm coverage is stable and account for evidence that may be missing from the silence interval.",
        next_steps="1. Verify consecutive heartbeats.\n2. Review the silent interval and independently checked service state.\n3. Confirm the agent configuration and close the coverage incident when stable.",
        why_it_matters="Monitoring visibility has returned, but the blind interval may contain delayed or missing evidence.",
        evidence="A new heartbeat was received after the staleness detector emitted probe.agent.stale.",
        monitoring_method="Probe-agent heartbeat and recovery projection.",
        impact="Service monitoring is available again; the previous coverage gap still needs review.",
        recovery="This is the recovery event for probe.agent.stale; it does not recover service.down or service.unknown alerts.",
        preview_extra={"vpc": "prod", "last_report": "2026-08-25T09:55:00Z", "agent_version": "1.0"},
    ),
    "probe.agent.first_seen": _contract(
        title="New probe agent seen · {{ event.extra.vpc or event.target.name or event.target.id or 'monitoring scope' }}",
        what_happened="A probe agent reported for the first time in this monitoring scope.",
        facts=("Scope/VPC: {{ event.extra.vpc or event.target.name or event.target.id or 'not reported' }}\n"
               "First report: {{ event.event_time }}\n"
               "{% if event.extra.agent_version %}Agent version: {{ event.extra.agent_version }}\n{% endif %}"
               "{% if event.extra.result_count is not none %}Results in report: {{ event.extra.result_count }}{% endif %}"),
        decision="Confirm the new probe is expected, assigned to the right environment, and authorized to report these targets.",
        next_steps="1. Verify the VPC/account and probe owner.\n2. Confirm target assignment, credentials, and monitoring tier.\n3. Record the onboarding change or remove the unexpected agent.",
        why_it_matters="A new monitoring source changes coverage and may represent an approved deployment or an unmanaged path.",
        evidence="The projection observed the first heartbeat for this probe scope.",
        monitoring_method="Probe-agent heartbeat and first-seen projection.",
        impact="The probe will contribute service coverage; incorrect enrollment can create false confidence or unnecessary load.",
        recovery="No recovery event is required for first-seen onboarding; review is closed by owner confirmation.",
        preview_extra={"vpc": "prod", "agent_version": "1.0", "result_count": 12},
    ),
}


def _cloudtrail_contract(key: str, label: str, what: str, decision: str, steps: str, impact: str) -> dict[str, Any]:
    return _contract(
        title=label,
        what_happened=what,
        facts=("Actor: {{ event.actor.principal or 'not reported' }}\n"
               "{% if event.actor.is_root %}Actor type: root\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.actor.user_agent %}User agent: {{ event.actor.user_agent }}\n{% endif %}"
               "Account: {{ event.source.account or 'not reported' }}\n"
               "Region: {{ event.source.region or 'not reported' }}\n"
               "Target: {{ event.target.name or event.target.id or 'not reported' }}\n"
               "Operation: {{ event.extra.event_name or event.action }}\n"
               "{% if event.extra.error_code %}Error: {{ event.extra.error_code }}{% endif %}"
               "{% if event.extra.mfa_used %}\nMFA: {{ event.extra.mfa_used }}{% endif %}\n"
               "When: {{ event.event_time }}"),
        decision=decision,
        next_steps=steps,
        why_it_matters=impact,
        evidence="CloudTrail normalized the operation, actor, target, account, region, and available security flags shown above.",
        monitoring_method="AWS CloudTrail management events and the BlackWatch normalized CloudTrail adapter.",
        impact=impact,
        recovery="No automatic recovery is claimed; close this review only after the approved state or follow-up change is verified.",
        preview_extra={"event_name": key.split(".")[-1], "account": "123456789012", "region": "us-east-1"},
    )


_AWS_IAM = {
    "iam.access_key.create": _cloudtrail_contract("iam.access_key.create", "IAM access key created", "A new IAM access key was created.", "Confirm the key owner, purpose, and expiry plan.", "Identify the key owner; check last-used and scope; record rotation/expiry; disable it if the creation was not approved.", "A long-lived key can provide programmatic access outside the normal human login path."),
    "iam.mfa.deactivate": _cloudtrail_contract("iam.mfa.deactivate", "IAM MFA disabled", "Multi-factor authentication was disabled for an identity.", "Treat this as urgent unless an approved recovery or enrollment change explains it.", "Confirm the affected identity and approver; re-enable MFA; review recent logins and access-key activity.", "Removing MFA lowers protection against credential takeover."),
    "iam.role.update_trust": _cloudtrail_contract("iam.role.update_trust", "IAM role trust policy changed", "An IAM role trust policy was changed.", "Verify every trusted principal and whether the role can now be assumed by an unintended account or service.", "Review the before/after policy and change ticket; remove unintended principals; test the approved trust path.", "Trust-policy changes can grant cross-account or workload access without changing the role's permissions."),
    "iam.user.create": _cloudtrail_contract("iam.user.create", "IAM user created", "A new IAM user was created.", "Confirm the user, owner, account, and intended authentication method are approved.", "Review groups, policies, login profile, MFA, and access keys; disable or remove an unapproved user.", "An unexpected identity can become a persistent access path."),
    "iam.user.delete": _cloudtrail_contract("iam.user.delete", "IAM user deleted", "An IAM user was deleted.", "Confirm deletion was approved and that required ownership, access, and audit evidence was transferred.", "Check the change record and dependent workloads; verify keys, login profiles, and ownership were handled before closing.", "Deletion can interrupt automation or remove an identity needed for audit and recovery."),
    "iam.role.create": _cloudtrail_contract("iam.role.create", "IAM role created", "A new IAM role was created.", "Confirm the role's trust policy, permissions, owner, and intended use.", "Review attached and inline policies; check trusted principals and external IDs; document or remove an unapproved role.", "A role can create a new privilege or cross-account access path."),
    "iam.role.delete": _cloudtrail_contract("iam.role.delete", "IAM role deleted", "An IAM role was deleted.", "Confirm the deletion will not break workloads or remove a required control.", "Check dependent services and trust relationships; verify replacement/rollback and record the approved change.", "Deleting a role can interrupt services or remove evidence of how access was granted."),
    "iam.login_profile.create": _cloudtrail_contract("iam.login_profile.create", "IAM console login profile created", "A console login profile was created for an IAM user.", "Confirm the user is approved for console access and will enroll MFA.", "Verify owner and password handling; require MFA; review the user's policies and recent access.", "A new console credential expands interactive access to the account."),
    "iam.policy.attach": _cloudtrail_contract("iam.policy.attach", "IAM policy attached", "A policy was attached to an IAM principal.", "Determine whether the policy grants more access than the principal requires.", "Inspect policy ARN, principal, effective permissions, and change ticket; detach or restrict it if unauthorized.", "Attached policy permissions take effect immediately for the principal."),
    "iam.policy.put_inline": _cloudtrail_contract("iam.policy.put_inline", "Inline IAM policy changed", "An inline IAM policy was added or changed.", "Review the resulting permissions, especially wildcard or privilege-escalation actions.", "Compare the policy with the approved diff; remove unintended statements; test the least-privilege result.", "Inline policy changes can silently grant broad access to one identity."),
    "kms.key.disable": _cloudtrail_contract("kms.key.disable", "KMS key disabled", "A KMS key was disabled.", "Confirm the key is not required by production encryption, backups, or recovery workflows.", "Identify dependent resources; restore the key if unauthorized; verify decrypt/encrypt paths and owner approval.", "Disabling a key can immediately break access to encrypted data."),
    "kms.key.delete_scheduled": _cloudtrail_contract("kms.key.delete_scheduled", "KMS key deletion scheduled", "Deletion was scheduled for a KMS key.", "Treat this as urgent and confirm the deletion window and final approval.", "Check key dependencies and backups; cancel the schedule if unauthorized; preserve the owner decision and recovery plan.", "A scheduled deletion can make encrypted data permanently unreadable after the waiting period."),
    "kms.policy.put": _cloudtrail_contract("kms.policy.put", "KMS key policy changed", "A KMS key policy was changed.", "Verify every new principal and whether the policy permits wildcard or cross-account use.", "Review the policy diff and key dependencies; remove unintended access; validate approved encryption workflows.", "Key policy changes control who can use or administer encrypted data."),
    "kms.grant.create": _cloudtrail_contract("kms.grant.create", "KMS grant created", "A grant was created for a KMS key.", "Confirm the grantee, operations, constraints, and expiry are approved.", "Inspect grant details and workload owner; retire an unapproved grant; check whether data was accessed.", "A grant can provide direct cryptographic use without a broad key-policy change."),
    "kms.rotation.disable": _cloudtrail_contract("kms.rotation.disable", "KMS key rotation disabled", "Automatic KMS key rotation was disabled.", "Confirm the exception and rotation owner before leaving the key in this state.", "Review the key policy and compliance requirement; re-enable rotation or document the approved exception.", "Disabling rotation increases the lifetime and exposure of a cryptographic key."),
    "cloudtrail.trail.delete": _cloudtrail_contract("cloudtrail.trail.delete", "CloudTrail trail deleted", "A CloudTrail trail was deleted.", "Treat this as a logging-control change and confirm it is explicitly approved.", "Identify the affected account/region; restore or replace the trail; verify delivery and retention before closing.", "Deleting a trail can remove audit visibility and create an evidence gap."),
    "cloudtrail.logging.stop": _cloudtrail_contract("cloudtrail.logging.stop", "CloudTrail logging stopped", "CloudTrail logging was stopped for a trail.", "Restore logging unless an approved maintenance window is active.", "Confirm the trail and account; restart logging; verify new events arrive and record the blind interval.", "Security and operational actions may go unrecorded while logging is stopped."),
    "cloudtrail.trail.update": _cloudtrail_contract("cloudtrail.trail.update", "CloudTrail trail changed", "A CloudTrail trail configuration changed.", "Verify the destination, selectors, encryption, retention, and access settings against the baseline.", "Review the exact request and change ticket; restore missing coverage or controls; validate delivery with a test event.", "A trail update can weaken audit coverage without stopping logging outright."),
    "auth.console.login": _cloudtrail_contract("auth.console.login", "AWS console login · {{ event.actor.principal or 'unknown identity' }}", "An AWS console login was observed.", "Decide whether the identity, source, MFA state, and login outcome match expected human access.", "Confirm the owner and source; review MFA and nearby failures; investigate or protect the identity when unexpected.", "A console login establishes interactive control-plane access."),
    "auth.federated.login": _cloudtrail_contract("auth.federated.login", "Federated AWS login · {{ event.actor.principal or 'unknown identity' }}", "A federated AWS login was observed.", "Confirm the federated identity, source, provider, and expected access window.", "Check the identity-provider sign-in and role session; review the assumed role and source; revoke or investigate if unexpected.", "Federated access can grant temporary control-plane permissions through an external identity provider."),
}


def _s3_contract(key: str, label: str, what: str, decision: str, steps: str, impact: str, *, object_access: bool = False) -> dict[str, Any]:
    if object_access:
        facts = ("Object: {{ event.target.id or 'not reported' }}\n"
                 "Operation: {{ event.extra.operation or 'not reported' }}\n"
                 "{% if event.actor.principal %}Requester: {{ event.actor.principal }}\n{% endif %}"
                 "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
                 "Status: {{ event.extra.http_status or 'not reported' }}\n"
                 "{% if event.extra.bytes_sent is not none %}Bytes: {{ event.extra.bytes_sent }}\n{% endif %}"
                 "{% if event.extra.error_code %}Error: {{ event.extra.error_code }}\n{% endif %}"
                 "When: {{ event.event_time }}")
    else:
        facts = ("Bucket: {{ event.target.name or event.target.id or event.extra.bucket_name or 'not reported' }}\n"
                 "Account: {{ event.source.account or event.extra.account or 'not reported' }}\n"
                 "Region: {{ event.source.region or event.extra.region or 'not reported' }}\n"
                 "{% if event.extra.public is not none %}Public: {{ event.extra.public }}\n{% endif %}"
                 "{% if event.extra.public_reasons %}Public reasons: {{ event.extra.public_reasons | join(', ') }}\n{% endif %}"
                 "{% if event.extra.encryption %}Encryption: {{ event.extra.encryption }}\n{% endif %}"
                 "{% if event.extra.versioning %}Versioning: {{ event.extra.versioning }}\n{% endif %}"
                 "{% if event.extra.last_scan %}Last scan: {{ event.extra.last_scan }}\n{% endif %}"
                 "Detected: {{ event.event_time }}")
    return _contract(
        title=label,
        what_happened=what,
        facts=facts,
        decision=decision,
        next_steps=steps,
        why_it_matters=impact,
        evidence="S3 access, CloudTrail management, or inventory-projection fields shown above are the available evidence.",
        monitoring_method="S3 access logs, CloudTrail S3 management events, and the bucket inventory projection.",
        impact=impact,
        recovery="No automatic recovery is claimed; verify the approved access or bucket state before closing this review.",
        preview_extra={"bucket_name": "customer-data-prod", "account": "123456789012", "region": "us-east-1", "operation": "GET.OBJECT", "http_status": 403},
    )


_AWS_S3 = {
    "s3.object.access.anonymous": _s3_contract("s3.object.access.anonymous", "Anonymous S3 object access", "An unauthenticated request accessed an S3 object.", "Treat this as unexpected unless the bucket/object is intentionally public.", "Confirm the bucket and object exposure; inspect the request status and source; remove public access or document the approved public use.", "Anonymous access can expose data without an attributable AWS identity.", object_access=True),
    "s3.object.access": _s3_contract("s3.object.access", "S3 object accessed", "An S3 object access request was observed.", "Decide whether the requester, operation, object, and result match expected use.", "Confirm the requester and source; review the object sensitivity and status; investigate unusual access or repeated errors.", "Object access may expose, modify, or delete stored data depending on the operation.", object_access=True),
    "s3.bucket.create": _s3_contract("s3.bucket.create", "S3 bucket created", "An S3 bucket was created.", "Confirm the bucket owner, account, region, encryption, logging, versioning, and public-access controls.", "Review the bucket baseline before data is placed in it; enable required controls and assign an owner.", "A new bucket can create an unmanaged data store or public exposure.",),
    "s3.bucket.delete": _s3_contract("s3.bucket.delete", "S3 bucket deleted", "An S3 bucket deletion operation was observed.", "Treat as urgent and confirm deletion is approved and the required data-retention plan is complete.", "Check the change ticket and backups; stop or investigate the deletion when unauthorized; preserve evidence.", "Deletion can make stored data and recovery copies unavailable.",),
    "s3.bucket.acl.put": _s3_contract("s3.bucket.acl.put", "S3 bucket ACL changed", "An S3 bucket ACL was changed.", "Verify every grantee and whether the ACL creates public or cross-account access.", "Review the ACL diff and effective access; remove unintended grants; validate with a safe access test.", "ACL changes can expose or alter access to bucket data.",),
    "s3.bucket.policy.put": _s3_contract("s3.bucket.policy.put", "S3 bucket policy changed", "An S3 bucket policy was changed.", "Confirm principals, actions, resources, and conditions are least-privilege and intentional.", "Inspect the policy diff; check public/cross-account paths; restore the approved policy if unauthorized.", "Bucket policies can grant broad read, write, or delete access.",),
    "s3.bucket.bpa.put": _s3_contract("s3.bucket.bpa.put", "S3 public access block changed", "A bucket public-access-block setting was changed.", "Determine whether the change weakens a required preventive control.", "Review all four block settings and the bucket policy/ACL; restore the block or approve the exception.", "A weaker public-access block can make later ACL or policy changes externally reachable.",),
    "s3.bucket.bpa.delete": _s3_contract("s3.bucket.bpa.delete", "S3 public access block removed", "The bucket public-access block was removed.", "Treat this as an exposure-enabling change until the owner confirms it.", "Inspect bucket policy and ACL immediately; restore the block if public access is not intended; check access logs.", "Removing the block allows other controls to expose bucket data.",),
    "s3.bucket.public": _s3_contract("s3.bucket.public", "S3 bucket became public", "The inventory projection detected that the bucket is publicly accessible.", "Assume exposure is unintended unless a documented public-data exception exists.", "Identify the public reason; remove the policy/ACL/BPA condition that exposes it; review access logs and preserve evidence.", "Public access can expose stored data to unauthenticated or unintended principals.",),
    "s3.bucket.public_removed": _s3_contract("s3.bucket.public_removed", "S3 bucket public access removed", "The bucket is no longer publicly accessible in the latest inventory state.", "Confirm the exposure was intentionally remediated and that required application access still works.", "Review the changed control and access logs; validate private access paths; close the earlier exposure only after verification.", "The exposure appears resolved, but prior public access may have exposed data.",),
    "s3.bucket.encryption.delete": _s3_contract("s3.bucket.encryption.delete", "S3 bucket encryption removed", "Default bucket encryption was removed.", "Restore the required encryption control unless an approved exception explains the change.", "Check bucket/object encryption behavior; restore default encryption; review the change window and affected data.", "New objects may be stored without the expected encryption protection.",),
    "s3.bucket.encryption_added": _s3_contract("s3.bucket.encryption_added", "S3 bucket encryption restored", "The inventory projection observed default encryption after the bucket was previously unencrypted.", "Confirm the restored encryption state is the approved algorithm/key and that affected data was handled.", "Verify the current encryption configuration and application writes; review the unencrypted interval; close the earlier gap only after validation.", "New objects are protected again, but objects written during the unencrypted interval may need review.",),
    "s3.bucket.versioning.put": _s3_contract("s3.bucket.versioning.put", "S3 bucket versioning changed", "The bucket versioning configuration changed.", "Confirm the resulting state and whether retention/recovery requirements remain satisfied.", "Review the requested versioning status and MFA delete; restore the approved setting and check lifecycle impact.", "Versioning changes affect recovery from deletion, overwrite, and ransomware-like activity.",),
    "s3.bucket.versioning_off": _s3_contract("s3.bucket.versioning_off", "S3 bucket versioning disabled", "Bucket versioning was suspended or disabled.", "Treat this as a recovery-control change and confirm explicit approval.", "Restore versioning when unauthorized; verify retention and recent object changes; preserve the owner decision.", "Without versioning, overwritten or deleted objects may not be recoverable.",),
    "s3.bucket.logging.put": _s3_contract("s3.bucket.logging.put", "S3 bucket logging changed", "Bucket access logging configuration changed.", "Confirm logging remains enabled, reaches the approved destination, and cannot be altered by the bucket owner unexpectedly.", "Review the destination and change; restore logging if disabled; verify a test access record arrives.", "Missing access logs reduce the ability to investigate data exposure.",),
    "s3.bucket.unencrypted": _s3_contract("s3.bucket.unencrypted", "Unencrypted S3 bucket detected", "The inventory projection observed a bucket without expected default encryption.", "Decide whether the bucket is allowed to store data in this state.", "Enable the approved encryption; identify objects needing remediation; verify the encryption baseline in the next scan.", "Objects may be stored without the required at-rest protection.",),
    "s3.bucket.first_seen": _s3_contract("s3.bucket.first_seen", "S3 bucket first seen", "The inventory projection observed this bucket for the first time after its baseline.", "Confirm the bucket is expected, owned, and configured for the correct environment.", "Validate encryption, public access, versioning, logging, tags, and retention; record the owner.", "A new bucket may be legitimate or an unmanaged data store.",),
    "s3.bucket.disappeared": _s3_contract("s3.bucket.disappeared", "S3 bucket disappeared from inventory", "A previously tracked bucket was absent from a completed inventory scan.", "Determine whether the bucket was deleted or the inventory result is incomplete before taking destructive action.", "Confirm scan completeness and account; check CloudTrail for deletion; preserve last-known state and recovery evidence.", "The bucket may be unavailable, deleted, or missing from monitoring; a partial scan must not be treated as deletion.",),
}


def _human_action(key: str) -> str:
    return " ".join(part.replace("_", " ") for part in key.split("."))


# Keep the catalog in parity with the CloudTrail/S3 producers. These actions
# are less specialized than the high-risk contracts above, but still receive
# their own event key, headline, decision, and manual-resolution semantics.
for _key in {
    "iam.access_key.update", "iam.access_key.delete", "iam.mfa.enable", "iam.mfa.delete",
    "iam.user.update", "iam.group.create", "iam.group.delete", "iam.group.add_user",
    "iam.group.remove_user", "iam.login_profile.update", "iam.login_profile.delete",
    "iam.policy.detach", "iam.policy.delete_inline", "iam.policy.create", "iam.policy.delete",
    "iam.policy.create_version", "iam.policy.delete_version", "iam.role.boundary.put",
    "iam.role.boundary.delete", "iam.user.boundary.put", "iam.user.boundary.delete",
    "kms.key.create", "kms.key.enable", "kms.key.delete_cancelled", "kms.grant.retire",
    "kms.grant.revoke", "kms.rotation.enable", "cloudtrail.logging.start", "cloudtrail.trail.create",
}:
    _AWS_IAM.setdefault(
        _key,
        _cloudtrail_contract(
            _key,
            f"AWS {_human_action(_key)}",
            f"The {_human_action(_key)} operation was observed.",
            "Confirm the actor, target, and resulting identity or key state are approved.",
            f"Review the {_human_action(_key)} request and change record; verify the resulting permissions or logging state; reverse or contain the change if unauthorized.",
            "An unreviewed control-plane change can alter access, encryption, or audit visibility.",
        ),
    )

for _key in {
    "s3.bucket.encryption.put", "s3.bucket.versioning_suspended", "s3.bucket.versioning_enabled",
    "s3.bucket.logging_disabled", "s3.bucket.policy.delete", "s3.bucket.lifecycle.put",
    "s3.bucket.replication.put", "s3.bucket.replication.delete", "s3.bucket.object_lock.put",
}:
    _AWS_S3.setdefault(
        _key,
        _s3_contract(
            _key,
            f"S3 {_human_action(_key.removeprefix('s3.'))}",
            f"The {_human_action(_key.removeprefix('s3.'))} operation was observed.",
            "Confirm the resulting bucket control is approved and preserves the required data-protection baseline.",
            f"Review the {_human_action(_key.removeprefix('s3.'))} request and effective bucket state; compare with the change record; restore the approved control if unauthorized.",
            "Bucket-control changes can affect exposure, retention, recovery, or data movement.",
        ),
    )


for _key, _title, _verb, _field, _decision, _steps, _recovery in [
    ("vpn.cert.expired", "VPN certificate expired", "is past its expiry time", "days_remaining", "Assume secure connectivity may fail until the live endpoint is verified and the certificate is replaced.", "Verify whether the expired certificate is live; replace it; validate the VPN trust chain; check for failed handshakes during the expired period.", "Manual renewal plus successful endpoint validation is required; no automatic recovery event is emitted."),
    ("vpn.cert.expiring.critical", "VPN certificate expires critically soon", "is inside the urgent renewal window", "days_remaining", "Treat this as an urgent outage-prevention task.", "Confirm the live endpoint uses this certificate; renew and deploy immediately; validate client trust and the VPN handshake; escalate if blocked.", "Manual renewal and endpoint validation are required until a certificate-recovered event exists."),
    ("vpn.cert.expiring.high", "VPN certificate expires soon", "is inside the high-risk renewal window", "days_remaining", "Renew or schedule immediately and confirm no deployment dependency fails first.", "Check the live endpoint certificate; confirm the owner and expiry plan; renew, deploy, and validate the full chain.", "A healthy probe after renewal is the recovery condition; no dedicated recovery action exists yet."),
    ("vpn.cert.expiring.warning", "VPN certificate entered its warning window", "entered the warning window", "days_remaining", "Decide whether renewal is scheduled and safe for the next deployment or use period.", "Identify the owner; confirm the live endpoint certificate; renew before the threshold; verify with a healthy probe.", "Record renewal and verification time until a certificate-recovered event is available."),
    ("vpn.cert.probe.failed", "VPN certificate check failed", "could not be read or evaluated", "error", "Decide whether this is a probe/permission failure or evidence that certificate health is unknown.", "Inspect the probe error and path permissions; confirm the certificate exists; run an independent endpoint check; repair the probe and verify a healthy result.", "A successful subsequent probe is recovery; until then, document why certificate health is trusted."),
]:
    _VPN[_key] = _contract(
        title=f"{_title} · {{{{ event.extra.subject or event.target.name or event.target.id or 'unknown certificate' }}}}",
        what_happened=f"The monitored VPN certificate {_verb}.",
        facts=("Certificate: {{ event.extra.subject or event.target.name or event.target.id or 'not reported' }}\n"
               "Server: {{ event.target.name or event.target.id or event.extra.server or 'unknown' }}\n"
               "{% if event.extra.days_remaining is not none %}Days remaining: {{ event.extra.days_remaining }}\n{% endif %}"
               "{% if event.extra.not_after %}Expires: {{ event.extra.not_after }}\n{% endif %}"
               "{% if event.extra.path %}Path: {{ event.extra.path }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision=_decision,
        next_steps=_steps,
        why_it_matters="An expired, near-expiry, or unreadable certificate can break secure VPN connections and create an avoidable outage.",
        evidence=("Certificate source and expiry fields are shown above. "
                   "{% if event.extra.error %}Probe error: {{ event.extra.error }}{% endif %}"),
        monitoring_method="OpenVPN certificate inventory and expiry/probe checks.",
        impact="Clients may reject the endpoint, or BlackWatch may be unable to confirm secure connectivity.",
        recovery=_recovery,
        preview_extra={"server": "vpn-1", "subject": "vpn-1-server", "days_remaining": 5, "not_after": "2026-08-30T00:00:00Z"},
    )


_CERT = {
    "cert.expired": _contract(
        title="Certificate expired{% if event.extra.subject or event.target.name or event.target.id %} · {{ event.extra.subject or event.target.name or event.target.id }}{% endif %}",
        what_happened="The monitored certificate is past its not-after time.",
        facts=("{% if event.extra.host or event.target.name or event.target.id %}Host: {{ event.extra.host or event.target.name or event.target.id }}\n{% endif %}"
               "{% if event.extra.port is defined and event.extra.port is not none %}Port: {{ event.extra.port }}\n{% endif %}"
               "{% if event.extra.subject %}Subject: {{ event.extra.subject }}\n{% endif %}"
               "{% if event.extra.issuer %}Issuer: {{ event.extra.issuer }}\n{% endif %}"
               "{% if event.extra.sans %}SANs: {{ event.extra.sans | join(', ') }}\n{% endif %}"
               "{% if event.extra.not_after %}Expired at: {{ event.extra.not_after }}\n{% endif %}"
               "{% if event.extra.days_remaining is defined and event.extra.days_remaining is not none %}Days remaining: {{ event.extra.days_remaining }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Renew and deploy now unless an approved replacement is already active; treat the endpoint as at risk until verified.",
        next_steps="1. Confirm the expired certificate is the one served by the endpoint.\n2. Renew and deploy the replacement immediately.\n3. Validate the full trust chain and client handshake.\n4. Review failures since expiry and record the owner and change.",
        why_it_matters="Clients may reject the endpoint, causing an outage or unsafe workarounds.",
        evidence="The certificate subject, issuer, expiry time, and days remaining are the available expiry evidence.",
        monitoring_method="Configured TLS certificate inventory and expiry checks.",
        impact="Secure clients may be unable to connect to the endpoint.",
        recovery="A later successful probe confirms the endpoint is readable, but renewal and validation remain manual resolution steps.",
        preview_extra={"host": "api.example.com", "port": 443, "subject": "CN=api.example.com", "issuer": "Example CA", "sans": ["api.example.com"], "not_after": "2026-08-28T00:00:00Z", "days_remaining": -1},
    ),
    "cert.expiring.critical": _contract(
        title="Certificate expires critically soon{% if event.extra.subject or event.target.name or event.target.id %} · {{ event.extra.subject or event.target.name or event.target.id }}{% endif %}",
        what_happened="The monitored certificate is inside the critical renewal window.",
        facts=("{% if event.extra.host or event.target.name or event.target.id %}Host: {{ event.extra.host or event.target.name or event.target.id }}\n{% endif %}"
               "{% if event.extra.port is defined and event.extra.port is not none %}Port: {{ event.extra.port }}\n{% endif %}"
               "{% if event.extra.subject %}Subject: {{ event.extra.subject }}\n{% endif %}"
               "{% if event.extra.issuer %}Issuer: {{ event.extra.issuer }}\n{% endif %}"
               "{% if event.extra.sans %}SANs: {{ event.extra.sans | join(', ') }}\n{% endif %}"
               "{% if event.extra.not_after %}Expires at: {{ event.extra.not_after }}\n{% endif %}"
               "{% if event.extra.days_remaining is defined and event.extra.days_remaining is not none %}Days remaining: {{ event.extra.days_remaining }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Renew and deploy immediately; do not wait for the next warning window.",
        next_steps="1. Confirm the live endpoint uses this certificate.\n2. Renew and deploy immediately.\n3. Validate the chain, hostname, and client handshake.\n4. Escalate if ownership or deployment is blocked.",
        why_it_matters="A near-term expiry can become an avoidable service outage before the next maintenance window.",
        evidence="The certificate identity, expiry time, and days remaining are the available expiry evidence.",
        monitoring_method="Configured TLS certificate inventory and expiry checks.",
        impact="The endpoint may fail secure connection validation within the critical window.",
        recovery="A successful post-renewal probe confirms reachability; manual renewal and deployment close the expiry risk.",
        preview_extra={"host": "api.example.com", "port": 443, "subject": "CN=api.example.com", "issuer": "Example CA", "sans": ["api.example.com"], "not_after": "2026-09-02T00:00:00Z", "days_remaining": 4},
    ),
    "cert.expiring.high": _contract(
        title="Certificate expires soon{% if event.extra.subject or event.target.name or event.target.id %} · {{ event.extra.subject or event.target.name or event.target.id }}{% endif %}",
        what_happened="The monitored certificate is inside the high-risk renewal window.",
        facts=("{% if event.extra.host or event.target.name or event.target.id %}Host: {{ event.extra.host or event.target.name or event.target.id }}\n{% endif %}"
               "{% if event.extra.port is defined and event.extra.port is not none %}Port: {{ event.extra.port }}\n{% endif %}"
               "{% if event.extra.subject %}Subject: {{ event.extra.subject }}\n{% endif %}"
               "{% if event.extra.issuer %}Issuer: {{ event.extra.issuer }}\n{% endif %}"
               "{% if event.extra.sans %}SANs: {{ event.extra.sans | join(', ') }}\n{% endif %}"
               "{% if event.extra.not_after %}Expires at: {{ event.extra.not_after }}\n{% endif %}"
               "{% if event.extra.days_remaining is defined and event.extra.days_remaining is not none %}Days remaining: {{ event.extra.days_remaining }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Assign the renewal owner and schedule deployment before the certificate enters the critical window.",
        next_steps="1. Confirm the endpoint, owner, and change window.\n2. Assign the renewal owner and schedule deployment.\n3. Validate the full chain after deployment.\n4. Escalate if the schedule cannot meet the remaining lifetime.",
        why_it_matters="There is still time to plan, but delay can turn renewal into an outage response.",
        evidence="The certificate identity, expiry time, and days remaining are the available expiry evidence.",
        monitoring_method="Configured TLS certificate inventory and expiry checks.",
        impact="The endpoint could lose trusted connectivity if renewal is not completed in time.",
        recovery="A successful post-renewal probe confirms reachability; the planned renewal must still be recorded manually.",
        preview_extra={"host": "api.example.com", "port": 443, "subject": "CN=api.example.com", "issuer": "Example CA", "sans": ["api.example.com"], "not_after": "2026-09-10T00:00:00Z", "days_remaining": 12},
    ),
    "cert.expiring.warning": _contract(
        title="Certificate renewal warning{% if event.extra.subject or event.target.name or event.target.id %} · {{ event.extra.subject or event.target.name or event.target.id }}{% endif %}",
        what_happened="The monitored certificate entered its warning window.",
        facts=("{% if event.extra.host or event.target.name or event.target.id %}Host: {{ event.extra.host or event.target.name or event.target.id }}\n{% endif %}"
               "{% if event.extra.port is defined and event.extra.port is not none %}Port: {{ event.extra.port }}\n{% endif %}"
               "{% if event.extra.subject %}Subject: {{ event.extra.subject }}\n{% endif %}"
               "{% if event.extra.issuer %}Issuer: {{ event.extra.issuer }}\n{% endif %}"
               "{% if event.extra.sans %}SANs: {{ event.extra.sans | join(', ') }}\n{% endif %}"
               "{% if event.extra.not_after %}Expires at: {{ event.extra.not_after }}\n{% endif %}"
               "{% if event.extra.days_remaining is defined and event.extra.days_remaining is not none %}Days remaining: {{ event.extra.days_remaining }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Confirm that renewal is scheduled and owned before the remaining lifetime becomes high risk.",
        next_steps="1. Identify the certificate owner and renewal method.\n2. Schedule renewal before the next urgency threshold.\n3. Confirm deployment dependencies and a validation check.\n4. Monitor the endpoint until renewal is complete.",
        why_it_matters="Early action keeps renewal inside a planned change window and reduces outage risk.",
        evidence="The certificate identity, expiry time, and days remaining are the available expiry evidence.",
        monitoring_method="Configured TLS certificate inventory and expiry checks.",
        impact="No outage is inferred, but the endpoint is moving toward a higher renewal risk.",
        recovery="Record the scheduled or completed renewal and confirm it with a successful probe; no automatic closure is claimed.",
        preview_extra={"host": "api.example.com", "port": 443, "subject": "CN=api.example.com", "issuer": "Example CA", "sans": ["api.example.com"], "not_after": "2026-09-25T00:00:00Z", "days_remaining": 27},
    ),
    "cert.probe.failed": _contract(
        title="Certificate probe failed{% if event.extra.host or event.target.name or event.target.id %} · {{ event.extra.host or event.target.name or event.target.id }}{% endif %}",
        what_happened="BlackWatch could not read or evaluate the certificate at the monitored endpoint.",
        facts=("{% if event.extra.host or event.target.name or event.target.id %}Host: {{ event.extra.host or event.target.name or event.target.id }}\n{% endif %}"
               "{% if event.extra.port is defined and event.extra.port is not none %}Port: {{ event.extra.port }}\n{% endif %}"
               "{% if event.extra.error %}Probe error: {{ event.extra.error }}\n{% endif %}"
               "Detected: {{ event.event_time }}"),
        decision="Treat certificate health as unknown; do not label the certificate expired until an independent check confirms it.",
        next_steps="1. Inspect the probe error and endpoint reachability.\n2. Check permissions, DNS, TLS negotiation, and the certificate path.\n3. Run an independent endpoint check.\n4. Repair the probe and verify a successful result.",
        why_it_matters="A failed check creates a monitoring blind spot and may hide an expiry or endpoint outage.",
        evidence="{% if event.extra.error %}The producer reported this probe error: {{ event.extra.error }}{% endif %}\n",
        monitoring_method="Configured TLS endpoint probe and certificate parser.",
        impact="Certificate health cannot currently be confirmed; connection impact is unknown.",
        recovery="A later successful probe is the matching recovery signal; it does not imply the certificate was previously expired.",
        preview_extra={"host": "api.example.com", "port": 443, "subject": "", "issuer": "", "sans": [], "not_after": "", "days_remaining": None, "error": "TLS handshake timeout"},
    ),
}


_HOST_DETAIL = {
    "host.agent.stale": ("The host agent has not reported within its expected heartbeat window.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; last report: {{ event.extra.last_report or 'not reported' }}; silence: {{ event.extra.silence_seconds or 'not reported' }} seconds.", "Restore telemetry or explicitly accept the monitoring-coverage gap.", "Check the agent process, host reachability, credentials, and last error; restore the agent; verify a new heartbeat.", "The host is outside reliable monitoring coverage and security changes may be missed."),
    "host.agent.recovered": ("The previously silent host agent reported again.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; report time: {{ event.event_time }}; version: {{ event.extra.agent_version or 'not reported' }}.", "Confirm the agent is stable before treating the monitoring gap as closed.", "Check consecutive heartbeats and review the silence interval and agent logs for cause.", "Telemetry is available again, but events during the silence window may be missing."),
    "host.auth.ssh.failure": ("An SSH authentication attempt failed.", "User: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; host: {{ event.target.name or event.target.id or 'unknown host' }}; when: {{ event.event_time }}.", "Decide whether this attempt was expected; one failure alone is not proof of intrusion.", "Confirm the user and source; review nearby failures and successful logins; follow the SSH credential runbook if unexplained.", "The attempt did not authenticate, but repeated or unusual failures can precede unauthorized access."),
    "host.auth.ssh.password.success": ("An SSH password authentication succeeded.", "User: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; host: {{ event.target.name or event.target.id or 'unknown host' }}; when: {{ event.event_time }}.", "Confirm that password-based SSH access is approved for this user and host.", "Verify the owner and source; review the change window and nearby failures; disable password access if it is not required.", "A successful password login establishes host access and may bypass stronger key-based controls."),
    "host.auth.ssh.success": ("An SSH authentication succeeded.", "User: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; host: {{ event.target.name or event.target.id or 'unknown host' }}; when: {{ event.event_time }}.", "Confirm that the user, source, and access method match the approved activity.", "Check the change window and session activity; investigate the source if the login is unexpected.", "The account established host access from the recorded source."),
    "host.bruteforce": ("Repeated SSH failures crossed the brute-force threshold for a host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; source: {{ event.actor.source_ip or 'not reported' }}; count: {{ event.extra.count_in_window or 'not reported' }}; window: {{ event.extra.window_seconds or 'not reported' }} seconds.", "Treat this as suspicious until the source is identified as an approved gateway or scanner.", "Check targeted accounts and successful logins; rate-limit or block the source; protect any affected accounts.", "Repeated failures can indicate password spraying or brute-force activity against the host."),
    "host.bruteforce.user": ("Repeated SSH failures targeted one local user.", "User: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; count: {{ event.extra.count_in_window or 'not reported' }}; window: {{ event.extra.window_seconds or 'not reported' }} seconds.", "Treat the account as at risk until its owner explains the activity.", "Review all sources and successful logins; lock or rotate the account if unauthorized; document the owner decision.", "Repeated attempts against one username can expose a weak or reused credential."),
    "host.sudo.failure": ("A sudo attempt failed on the host.", "User: {{ event.actor.principal or 'not reported' }}; host: {{ event.target.name or event.target.id or 'unknown host' }}; command: {{ event.extra.command or 'not reported' }}; when: {{ event.event_time }}.", "Determine whether the user was expected to request this privileged command.", "Review the command, user, TTY, and nearby successful sudo events; investigate or restrict the account if unexplained.", "A failed privilege attempt may reveal an unauthorized user probing for escalation."),
    "host.authorized_key.added": ("An authorized SSH key was added to the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; account: {{ event.actor.principal or event.extra.user or 'not reported' }}; key fingerprint: {{ event.extra.key_fingerprint or 'not reported' }}.", "Verify the key owner and confirm the addition was approved.", "Compare the fingerprint with the change record; remove it if unauthorized; rotate exposed credentials and review access.", "A new key can create persistent access without a password."),
    "host.user.added": ("A local user account was created on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; user: {{ event.extra.user or event.actor.principal or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Confirm the account, groups, shell, and owner are approved.", "Review the account creation change; inspect group/sudo membership; disable or remove unauthorized access according to policy.", "An unexpected local account can provide persistence or privilege escalation."),
    "host.port.opened": ("A new listening port was observed on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; port: {{ event.extra.port or 'not reported' }}; process: {{ event.extra.process or 'not reported' }}; address: {{ event.extra.address or 'not reported' }}.", "Decide whether the listener is an approved service and should be reachable.", "Identify the owning process; compare with the deployment record; restrict exposure or stop the process if unauthorized.", "A new listener changes the host attack surface and may expose an unexpected service."),
    "host.fim.modified": ("A monitored file was modified.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; actor: {{ event.actor.principal or event.extra.whodati or 'not reported' }}; hash: {{ event.extra.hash or 'not reported' }}.", "Verify whether the file change belongs to an approved release or configuration change.", "Compare before/after hashes and ownership; inspect the diff; restore or quarantine the file if unauthorized.", "A modified protected file can alter execution, authentication, or security controls."),
    "host.fim.deleted": ("A monitored file was deleted.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Treat the deletion as unauthorized until an approved change explains it.", "Confirm the change window; recover the file from a trusted source; inspect related access and process activity.", "Deleting a protected file can disable a service or remove evidence and controls."),
    "host.fim.created": ("A new file appeared in a monitored path.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; owner: {{ event.extra.owner or 'not reported' }}; hash: {{ event.extra.hash or 'not reported' }}.", "Determine whether the file is an approved deployment artifact or an unexpected payload.", "Identify the creator and process; scan the file; compare its hash with a trusted artifact; quarantine if unexplained.", "An unexpected file in a protected path may establish persistence or change runtime behavior."),
    "host.fim.perm_changed": ("Permissions on a monitored file changed.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; old mode: {{ event.extra.old_mode or 'not reported' }}; new mode: {{ event.extra.new_mode or 'not reported' }}.", "Confirm that the new permissions are required by the owner and approved change.", "Compare the modes and owner; restore least-privilege permissions if unauthorized; review the actor and nearby changes.", "A permission change can make credentials or executable code writable or readable by more users."),
    "host.fim.owner_changed": ("Ownership of a monitored file changed.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; old owner: {{ event.extra.old_owner or 'not reported' }}; new owner: {{ event.extra.new_owner or 'not reported' }}.", "Verify the new owner is expected and cannot create an unintended privilege path.", "Compare the owner with the change record; restore the expected owner; inspect process and sudo activity.", "Ownership controls who can alter a protected file and may affect privilege boundaries."),
    "host.fim.coverage": ("File-integrity monitoring coverage changed.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path or scope: {{ event.extra.path or event.extra.scope or 'not reported' }}; change: {{ event.extra.change_type or 'not reported' }}.", "Decide whether the coverage reduction or expansion is approved and understood.", "Check the FIM configuration diff; restore protected paths; validate a test event and record the owner.", "A coverage gap can allow important file changes to go undetected."),
    "host.service.added": ("A new service was detected on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; service: {{ event.extra.service_name or event.extra.service or 'not reported' }}; state: {{ event.extra.state or 'not reported' }}.", "Confirm the service is part of an approved deployment and has the expected privileges.", "Identify its package and owner; review startup settings and network listeners; disable it if unauthorized.", "An unapproved service can persist across reboot or expose a new network surface."),
    "host.cpu.anomaly": ("Host CPU behavior crossed the configured anomaly threshold.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; value: {{ event.extra.value or 'not reported' }}; baseline: {{ event.extra.baseline or 'not reported' }}; duration: {{ event.extra.duration_seconds or 'not reported' }} seconds.", "Decide whether the load is an approved workload or a symptom of abuse or failure.", "Identify the top process and deployment; check errors and capacity; contain or scale the workload if unexplained.", "Sustained CPU pressure can degrade services and may indicate runaway or malicious execution."),
    "host.cpu.normal": ("Host CPU behavior returned to its baseline.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; value: {{ event.extra.value or 'not reported' }}; baseline: {{ event.extra.baseline or 'not reported' }}; detected: {{ event.event_time }}.", "Confirm the earlier CPU condition is stable before closing the incident.", "Review the peak process and timeline; verify several normal samples; record the cause if known.", "Capacity has recovered, but the trigger may still require remediation."),
    "host.cron.changed": ("A monitored scheduled task changed.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; task: {{ event.extra.path or event.extra.command or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Verify the schedule, command, and owner against the approved change.", "Inspect the before/after definition; check the command and referenced files; remove unauthorized persistence.", "Scheduled tasks can execute code repeatedly without an interactive login."),
    "host.disk.critical": ("Disk usage crossed the critical threshold.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; mount: {{ event.extra.mount or 'not reported' }}; usage: {{ event.extra.value or 'not reported' }}; threshold: {{ event.extra.threshold or 'not reported' }}.", "Prevent service or logging failure before the filesystem fills.", "Identify the largest safe-to-remove consumers; extend or clean the volume; verify application and audit writes recover.", "A full filesystem can stop applications, databases, and evidence collection."),
    "host.disk.warn": ("Disk usage crossed the warning threshold.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; mount: {{ event.extra.mount or 'not reported' }}; usage: {{ event.extra.value or 'not reported' }}; threshold: {{ event.extra.threshold or 'not reported' }}.", "Decide whether planned cleanup or capacity work is needed before the critical threshold.", "Review growth and retention; clean approved data or expand capacity; monitor the next samples.", "The host still has capacity, but continued growth can become an outage."),
    "host.disk.recovered": ("Disk usage returned below the recovery threshold.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; mount: {{ event.extra.mount or 'not reported' }}; usage: {{ event.extra.value or 'not reported' }}; detected: {{ event.event_time }}.", "Confirm the filesystem remains stable and identify what reduced usage.", "Review cleanup or capacity changes; verify application, database, and audit writes; close the earlier disk alert when stable.", "Capacity is available again, but the growth cause may remain."),
    "host.file.changed": ("A monitored file changed on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; change: {{ event.extra.change_type or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Verify the change against a deployment or configuration record.", "Inspect the diff and hash; identify the process and owner; restore the trusted version if unauthorized.", "A change to a monitored file may alter behavior or security configuration."),
    "host.memory.exhausted": ("The host reported memory exhaustion.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; value: {{ event.extra.value or 'not reported' }}; threshold: {{ event.extra.threshold or 'not reported' }}; process: {{ event.extra.process or 'not reported' }}.", "Restore enough memory headroom to protect services and telemetry.", "Identify the largest consumers; check for a leak or workload spike; restart, scale, or contain according to the runbook.", "Memory exhaustion can terminate processes and make monitoring unreliable."),
    "host.memory.recovered": ("Host memory pressure returned to normal.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; value: {{ event.extra.value or 'not reported' }}; baseline: {{ event.extra.baseline or 'not reported' }}; detected: {{ event.event_time }}.", "Confirm memory remains stable and the pressure cause is understood.", "Review killed or restarted processes; verify several normal samples; document capacity or leak remediation.", "Memory headroom has returned, but the earlier pressure may recur."),
    "host.oom_kill": ("The kernel killed a process because of memory pressure.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; process: {{ event.extra.process or 'not reported' }}; pid: {{ event.extra.pid or 'not reported' }}; when: {{ event.event_time }}.", "Determine whether the killed process is critical and whether memory pressure is still active.", "Check service health and restart policy; inspect memory consumers and recent deploys; add capacity or contain the cause.", "A process was forcibly terminated and dependent service behavior may be degraded."),
    "host.collector.stalled": ("A host telemetry collector stopped producing expected data.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; collector: {{ event.extra.collector or 'not reported' }}; last report: {{ event.extra.last_report or 'not reported' }}.", "Restore the affected telemetry or explicitly accept the blind spot.", "Check the collector process, permissions, queue, and host resources; repair it; verify fresh events.", "The affected signal is not reliable and important changes may be missed."),
    "host.collector.recovered": ("A previously stalled host collector resumed reporting.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; collector: {{ event.extra.collector or 'not reported' }}; report: {{ event.event_time }}.", "Confirm the collector remains healthy before closing the coverage incident.", "Verify consecutive samples and inspect the stall interval for missing or delayed evidence.", "Telemetry is available again, but the stall window may contain a data gap."),
    "host.first_seen": ("A host was observed for the first time.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; instance: {{ event.extra.instance_id or 'not reported' }}; account: {{ event.source.account or 'not reported' }}; region: {{ event.source.region or 'not reported' }}.", "Confirm the host is expected and belongs to the correct account and environment.", "Identify the owner; validate the agent and baseline; enroll the host in the intended monitoring and access controls.", "An unknown host may be an approved new asset or an unmanaged resource."),
    "host.kernel.module.added": ("A kernel module was added to the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; module: {{ event.extra.module or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Treat the module as sensitive until its package, signer, and owner are verified.", "Compare with the approved kernel baseline; verify signer and package; unload and investigate if unauthorized.", "Kernel modules run with high privilege and can hide activity or alter host behavior."),
    "host.kernel.module.removed": ("A kernel module was removed from the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; module: {{ event.extra.module or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}.", "Determine whether the removal was planned and whether a required driver or control is now absent.", "Compare with the baseline and change record; check dependent services; restore or investigate if unexpected.", "Removing a module can disable security or workload functionality."),
    "host.package_db.corrupted": ("The host package database could not be read safely.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; database: {{ event.extra.path or 'not reported' }}; error: {{ event.extra.error or 'not reported' }}.", "Restore package-management integrity before trusting package or patch state.", "Back up the package metadata; repair it with the host runbook; verify package queries and audit the repair.", "A corrupt package database can hide changes and block safe security updates."),
    "host.package_db.recovered": ("The host package database became readable again.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; database: {{ event.extra.path or 'not reported' }}; detected: {{ event.event_time }}.", "Confirm package inventory and repair history are trustworthy before closing the alert.", "Run an inventory check; compare installed packages with the baseline; review the repair and missing update window.", "Package visibility is restored, but the earlier integrity gap may have hidden changes."),
    "host.packages.changed": ("Installed packages changed on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; package: {{ event.extra.package or 'not reported' }}; change: {{ event.extra.change_type or 'not reported' }}; version: {{ event.extra.version or 'not reported' }}.", "Verify the package change belongs to an approved patch or deployment.", "Compare before/after versions and repository; inspect post-install scripts and service changes; revert if unauthorized.", "Packages can add code, alter services, or introduce vulnerable components."),
    "host.process.first_seen": ("A process not previously seen on the host started.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; process: {{ event.extra.process or 'not reported' }}; pid: {{ event.extra.pid or 'not reported' }}; user: {{ event.actor.principal or event.extra.user or 'not reported' }}.", "Determine whether the process is an approved workload or an unexpected execution.", "Inspect the binary path, hash, parent, network connections, and deployment; stop or isolate if unexplained.", "A new process can be benign deployment activity or a persistence and execution signal."),
    "host.sudoers.changed": ("The sudoers configuration changed.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; change: {{ event.extra.change_type or 'not reported' }}.", "Verify that the change does not grant unintended privilege.", "Review the exact diff and syntax; compare the owner and approver; restore the trusted policy if unauthorized.", "Sudoers changes can grant root access or remove an important restriction."),
    "host.suid.added": ("A new SUID file was observed on the host.", "Host: {{ event.target.name or event.target.id or 'unknown host' }}; path: {{ event.extra.path or 'not reported' }}; owner: {{ event.extra.owner or 'not reported' }}; hash: {{ event.extra.hash or 'not reported' }}.", "Treat the file as a privilege-escalation risk until its origin and purpose are verified.", "Compare with the package baseline; inspect the binary and owner; remove the SUID bit or isolate the file if unauthorized.", "A SUID executable can let an unprivileged user run code with elevated privileges."),
}


_RDS = {
    "rds.auth.failure": _contract(title="RDS login failed · {{ event.actor.principal or event.actor.source_ip or 'unknown source' }}", what_happened="A database authentication attempt failed.", facts="User: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; reason: {{ event.extra.reason or 'not reported' }}; when: {{ event.event_time }}.", decision="Decide whether this was a user error, an application issue, or unauthorized access.", next_steps="Confirm the user, source, and expected connection; review nearby failures and successes; protect the account if unexplained.", why_it_matters="Repeated or unfamiliar database login failures can precede account takeover or application outage.", evidence="The normalized failure reason and database log signal are shown above.", monitoring_method="RDS database authentication logs and normalized session events.", impact="This attempt did not create a session, but repeated failures may affect access or indicate attack.", recovery="No automatic recovery; a later successful login is separate context and does not close this failure."),
    "rds.auth.burst": _contract(title="RDS authentication burst · {{ event.actor.source_ip or event.actor.principal or 'unknown source' }}", what_happened="Database authentication failures crossed the configured burst threshold.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; user: {{ event.actor.principal or 'not reported' }}; source: {{ event.actor.source_ip or 'not reported' }}; count: {{ event.extra.failure_count or event.extra.count_in_window or 'not reported' }}; window: {{ event.extra.window_minutes or 'not reported' }} minutes.", decision="Treat the burst as suspicious until the source is explained as an approved application or gateway.", next_steps="Identify the source and affected users; check for successful logins in the same window; rate-limit, rotate, or contain according to the database runbook.", why_it_matters="A concentrated burst can be password spraying, a broken application secret, or an active database attack.", evidence="The failure count, detection window, database, and source are the correlation evidence.", monitoring_method="RDS authentication-failure correlation by database and source.", impact="Accounts may be at risk, or a workload may be repeatedly failing to connect.", recovery="No automatic recovery; document containment and the confirmed source or application fix."),
    "rds.session.start": _contract(title="RDS session started · {{ event.actor.principal or event.actor.source_ip or 'unknown user' }}", what_happened="A database session was established.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; database name: {{ event.extra.database or event.extra.db_name or 'not reported' }}; started: {{ event.event_time }}.", decision="Confirm that the user, source, and database are expected for this session.", next_steps="If expected, no action is required; otherwise review the authentication trail, terminate the session, and protect the credential.", why_it_matters="A session represents active database access and should be explainable for sensitive workloads.", evidence="The session-start log and normalized user, source, and database fields are shown above.", monitoring_method="Database connection logs and the RDS active-session projection.", impact="The recorded identity has active access to the database.", recovery="rds.session.end closes this session trail; it does not prove the access was authorized."),
    "rds.session.end": _contract(title="RDS session ended · {{ event.actor.principal or event.actor.source_ip or 'unknown user' }}", what_happened="A database session disconnected.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; session: {{ event.extra.session_id or 'not reported' }}; duration: {{ event.extra.duration_seconds or 'not reported' }} seconds; ended: {{ event.event_time }}.", decision="Decide whether the disconnect was expected or indicates an application, network, or database problem.", next_steps="Compare the end time with deployment and workload activity; check disconnect/error logs; close the trail when the reason is understood.", why_it_matters="Unexpected disconnects can interrupt work or reveal instability even when no security violation is proven.", evidence="The disconnect log, session identifier, and duration are the available evidence.", monitoring_method="Database disconnection logs and the RDS active-session projection.", impact="The session no longer holds active access; dependent work may have been interrupted.", recovery="There is no separate remediation event; manual resolution records the expected disconnect or incident cause."),
    "rds.session.concurrent": _contract(title="Concurrent RDS sessions · {{ event.actor.principal or 'unknown user' }}", what_happened="The same database identity crossed the configured concurrent-session threshold.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or 'not reported' }}; active sessions: {{ event.extra.session_count or 'not reported' }}; threshold: {{ event.extra.threshold or 'not reported' }}.", decision="Decide whether the concurrency matches the workload or indicates credential sharing or a connection leak.", next_steps="List active sessions and sources; compare them with the application pool and owner; terminate or protect unexpected sessions.", why_it_matters="Unexpected concurrency can exhaust database capacity or indicate shared credentials.", evidence="The active-session projection counted the identity's open sessions against the configured threshold.", monitoring_method="RDS active-session projection and concurrency correlation.", impact="Connection capacity and data access may be affected while the sessions remain open.", recovery="No automatic recovery; resolve by normalizing the pool, closing sessions, or documenting approved concurrency."),
    "rds.session.long_idle": _contract(title="Long-idle RDS session · {{ event.actor.principal or event.extra.user or 'unknown user' }}", what_happened="A database session remained idle longer than the configured limit.", facts="User: {{ event.actor.principal or event.extra.user or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; session: {{ event.extra.session_id or 'not reported' }}; idle: {{ event.extra.idle_hours or 'not reported' }} hours; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}.", decision="Decide whether the session is an expected transaction, a leaked connection, or an access risk.", next_steps="Check the owner and transaction state; close the session if safe; fix pool/timeout behavior and review the source if unexpected.", why_it_matters="Long-idle sessions consume capacity and can retain locks or active access longer than intended.", evidence="The staleness detector measured the idle duration from the active-session read model.", monitoring_method="RDS active-session staleness checks.", impact="Capacity or locked resources may remain unavailable, and access persists beyond the expected work window.", recovery="No automatic recovery; closure is confirmed when the session ends or the owner explains the exception."),
    "rds.session.new_source": _contract(title="New RDS session source · {{ event.actor.principal or 'unknown user' }}", what_happened="A known database identity connected from a source not previously associated with it.", facts="User: {{ event.actor.principal or 'not reported' }}; new source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; when: {{ event.event_time }}.", decision="Confirm the new source belongs to an approved device, service, or deployment.", next_steps="Compare the source with network and deployment records; review recent authentication; revoke or investigate if it is not expected.", why_it_matters="A new source can be a legitimate failover or a sign that a credential is being used elsewhere.", evidence="The session projection matched the identity to a source not present in its prior history.", monitoring_method="RDS session-source history and connection projection.", impact="The identity has extended its database access path to a new source.", recovery="No automatic recovery; owner confirmation or credential action resolves the review."),
    "rds.proxy.source.new": _contract(title="New RDS proxy source · {{ event.actor.source_ip or 'unknown source' }}", what_happened="A new client source connected through the database proxy.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; user: {{ event.actor.principal or 'not reported' }}; when: {{ event.event_time }}.", decision="Confirm the source is an approved application, network path, or deployment.", next_steps="Trace the source through the proxy and workload inventory; review the first connection; restrict or investigate if unrecognized.", why_it_matters="The proxy can hide backend details, so a new client path deserves explicit ownership confirmation.", evidence="The proxy connection event recorded the source and target database above.", monitoring_method="RDS Proxy client connection logs and source-history projection.", impact="A new path now reaches the database through the proxy.", recovery="No automatic recovery; owner confirmation or removal of the unapproved source resolves the review."),
    "rds.proxy.client.connect": _contract(title="RDS proxy client connected · {{ event.actor.source_ip or 'unknown source' }}", what_happened="A client connected to the RDS Proxy.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; client port: {{ event.extra.source_port or 'not reported' }}; when: {{ event.event_time }}.", decision="Confirm the client connection is expected for the proxy's workload.", next_steps="Match the source to an application or owner; check the backend session if access is unexpected; review proxy health.", why_it_matters="Proxy connections are an access-path fact and can reveal a new or failing client workload.", evidence="The proxy client-connect log and source fields are shown above.", monitoring_method="RDS Proxy client connection telemetry.", impact="The client can request database access through the proxy.", recovery="rds.proxy.client.disconnect ends this connection trail; it is not a security recovery event."),
    "rds.proxy.client.disconnect": _contract(title="RDS proxy client disconnected · {{ event.actor.source_ip or 'unknown source' }}", what_happened="A client disconnected from the RDS Proxy.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; client port: {{ event.extra.source_port or 'not reported' }}; when: {{ event.event_time }}.", decision="Decide whether the disconnect is normal or part of a connection failure pattern.", next_steps="Compare with application deploys and retry logs; check backend sessions and proxy errors if disconnects are unexpected.", why_it_matters="Unexpected proxy disconnects can cause application errors or repeated reconnect storms.", evidence="The proxy client-disconnect log and source fields are shown above.", monitoring_method="RDS Proxy client connection telemetry.", impact="This client no longer has an active proxy connection; dependent requests may have failed.", recovery="There is no separate remediation event; the application or proxy health signal must explain the disconnect."),
    "rds.proxy.backend_hba_reject": _contract(title="RDS proxy backend rejected a connection", what_happened="The database backend rejected a connection made through the proxy.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; user: {{ event.actor.principal or event.extra.user or 'not reported' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; reason: {{ event.extra.reason or 'host authorization rejected' }}.", decision="Determine whether backend authorization is misconfigured or the source is unauthorized.", next_steps="Check pg_hba/proxy target rules, secret and network identity, and recent configuration changes; correct the approved path and retest.", why_it_matters="A backend rejection can break an application or expose a mismatch between the proxy and database trust controls.", evidence="The backend rejection reason and proxy/database identity are shown above.", monitoring_method="RDS Proxy backend connection logs and database authorization signals.", impact="Requests through the proxy may fail to reach the database.", recovery="Recovery is a successful backend connection after the approved authorization fix; no automatic closure is claimed."),
    "rds.proxy.misconfig": _contract(title="RDS proxy configuration problem", what_happened="The RDS Proxy reported a configuration problem.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; detail: {{ event.extra.message or event.extra.reason or 'not reported' }}.", decision="Decide whether the proxy can safely serve traffic or must be removed from the path while it is corrected.", next_steps="Review proxy target, secret, network, and health configuration; compare the last change; correct and validate a real client connection.", why_it_matters="A proxy configuration error can interrupt database access or route clients to the wrong backend.", evidence="The proxy's reported message and affected database are shown above.", monitoring_method="RDS Proxy health and configuration telemetry.", impact="Proxy-backed applications may fail or have incomplete database connectivity.", recovery="A healthy proxy configuration and successful client/backend test are required for recovery."),
    "rds.query.role": _contract(title="Sensitive RDS role query observed", what_happened="A query associated with a monitored sensitive database role was observed.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; role: {{ event.extra.role or 'not reported' }}; query: {{ event.extra.query or 'not captured' }}.", decision="Confirm the role use and query are approved for this user and change window.", next_steps="Identify the owner and purpose; review the query result and nearby writes; escalate or revoke access if unauthorized.", why_it_matters="Sensitive roles can read or change high-value database objects.", evidence="The role match and normalized query metadata are shown above; raw query text is omitted when unavailable.", monitoring_method="RDS database query rules and role-based detection.", impact="Sensitive data or database controls may have been accessed.", recovery="No automatic recovery; owner approval or incident response closes the review."),
    "rds.query.function": _contract(title="Sensitive RDS function used", what_happened="A monitored sensitive database function was called.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; function: {{ event.extra.function or 'not reported' }}; when: {{ event.event_time }}.", decision="Verify that this function call was required and authorized.", next_steps="Review the caller, parameters if available, result, and change window; restrict or investigate the account if unexpected.", why_it_matters="Sensitive functions may export data, alter permissions, or bypass normal application controls.", evidence="The function match and caller fields are the detection evidence.", monitoring_method="RDS database query rules for sensitive functions.", impact="The caller may have invoked a privileged database operation.", recovery="No automatic recovery; document the approved purpose or handle as a database-access incident."),
    "rds.query.ddl": _contract(title="RDS schema change observed", what_happened="A database DDL statement changed schema or database objects.", facts="User: {{ event.actor.principal or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; object: {{ event.extra.object or 'not reported' }}; statement: {{ event.extra.query or 'not captured' }}.", decision="Confirm the schema change belongs to an approved migration.", next_steps="Compare the statement with the migration; check application compatibility and rollback; revert or contain if unauthorized.", why_it_matters="Schema changes can alter data access, break applications, or remove important controls.", evidence="The DDL match and object/query metadata are shown above.", monitoring_method="RDS database query rules for DDL activity.", impact="Database structure or permissions may have changed for dependent workloads.", recovery="Recovery is the approved rollback or successful migration validation; no automatic closure is assumed."),
    "rds.error": _contract(title="RDS database error", what_happened="A database error was observed in the monitored RDS signal.", facts="Database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; severity: {{ event.extra.severity or event.severity or 'not reported' }}; message: {{ event.extra.message or 'not reported' }}; when: {{ event.event_time }}.", decision="Determine whether this is an isolated application error or a database health condition requiring intervention.", next_steps="Check the error rate and affected workload; correlate with deploys, capacity, locks, and connectivity; follow the RDS runbook if it persists.", why_it_matters="Database errors can become availability or data-integrity problems when they repeat.", evidence="The normalized database error message and severity are shown above.", monitoring_method="RDS engine logs and normalized database-error rules.", impact="Some database operations may have failed or degraded.", recovery="Close only after the error rate returns to normal and dependent workloads are healthy."),
    "rds.instance.create": _contract(title="RDS instance created", what_happened="A new RDS database instance was created.", facts="Instance: {{ event.target.name or event.target.id or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; account: {{ event.source.account or 'not reported' }}; region: {{ event.source.region or 'not reported' }}; when: {{ event.event_time }}.", decision="Confirm the instance, account, region, and owner are approved.", next_steps="Validate network exposure, encryption, backups, monitoring, and owner tags before allowing production data.", why_it_matters="A new database can introduce cost, exposed data paths, or an unmanaged production dependency.", evidence="The CloudTrail RDS create operation and target identity are shown above.", monitoring_method="RDS lifecycle and CloudTrail management events.", impact="A new database resource now exists and may be reachable or billable.", recovery="No automatic recovery; remove only through an approved change after preserving required evidence and data."),
    "rds.instance.delete": _contract(title="RDS instance deletion requested", what_happened="An RDS database instance deletion operation was observed.", facts="Instance: {{ event.target.name or event.target.id or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; account: {{ event.source.account or 'not reported' }}; when: {{ event.event_time }}.", decision="Treat as urgent and confirm the deletion is explicitly approved before it completes.", next_steps="Check the change ticket and final snapshot; stop or cancel the deletion when unauthorized; notify the owner and preserve evidence.", why_it_matters="Deleting an instance can interrupt applications and destroy access to data if recovery options are incomplete.", evidence="The CloudTrail deletion operation, actor, and target are shown above.", monitoring_method="RDS lifecycle and CloudTrail management events.", impact="The database and dependent applications may become unavailable; data recovery depends on snapshots and retention.", recovery="Recovery requires an approved restore or cancellation outcome; never claim data restoration from this alert alone."),
    "rds.instance.modify": _contract(title="RDS instance configuration changed", what_happened="An RDS instance configuration was modified.", facts="Instance: {{ event.target.name or event.target.id or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; change: {{ event.extra.change or event.extra.message or 'not reported' }}; when: {{ event.event_time }}.", decision="Verify each changed setting against the approved maintenance or security change.", next_steps="Review the before/after configuration, maintenance behavior, exposure, encryption, and performance impact; revert unauthorized settings.", why_it_matters="Configuration changes can alter availability, security controls, cost, or data exposure.", evidence="The CloudTrail modify operation and available change detail are shown above.", monitoring_method="RDS lifecycle and CloudTrail configuration events.", impact="Database behavior or security posture may differ from the approved baseline.", recovery="Recovery is a validated rollback or approved configuration state; no automatic rollback is implied."),
    "rds.snapshot.modify": _contract(title="RDS snapshot changed", what_happened="An RDS snapshot configuration or sharing setting changed.", facts="Snapshot: {{ event.target.name or event.target.id or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; change: {{ event.extra.change or event.extra.message or 'not reported' }}; when: {{ event.event_time }}.", decision="Confirm the snapshot sharing, retention, and encryption change is approved.", next_steps="Check who can access the snapshot and whether recovery coverage remains; remove unintended sharing and preserve the approved copy.", why_it_matters="Snapshots can contain sensitive data and are also a key recovery control.", evidence="The snapshot-management operation and available sharing/configuration detail are shown above.", monitoring_method="RDS snapshot and CloudTrail management events.", impact="Recovery data may be exposed, altered, or unavailable to the expected recovery team.", recovery="Recovery is a verified approved snapshot configuration and access review."),
    "rds.parameter_group.modify": _contract(title="RDS parameter group changed", what_happened="An RDS parameter group security or runtime setting changed.", facts="Parameter group: {{ event.target.name or event.target.id or 'not reported' }}; actor: {{ event.actor.principal or 'not reported' }}; setting: {{ event.extra.parameter or event.extra.change or 'not reported' }}; when: {{ event.event_time }}.", decision="Verify the parameter change is approved and does not weaken security or availability controls.", next_steps="Compare the setting with the baseline; determine affected instances and reboot behavior; revert or schedule the approved value.", why_it_matters="Parameter changes can weaken logging/authentication or change database behavior across instances.", evidence="The parameter-group operation and changed setting are shown above.", monitoring_method="RDS parameter-group and CloudTrail configuration events.", impact="One or more databases may run with a changed security or runtime posture.", recovery="Recovery is a verified baseline parameter group and confirmation of affected instance state."),
    "rds.user.unknown": _contract(title="Unknown RDS user observed", what_happened="A database user not present in the configured allowlist was observed.", facts="User: {{ event.actor.principal or event.extra.user or 'not reported' }}; database: {{ event.target.name or event.target.id or event.extra.db_instance or 'unknown' }}; source: {{ event.actor.source_ip or event.extra.source_ip or 'not reported' }}; trigger: {{ event.extra.trigger or 'not reported' }}.", decision="Confirm whether the user is approved, newly provisioned, or unauthorized.", next_steps="Check the owner, provisioning record, grants, and recent login history; disable or restrict the user if it cannot be explained.", why_it_matters="An unknown database identity may have excessive access or indicate stale provisioning and credential misuse.", evidence="The allowlist mismatch and normalized user/source fields are shown above.", monitoring_method="RDS user inventory, session logs, and allowlist rules.", impact="An unverified identity may access database data or controls.", recovery="No automatic recovery; owner approval, grant correction, or account disablement resolves the review."),
}


def _host_contract(key: str, detail: tuple[str, str, str, str, str]) -> dict[str, Any]:
    what, facts, decision, steps, impact = detail
    return _contract(
        title=f"{key.replace('host.', '').replace('.', ' ').title()} · {{{{ event.target.name or event.target.id or 'unknown host' }}}}",
        what_happened=what,
        facts=facts,
        decision=decision,
        next_steps=steps,
        why_it_matters=impact,
        evidence="The normalized host-agent, journal, or change-detection fields shown above are the available evidence.",
        monitoring_method="EC2 host-agent telemetry, SSH/authentication logs, and host change signals.",
        impact=impact,
        recovery="A matching recovery or normal-state event is reported when the producer supports one; otherwise record manual resolution after verification.",
    )


_HOST = {key: _host_contract(key, detail) for key, detail in _HOST_DETAIL.items()}


_API_GATEWAY = {
    "api.auth.failure": _contract(
        title="API authentication failed for {{ event.target.name or event.target.id }}",
        what_happened="API Gateway rejected one request.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.method %}Method: {{ event.extra.method }}\n{% endif %}"
               "{% if event.extra.route_key %}Route: {{ event.extra.route_key }}\n{% endif %}"
               "{% if event.extra.status is defined and event.extra.status is not none %}Status: {{ event.extra.status }}\n{% endif %}"
               "{% if event.extra.reason %}Reason: {{ event.extra.reason }}\n{% endif %}"
               "{% if event.extra.integration_status is defined and event.extra.integration_status is not none %}Integration status: {{ event.extra.integration_status }}\n{% endif %}"
               "{% if event.extra.response_latency_ms is defined and event.extra.response_latency_ms is not none %}Latency: {{ event.extra.response_latency_ms }} ms\n{% endif %}"
               "{% if event.extra.response_length is defined and event.extra.response_length is not none %}Response length: {{ event.extra.response_length }}\n{% endif %}"
               "{% if event.extra.request_id %}Request ID: {{ event.extra.request_id }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Decide whether this request was expected; this event does not identify a user or URL path.",
        next_steps="Verify the source and request context, then investigate repeated failures or protect the affected access path.",
        why_it_matters="A single rejected request may be benign; repeated failures can indicate misuse of an API access path.",
        evidence="The normalized API status and authentication reason are the available evidence.",
        monitoring_method="API Gateway access-log normalization.",
        impact="This request was rejected; broader impact is not inferred from one event.",
        recovery="No automatic recovery is claimed; a later request is separate context and requires manual resolution.",
        preview_extra={"api_name": "payments", "method": "POST", "route_key": "ANY /{proxy+}", "status": 401, "reason": "unauthorized", "request_id": "req-1"},
    ),
    "api.auth.burst": _contract(
        title="API authentication failure burst{{ (' from ' ~ event.actor.source_ip) if event.actor.source_ip else '' }}",
        what_happened="Repeated API authentication failures reached the detector's burst condition.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.failure_count is defined and event.extra.failure_count is not none %}Failures: {{ event.extra.failure_count }}\n{% endif %}"
               "{% if event.extra.window_minutes is defined and event.extra.window_minutes is not none %}Window: {{ event.extra.window_minutes }} minutes\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Treat the aggregate as suspicious until the source and activity are explained.",
        next_steps="Check whether the source is an approved client or gateway, review nearby successes, and contain the source if unauthorized.",
        why_it_matters="A concentrated failure burst can indicate credential stuffing or a noisy client that needs correction.",
        evidence="The producer supplied the failure count and window; no additional identity or path is inferred.",
        monitoring_method="API Gateway authentication-failure correlation by source IP.",
        impact="Multiple requests were rejected from one source; account impact is not established by this aggregate alone.",
        recovery="No automatic recovery exists; resolve manually after source validation and containment or approval.",
        preview_extra={"api_name": "payments", "failure_count": 10, "window_minutes": 5},
    ),
    "api.error": _contract(
        title="API Gateway error on {{ event.target.name or event.target.id }}",
        what_happened="API Gateway returned a server-side error for one request.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.method %}Method: {{ event.extra.method }}\n{% endif %}"
               "{% if event.extra.route_key %}Route: {{ event.extra.route_key }}\n{% endif %}"
               "{% if event.extra.status is defined and event.extra.status is not none %}Status: {{ event.extra.status }}\n{% endif %}"
               "{% if event.extra.integration_status is defined and event.extra.integration_status is not none %}Integration status: {{ event.extra.integration_status }}\n{% endif %}"
               "{% if event.extra.reason %}Reason: {{ event.extra.reason }}\n{% endif %}"
               "{% if event.extra.error_message %}Error: {{ event.extra.error_message }}\n{% endif %}"
               "{% if event.extra.request_id %}Request ID: {{ event.extra.request_id }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Determine whether this is an isolated request failure or a service or integration condition.",
        next_steps="Check the integration and API logs for the request ID, correlate nearby errors, and follow the service runbook if the condition persists.",
        why_it_matters="A server-side API error can affect availability or indicate an unhealthy integration.",
        evidence="The normalized response status, integration status, reason, and error message are the available evidence.",
        monitoring_method="API Gateway access-log normalization and server-error detection.",
        impact="This request failed; wider impact is not inferred from one error.",
        recovery="Recovery requires a subsequent healthy request or service signal when such a detector exists; otherwise resolve manually.",
        preview_extra={"api_name": "payments", "method": "GET", "route_key": "ANY /{proxy+}", "status": 502, "integration_status": 500, "reason": "integration_failure", "error_message": "upstream unavailable", "request_id": "req-2"},
    ),
    "api.error.burst": _contract(
        title="API Gateway error burst{{ (' from ' ~ event.actor.source_ip) if event.actor.source_ip else '' }}",
        what_happened="Repeated API server-side errors reached the detector's burst condition.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.error_count is defined and event.extra.error_count is not none %}Errors: {{ event.extra.error_count }}\n{% endif %}"
               "{% if event.extra.window_minutes is defined and event.extra.window_minutes is not none %}Window: {{ event.extra.window_minutes }} minutes\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Determine whether the aggregate is a client-specific pattern or a broader backend or integration incident.",
        next_steps="Correlate the source, request failures, integrations, and deployment timeline; contain the client or escalate the service incident when supported by evidence.",
        why_it_matters="A burst can indicate a failing backend, targeted probing, or a client repeatedly reaching an error path.",
        evidence="The producer supplied the error count and window; no threshold, path, or impact is inferred beyond those fields.",
        monitoring_method="API Gateway server-error correlation by source IP.",
        impact="Multiple requests returned errors from one source; wider customer impact is not established here.",
        recovery="Recovery requires a subsequent healthy/error-normalization signal when one exists; otherwise resolve manually after correlation.",
        preview_extra={"api_name": "payments", "error_count": 25, "window_minutes": 5},
    ),
    "api.scanner_ua": _contract(
        title="Known API scanner user agent detected",
        what_happened="An API request used a user agent matching a known scanner signature.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.user_agent %}User agent: {{ event.extra.user_agent }}\n{% endif %}"
               "{% if event.extra.scanner_signature %}Scanner signature: {{ event.extra.scanner_signature }}\n{% endif %}"
               "{% if event.extra.method %}Method: {{ event.extra.method }}\n{% endif %}"
               "{% if event.extra.status is defined and event.extra.status is not none %}Status: {{ event.extra.status }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Decide whether the source is an approved scanner or an unapproved client; the signature alone does not prove compromise.",
        next_steps="Validate the source owner and scanner authorization, then review nearby requests and contain the source if unauthorized.",
        why_it_matters="Scanner traffic can expose API weaknesses or create noisy failures, even when the request status is successful.",
        evidence="The normalized user agent and named scanner signature triggered this event.",
        monitoring_method="API Gateway user-agent signature matching.",
        impact="One scanner-like request was observed; exploit or customer impact is not inferred.",
        recovery="There is no automatic recovery; manual resolution is source validation and any required containment.",
        preview_extra={"api_name": "payments", "user_agent": "sqlmap/1.8", "scanner_signature": "sqlmap", "method": "GET", "status": 404},
    ),
    "api.source.new": _contract(
        title="New API source observed",
        what_happened="API Gateway observed a source IP not previously recorded for this API.",
        facts=("{% if event.extra.api_name %}API: {{ event.extra.api_name }}\n{% endif %}"
               "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
               "{% if event.extra.method %}Method: {{ event.extra.method }}\n{% endif %}"
               "{% if event.extra.status is defined and event.extra.status is not none %}Status: {{ event.extra.status }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Confirm whether this source belongs to an approved client, gateway, or integration.",
        next_steps="Identify the source owner, compare the request with expected API traffic, and add or restrict the source through the approved change process.",
        why_it_matters="A new source may be legitimate onboarding or an unrecognized path into the API.",
        evidence="The source projection recorded the first observed source IP for this API.",
        monitoring_method="API Gateway source-IP projection from normalized requests.",
        impact="A previously unseen source reached the API; authorization and customer impact are not established here.",
        recovery="No recovery event exists for first-seen source discovery; manual resolution is owner validation and an approved allow or block decision.",
        preview_extra={
            "api_name": "payments",
            "source_ip": "198.51.100.20",
            "tags": {"env": "prod", "api": "payments"},
            "message": "payments: new source IP 198.51.100.20 touched the API Gateway — never seen before",
        },
        preview_sample={
            "target_id": "payments",
            "target_name": "payments",
            "source_ip": "198.51.100.20",
            "message": "payments: new source IP 198.51.100.20 touched the API Gateway — never seen before",
            "extra": {},
        },
    ),
}


_AWS_POSTURE = {
    "network.sg.instance_attach": _contract(
        title="Security group attached to {{ event.extra.instance_id or event.target.name or event.target.id }}",
        what_happened="A security group attachment changed for an instance.",
        facts=("{% if event.extra.instance_id %}Instance: {{ event.extra.instance_id }}\n{% endif %}"
               "{% if event.extra.sg_ids %}Security groups: {{ event.extra.sg_ids | join(', ') }}\n{% endif %}"
               "{% if event.target.id %}Target: {{ event.target.id }}\n{% endif %}"
               "{% if event.actor.principal %}Actor: {{ event.actor.principal }}\n{% endif %}"
               "{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}"
               "{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Confirm whether this instance-to-security-group change was approved and matches the intended access boundary.",
        next_steps="Verify the instance, attached security groups, actor, and change window; reverse the attachment through the approved AWS change process if it is not authorized.",
        why_it_matters="A security-group attachment changes which network rules apply to an instance; this event alone does not establish exposure or impact.",
        evidence="The CloudTrail producer supplied the instance target and named security-group identifiers shown above.",
        monitoring_method="AWS CloudTrail EC2 instance-attribute events.",
        impact="The applicable network policy changed for the recorded instance; broader impact is not inferred.",
        recovery="No automatic recovery event is claimed; manual resolution is owner confirmation and an approved reversal when required.",
        preview_extra={"instance_id": "i-0123", "sg_ids": ["sg-0abc", "sg-0def"]},
    ),
    "aws.posture.finding.new": _contract(
        title="New AWS posture finding · {{ event.extra.finding_id or event.target.id }}",
        what_happened="The posture projection recorded a finding that is active for the first time or after a prior resolution.",
        facts=("{% if event.extra.finding_id %}Finding ID: {{ event.extra.finding_id }}\n{% endif %}"
               "{% if event.extra.resource_id %}Resource: {{ event.extra.resource_id }}{% if event.extra.resource_type %} ({{ event.extra.resource_type }}){% endif %}\n{% endif %}"
               "{% if event.extra.finding_type %}Control/finding: {{ event.extra.finding_type }}\n{% endif %}"
               "{% if event.extra.severity %}Severity: {{ event.extra.severity }}\n{% endif %}"
               "{% if event.extra.account %}Account: {{ event.extra.account }}\n{% endif %}"
               "{% if event.extra.region %}Region: {{ event.extra.region }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Determine whether the finding is an unauthorized posture condition, an approved exception, or a false positive.",
        next_steps="Verify the resource and control evidence, identify the owner, preserve the finding ID, and remediate or document the approved exception.",
        why_it_matters="A posture finding indicates a preventive control or exposure condition that remains traceable until resolved.",
        evidence="{% if event.extra.evidence is defined and event.extra.evidence %}The producer supplied this evidence: {{ event.extra.evidence }}{% endif %}",
        monitoring_method="AWS posture scan findings and the posture lifecycle projection.",
        impact="The recorded control condition may leave the resource exposed or outside the intended posture; broader impact is not inferred.",
        recovery="Pair a later aws.posture.finding.resolved event by finding ID; manual resolution is remediation or an owner-approved exception.",
        preview_extra={"finding_id": "finding-1", "resource_id": "sg-0abc", "resource_type": "sg", "finding_type": "public_ingress_risky_port", "severity": "critical", "account": "111122223333", "region": "us-west-1", "evidence": {"ports": [22], "cidrs": ["0.0.0.0/0"]}},
    ),
    "aws.posture.finding.resolved": _contract(
        title="AWS posture finding resolved · {{ event.extra.finding_id or event.target.id }}",
        what_happened="The posture projection no longer observed this finding in a completed scan and marked it resolved.",
        facts=("{% if event.extra.finding_id %}Finding ID: {{ event.extra.finding_id }}\n{% endif %}"
               "{% if event.extra.resource_id %}Resource: {{ event.extra.resource_id }}{% if event.extra.resource_type %} ({{ event.extra.resource_type }}){% endif %}\n{% endif %}"
               "{% if event.extra.finding_type %}Control/finding: {{ event.extra.finding_type }}\n{% endif %}"
               "{% if event.extra.account %}Account: {{ event.extra.account }}\n{% endif %}"
               "{% if event.extra.region %}Region: {{ event.extra.region }}\n{% endif %}"
               "Resolved at: {{ event.event_time }}"),
        decision="Confirm that the finding ID was resolved by the expected posture change or approved exception; do not treat this as a security-group attachment recovery.",
        next_steps="Review the resolution evidence and scan context, then close the finding trail only after the owner confirms the condition is understood.",
        why_it_matters="Resolution restores the finding lifecycle state, but it does not by itself prove why the condition changed or that related network changes were approved.",
        evidence="{% if event.extra.evidence is defined and event.extra.evidence %}The retained finding evidence was: {{ event.extra.evidence }}{% endif %}",
        monitoring_method="Completed AWS posture scans and finding-ID reconciliation.",
        impact="The finding is no longer open in the completed scan; impact from the prior condition is not inferred.",
        recovery="This is the recovery event for the matching new finding ID. Manual resolution is owner confirmation and closure of the finding trail; security-group attachment events remain separate.",
        preview_extra={"finding_id": "finding-1", "resource_id": "sg-0abc", "resource_type": "sg", "finding_type": "public_ingress_risky_port", "account": "111122223333", "region": "us-west-1", "evidence": {"ports": [22], "cidrs": ["0.0.0.0/0"]}},
    ),
}


_FINDINGS = {
    "finding.malware.detected": _contract(
        title="Malware detected{% if event.extra.signature %} · {{ event.extra.signature }}{% endif %}{% if event.target.name or event.target.id %} · {{ event.target.name or event.target.id }}{% endif %}",
        what_happened="A detector reported a malware signature or malicious detection on the affected resource.",
        facts=("{% if event.extra.signature %}Signature: {{ event.extra.signature }}\n{% endif %}"
               "{% if event.extra.detection %}Detection: {{ event.extra.detection }}\n{% endif %}"
               "{% if event.extra.resource or event.target.id or event.target.name %}Resource: {{ event.extra.resource or event.target.id or event.target.name }}\n{% endif %}"
               "{% if event.extra.object_path %}Object/path: {{ event.extra.object_path }}\n{% endif %}"
               "{% if event.extra.file_hash %}Hash: {{ event.extra.file_hash }}\n{% endif %}"
               "{% if event.extra.scan_time %}Scan time: {{ event.extra.scan_time }}\n{% endif %}"
               "{% if event.extra.engine %}Engine: {{ event.extra.engine }}\n{% endif %}"
               "{% if event.extra.confidence %}Confidence: {{ event.extra.confidence }}\n{% endif %}"
               "{% if event.extra.containment_state %}Containment: {{ event.extra.containment_state }}\n{% endif %}"
               "{% if event.extra.owner %}Owner: {{ event.extra.owner }}\n{% endif %}"
               "{% if event.source.vendor %}Vendor: {{ event.source.vendor }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Contain the affected resource before opening or distributing it, then confirm whether the detection is malicious or a documented false positive.",
        next_steps="1. Isolate or quarantine the affected object, host, or workload using the approved response process.\n2. Preserve the signature, hash, source payload, and scan evidence.\n3. Notify the owner and security responder; do not delete evidence before review.\n4. Re-scan after containment and document the disposition.",
        why_it_matters="A malware detection may expose users or systems to execution, credential theft, or data loss; the exact impact depends on the evidence provided.",
        evidence="{% if event.extra.evidence is defined and event.extra.evidence %}{{ event.extra.evidence }}{% endif %}",
        monitoring_method="Configured malware scanner, finding detector, or security webhook.",
        impact="Potential compromise of the affected resource; no broader scope is inferred without supporting evidence.",
        recovery="No automatic recovery is claimed. Resolve manually after containment, investigation, disposition, and a validating re-scan; use a resolved action only when the producer supplies one.",
        preview_extra={"signature": "Win.Trojan.Foo", "detection": "Eicar-Test-Signature", "resource": "s3://uploads/invoice.xlsx", "object_path": "uploads/invoice.xlsx", "file_hash": "sha256:abc123", "scan_time": "2026-08-29T09:59:00Z", "engine": "ClamAV 1.4", "confidence": "high", "containment_state": "not_contained", "owner": "finance-platform", "evidence": {"rule": "malware-signature"}},
    ),
    "<finding>.detected": _contract(
        title="Security finding detected{% if event.extra.finding_type %} · {{ event.extra.finding_type }}{% endif %}{% if event.target.name or event.target.id %} · {{ event.target.name or event.target.id }}{% endif %}",
        what_happened="A security finding or webhook reported a detected condition on the affected resource.",
        facts=("{% if event.extra.finding_type %}Finding type: {{ event.extra.finding_type }}\n{% endif %}"
               "{% if event.extra.finding_id %}Finding ID: {{ event.extra.finding_id }}\n{% endif %}"
               "{% if event.extra.resource or event.target.id or event.target.name %}Resource: {{ event.extra.resource or event.target.id or event.target.name }}\n{% endif %}"
               "{% if event.source.vendor %}Vendor: {{ event.source.vendor }}\n{% endif %}"
               "{% if event.extra.owner %}Owner: {{ event.extra.owner }}\n{% endif %}"
               "When: {{ event.event_time }}"),
        decision="Determine whether the finding is actionable, expected, or a false positive using the supplied evidence; do not apply malware-specific assumptions to other finding types.",
        next_steps="1. Review the finding type, affected resource, owner, and supplied evidence.\n2. Preserve the source payload and finding identifier.\n3. Apply the relevant runbook for this finding type or assign it to the owner.\n4. Record the disposition and validation result.",
        why_it_matters="A security finding identifies a potentially unsafe condition, but its impact depends on the finding type and evidence.",
        evidence="{% if event.extra.evidence is defined and event.extra.evidence %}{{ event.extra.evidence }}{% endif %}",
        monitoring_method="Configured security-finding detector or webhook source.",
        impact="Impact is determined by the finding type, affected resource, and evidence supplied by the producer.",
        recovery="No automatic recovery is claimed. Resolve manually unless the producer supplies a matching resolved action; retain arbitrary source evidence through the investigation.",
        preview_extra={"finding_type": "suspicious.login", "finding_id": "CASE-42", "resource": "production-account", "owner": "security-team", "evidence": {"source": "provider", "confidence": "medium"}},
    ),
}


_UEBA_DYNAMIC = _contract(
    title="New {{ ((event.extra.dimension or 'behavior') | replace('_', ' ') | title) | replace('Ip', 'IP') }} observed · {{ event.actor.principal or event.target.name or event.target.id or 'unidentified entity' }}",
    what_happened="The UEBA baseline observed a value that had not previously been associated with this principal after the warm-up period.",
    facts=("{% if event.actor.principal %}Principal: {{ event.actor.principal }}\n{% endif %}"
           "{% if event.actor.type %}Principal type: {{ event.actor.type }}\n{% endif %}"
           "{% if event.extra.dimension %}Dimension: {{ event.extra.dimension }}\n{% endif %}"
           "{% if event.extra.baseline_value is defined and event.extra.baseline_value is not none %}Value: {{ event.extra.baseline_value }}\n{% endif %}"
           "{% if event.actor.source_ip %}Source IP: {{ event.actor.source_ip }}\n{% endif %}"
           "{% if event.extra.source_country %}Source country: {{ event.extra.source_country }}\n{% endif %}"
           "{% if event.extra.source_asn %}Source ASN: {{ event.extra.source_asn }}\n{% endif %}"
           "{% if event.extra.user_agent_family %}User-agent family: {{ event.extra.user_agent_family }}\n{% endif %}"
           "{% if event.extra.hour_of_day is defined and event.extra.hour_of_day is not none %}UTC hour: {{ event.extra.hour_of_day }}\n{% endif %}"
           "When: {{ event.event_time }}"),
    decision="Do not treat a first-seen value as proof of compromise. Confirm whether the principal and this behavior are expected.",
    next_steps="1. Review the principal's recent access and the trigger event.\n2. Compare the new value with approved devices, locations, automation, and change records.\n3. If unexplained, validate the account, preserve evidence, and follow the credential or access-response runbook.",
    why_it_matters="A new value may be a legitimate workflow change, but it can also indicate credential misuse or an unreviewed access path.",
    evidence="{% if event.extra.trigger_action %}Trigger action: {{ event.extra.trigger_action }}\n{% endif %}{% if event.extra.trigger_event_id %}Trigger event ID: {{ event.extra.trigger_event_id }}\n{% endif %}",
    monitoring_method="UEBA per-principal behavioral baselines after the configured warm-up period.",
    impact="The event identifies an unusual behavior dimension; account compromise or business impact is not inferred from first-seen activity alone.",
    recovery="There is no automatic recovery event. Resolve manually after owner validation, baseline normalization, or credential action when required.",
    preview_extra={
        "dimension": "source_ip", "baseline_value": "203.0.113.7",
        "principal_id": "alice", "principal_type": "user",
        "trigger_action": "iam.role.assume", "trigger_event_id": "evt-ueba-1",
        "source_country": "IN", "source_asn": "AS64500", "user_agent_family": "aws-cli",
        "hour_of_day": 10,
    },
)


_AWS_COMPUTE = {
    "compute.imds.modify": _contract(
        title="EC2 metadata protection changed{{ (' · ' ~ (event.extra.instance_id or event.target.id)) if (event.extra.instance_id or event.target.id) else '' }}",
        what_happened="The instance metadata service configuration changed.",
        facts="{% if event.extra.instance_id %}Instance: {{ event.extra.instance_id }}\n{% endif %}{% if event.extra.http_tokens %}IMDS tokens: {{ event.extra.http_tokens }}\n{% endif %}{% if event.extra.http_endpoint %}IMDS endpoint: {{ event.extra.http_endpoint }}\n{% endif %}{% if event.extra.http_put_response_hop_limit is defined and event.extra.http_put_response_hop_limit is not none %}Hop limit: {{ event.extra.http_put_response_hop_limit }}\n{% endif %}{% if event.extra.imdsv1_enabled %}IMDSv1: enabled\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the metadata setting matches the approved instance-hardening baseline; treat IMDSv1 availability as a credential-theft risk until explained.",
        next_steps="Verify the instance owner and change ticket; require IMDSv2 where approved; review recent instance-role use and investigate unexpected metadata access.",
        why_it_matters="Metadata settings control whether workloads can reach instance credentials and other metadata.",
        evidence="CloudTrail supplied the instance and metadata-option values shown above; no credential access is inferred.",
        monitoring_method="AWS CloudTrail EC2 ModifyInstanceMetadataOptions events.",
        impact="The instance credential-access boundary changed; compromise or impact is not established by this event alone.",
        recovery="No automatic recovery is claimed; manual resolution requires the approved metadata baseline and review of recent role-credential activity.",
        preview_extra={"instance_id": "i-0123", "http_tokens": "optional", "http_endpoint": "enabled", "http_put_response_hop_limit": 1, "imdsv1_enabled": True},
    ),
    "compute.ami.modify": _contract(
        title="AMI exposure changed{{ (' · ' ~ (event.extra.image_id or event.target.id)) if (event.extra.image_id or event.target.id) else '' }}",
        what_happened="An EC2 image launch-permission or visibility setting changed.",
        facts="{% if event.extra.image_id %}AMI: {{ event.extra.image_id }}\n{% endif %}{% if event.extra.ami_public %}Public visibility: enabled\n{% endif %}{% if event.extra.ami_shared_accounts %}Shared accounts: {{ event.extra.ami_shared_accounts | join(', ') }}\n{% endif %}{% if event.extra.ami_removed_accounts %}Access removed for accounts: {{ event.extra.ami_removed_accounts | join(', ') }}\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the image exposure is intentional and that the image contains no credentials or sensitive data; public sharing is high risk until proven approved.",
        next_steps="Review the image contents and owner; compare the permission change with the release ticket; remove unintended public or cross-account access and rotate exposed credentials.",
        why_it_matters="AMI permissions can expose machine images, embedded secrets, and trusted software to unintended accounts.",
        evidence="CloudTrail supplied the image identifier and launch-permission change shown above; image contents are not inspected by this alert.",
        monitoring_method="AWS CloudTrail EC2 ModifyImageAttribute events.",
        impact="The image's distribution boundary changed; exposure depends on the resulting permissions and image contents.",
        recovery="No automatic recovery is claimed; manual resolution requires a verified approved permission set and credential review when exposure occurred.",
        preview_extra={"image_id": "ami-0123", "ami_public": True, "ami_shared_accounts": ["222222222222"]},
    ),
    "compute.instance.modify": _contract(
        title="EC2 instance configuration changed{{ (' · ' ~ (event.extra.instance_id or event.target.id)) if (event.extra.instance_id or event.target.id) else '' }}",
        what_happened="An EC2 instance attribute changed.",
        facts="{% if event.extra.instance_id %}Instance: {{ event.extra.instance_id }}\n{% endif %}{% if event.extra.instance_type %}Instance type: {{ event.extra.instance_type }}\n{% endif %}{% if event.extra.source_dest_check is defined and event.extra.source_dest_check is not none %}Source/destination check: {{ event.extra.source_dest_check }}\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the changed instance attribute is approved and does not alter routing, workload capacity, or host security unexpectedly.",
        next_steps="Review the before/after attribute and owner; validate application health and network behavior; revert through the approved change process if unauthorized.",
        why_it_matters="Instance attributes can change workload capacity or network behavior even when no security finding is raised.",
        evidence="CloudTrail supplied the instance attribute values shown above; unavailable before/after values are intentionally omitted.",
        monitoring_method="AWS CloudTrail EC2 ModifyInstanceAttribute events.",
        impact="The instance configuration differs from its prior state; operational impact depends on the changed attribute.",
        recovery="No automatic rollback is claimed; manual resolution is a verified approved configuration or a follow-up corrective change.",
        preview_extra={"instance_id": "i-0123", "instance_type": "m7g.large", "source_dest_check": False},
    ),
}


_AWS_BACKUP = {
    "backup.vault.create": _contract(
        title="Backup vault created{% if event.target.name or event.target.id %} · {{ event.target.name or event.target.id }}{% endif %}",
        what_happened="A new AWS Backup vault was created.",
        facts="{% if event.target.name or event.target.id %}Vault: {{ event.target.name or event.target.id }}\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the vault is expected, owned, and governed by the approved retention and access policy.",
        next_steps="Verify the owner, encryption, retention, immutability, logging, and cross-account access; record the intended backup scope.",
        why_it_matters="An unmanaged vault can create retention, access, or recovery gaps.",
        evidence="The CloudTrail vault-creation event and normalized account, region, and actor fields are shown above.",
        monitoring_method="AWS CloudTrail Backup API events.",
        impact="The account now has a backup destination whose controls and ownership require confirmation.",
        recovery="No automatic recovery; document the approved vault or remove it through the controlled AWS change process.",
        preview_extra={"vault_name": "critical", "account": "111111111111", "region": "us-east-1"},
    ),
    "backup.recovery_point.delete": _contract(
        title="Backup recovery point deleted{% if event.extra.recovery_point_arn %} · {{ event.extra.recovery_point_arn.split(':')[-1] }}{% endif %}",
        what_happened="An AWS Backup recovery point was deleted.",
        facts=("{% if event.extra.recovery_point_arn %}Recovery point: {{ event.extra.recovery_point_arn }}\n{% endif %}"
               "{% if event.extra.resource_arn %}Protected resource: {{ event.extra.resource_arn }}\n{% endif %}"
               "{% if event.extra.vault_name %}Vault: {{ event.extra.vault_name }}\n{% endif %}"
               "{% if event.extra.plan_name %}Backup plan: {{ event.extra.plan_name }}\n{% endif %}"
               "{% if event.extra.recovery_point_time %}Recovery point time: {{ event.extra.recovery_point_time }}\n{% endif %}"
               "{% if event.extra.retention_days is defined and event.extra.retention_days is not none %}Retention at deletion: {{ event.extra.retention_days }} days\n{% endif %}"
               "Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}"),
        decision="Treat the deletion as destructive; do not assume recovery until the owner confirms it was approved and coverage remains sufficient.",
        next_steps="1. Verify the last known-good recovery point still exists and is restorable.\n2. Check the vault retention policy, immutability controls, and backup plan.\n3. Confirm the resource owner and approved change or incident.\n4. Restore or create replacement protection if coverage was reduced.",
        why_it_matters="Deleting a recovery point can remove the ability to restore a protected resource.",
        evidence="The CloudTrail event records the deleted recovery point and the protected resource when supplied.",
        monitoring_method="AWS CloudTrail normalization for AWS Backup recovery-point actions.",
        impact="Recovery coverage may be reduced; no data loss beyond the deleted recovery point is inferred.",
        recovery="There is no automatic recovery. Close manually only after a later verified backup or operator restoration confirms coverage.",
        preview_extra={"recovery_point_arn": "arn:aws:backup:us-east-1:111111111111:recovery-point:rp-42", "resource_arn": "arn:aws:rds:us-east-1:111111111111:db:prod", "vault_name": "critical", "plan_name": "nightly-prod", "recovery_point_time": "2026-08-28T03:00:00Z", "retention_days": 35},
    ),
    "backup.vault.delete": _contract(
        title="Backup vault deleted{% if event.extra.vault_name %} · {{ event.extra.vault_name }}{% endif %}",
        what_happened="An AWS Backup vault was deleted.",
        facts=("{% if event.extra.vault_name %}Vault: {{ event.extra.vault_name }}\n{% endif %}{% if event.extra.vault_arn %}Vault ARN: {{ event.extra.vault_arn }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}"),
        decision="Escalate as a destructive backup-control change until retention and alternate recovery coverage are verified.",
        next_steps="1. Verify the last known-good recovery point and its restore location.\n2. Check retention, immutability, and alternate vault or account copies.\n3. Confirm the owner and approved change.\n4. Recreate protected coverage if the deletion was unauthorized.",
        why_it_matters="A deleted vault can remove multiple recovery points and weaken disaster recovery.",
        evidence="The CloudTrail event records the vault deletion; coverage impact must be confirmed from AWS Backup inventory.",
        monitoring_method="AWS CloudTrail normalization for AWS Backup vault actions.",
        impact="Multiple recovery points may be unavailable; the full scope is not inferred from this event alone.",
        recovery="There is no automatic recovery. Close manually after the vault or equivalent recovery coverage is restored and verified.",
        preview_extra={"vault_name": "critical", "vault_arn": "arn:aws:backup:us-east-1:111111111111:backup-vault:critical", "region": "us-east-1"},
    ),
    "backup.vault.policy.delete": _contract(
        title="Backup vault access policy deleted{% if event.extra.vault_name %} · {{ event.extra.vault_name }}{% endif %}",
        what_happened="An AWS Backup vault access policy was deleted.",
        facts=("{% if event.extra.vault_name %}Vault: {{ event.extra.vault_name }}\n{% endif %}{% if event.extra.vault_arn %}Vault ARN: {{ event.extra.vault_arn }}\n{% endif %}{% if event.extra.policy_summary %}Policy summary: {{ event.extra.policy_summary }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}"),
        decision="Determine whether cross-account backup access was intentionally removed and whether copies or restores depend on it.",
        next_steps="1. Compare the current vault policy with the approved baseline.\n2. Verify the last known-good recovery point and retention policy.\n3. Check copy jobs, delegated backup accounts, and restore permissions.\n4. Restore the approved policy if the change was unauthorized.",
        why_it_matters="Removing a vault policy can interrupt cross-account backup copies or restore operations.",
        evidence="The CloudTrail event identifies the policy deletion; the prior policy document may require a separate audit lookup.",
        monitoring_method="AWS CloudTrail normalization for AWS Backup vault policy actions.",
        impact="Backup copy or restore access may be reduced; availability is not inferred without policy comparison.",
        recovery="There is no automatic recovery. Close manually after the intended policy and a permitted backup/restore check are verified.",
        preview_extra={"vault_name": "critical", "vault_arn": "arn:aws:backup:us-east-1:111111111111:backup-vault:critical", "policy_summary": "Cross-account copy access"},
    ),
    "backup.vault.policy.put": _contract(
        title="Backup vault access policy changed{% if event.extra.vault_name %} · {{ event.extra.vault_name }}{% endif %}",
        what_happened="An AWS Backup vault access policy was added or replaced.",
        facts=("{% if event.extra.vault_name %}Vault: {{ event.extra.vault_name }}\n{% endif %}{% if event.extra.vault_arn %}Vault ARN: {{ event.extra.vault_arn }}\n{% endif %}{% if event.extra.policy_summary %}Policy summary: {{ event.extra.policy_summary }}\n{% endif %}{% if event.extra.backup_vault_policy_wildcard %}Wildcard principal: yes\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}"),
        decision="Approve only if the principals, conditions, and cross-account purpose match the backup design; otherwise remove or restrict the policy.",
        next_steps="1. Review every principal, action, resource, and condition in the new policy.\n2. Verify the last known-good recovery point and retention policy.\n3. Test intended copy and restore paths without granting unnecessary access.\n4. Revert or narrow wildcard access if it is not explicitly approved.",
        why_it_matters="A vault policy controls who can copy, delete, or restore backup data.",
        evidence="The CloudTrail event records the policy change; a wildcard principal is highlighted when detected by normalization.",
        monitoring_method="AWS CloudTrail normalization and backup vault policy signal checks.",
        impact="Backup data may become overexposed or inaccessible to intended accounts depending on the policy change.",
        recovery="There is no automatic recovery. Close manually after the approved policy is present and backup/restore access is verified.",
        preview_extra={"vault_name": "critical", "vault_arn": "arn:aws:backup:us-east-1:111111111111:backup-vault:critical", "policy_summary": "Cross-account copy access", "backup_vault_policy_wildcard": True},
    ),
    "backup.copy_job.start": _contract(
        title="Backup copy job started{% if event.extra.destination_account %} · account {{ event.extra.destination_account }}{% endif %}",
        what_happened="An AWS Backup copy job started.",
        facts=("{% if event.extra.job_id %}Job ID: {{ event.extra.job_id }}\n{% endif %}{% if event.extra.source_vault_arn %}Source vault: {{ event.extra.source_vault_arn }}\n{% endif %}{% if event.extra.destination_vault_arn %}Destination vault: {{ event.extra.destination_vault_arn }}\n{% endif %}{% if event.extra.destination_account %}Destination account: {{ event.extra.destination_account }}\n{% endif %}{% if event.extra.destination_region %}Destination region: {{ event.extra.destination_region }}\n{% endif %}{% if event.extra.backup_copy_dest_account %}Cross-account copy: yes\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}"),
        decision="Confirm the destination, account, region, and retention meet the approved recovery design; investigate unexpected cross-account copies.",
        next_steps="1. Verify the source recovery point and destination vault.\n2. Confirm destination-account ownership, retention, encryption, and immutability.\n3. Check the copy job reaches a completed state and is restorable.\n4. Escalate or stop unauthorized cross-account activity according to the runbook.",
        why_it_matters="A copy job can improve resilience, but an unexpected destination can expose or misplace backup data.",
        evidence="The CloudTrail event records the copy-job request and destination fields when supplied.",
        monitoring_method="AWS CloudTrail normalization for AWS Backup copy-job actions.",
        impact="Recovery coverage may increase or backup data may cross a trust boundary; completion is not assumed.",
        recovery="This is not a recovery event. Close manually after the copy completes and the destination recovery point is verified.",
        preview_extra={"job_id": "copy-42", "source_vault_arn": "arn:aws:backup:us-east-1:111111111111:backup-vault:critical", "destination_vault_arn": "arn:aws:backup:us-west-2:222222222222:backup-vault:dr", "destination_account": "222222222222", "destination_region": "us-west-2", "backup_copy_dest_account": "222222222222"},
    ),
}

_AWS_EFS = {
    "efs.filesystem.create": _contract(
        title="EFS file system created{% if event.extra.efs_filesystem_id or event.target.name or event.target.id %} · {{ event.extra.efs_filesystem_id or event.target.name or event.target.id }}{% endif %}",
        what_happened="A new EFS file system was created.",
        facts="{% if event.extra.efs_filesystem_id or event.target.name or event.target.id %}File system: {{ event.extra.efs_filesystem_id or event.target.name or event.target.id }}\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the file system is expected, owned, encrypted, and reachable only through approved network paths.",
        next_steps="Verify encryption, lifecycle, backup, mount-target security groups, owner, and dependent workload; record the approved purpose.",
        why_it_matters="An unmanaged shared file system can expose data or create an untracked dependency.",
        evidence="The CloudTrail creation event and normalized resource, account, region, and actor fields are shown above.",
        monitoring_method="AWS CloudTrail EFS API events.",
        impact="A new shared storage resource is available until its controls and ownership are confirmed.",
        recovery="No automatic recovery; document the approved system or remove it through the controlled AWS change process.",
        preview_extra={"efs_filesystem_id": "fs-0123"},
    ),
    "efs.filesystem.policy.put": _contract(
        title="EFS policy changed",
        what_happened="An EFS file-system policy was changed.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}{% if event.extra.efs_policy_summary %}Policy: {{ event.extra.efs_policy_summary }}\n{% endif %}{% if event.extra.efs_policy_wildcard %}Wildcard principal: yes\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the policy is approved and grants only the intended principals; treat a wildcard principal as an urgent review.",
        next_steps="1. Compare the policy with the approved access design.\n2. Remove unintended principals or conditions.\n3. Test application access and document the change.",
        why_it_matters="An EFS policy controls who can access shared file data.",
        evidence="The CloudTrail policy-change request and policy fields are shown when supplied.",
        monitoring_method="AWS CloudTrail normalization for EFS policy actions.",
        impact="Shared data may become exposed or inaccessible to intended workloads.",
        recovery="Restore the last approved policy deliberately; this event is not itself a recovery confirmation.",
        preview_extra={"efs_filesystem_id": "fs-0123", "efs_policy_summary": "Allow application role", "efs_policy_wildcard": True},
    ),
    "efs.filesystem.policy.delete": _contract(
        title="EFS policy deleted",
        what_happened="The policy attached to an EFS file system was deleted.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm whether policy removal was approved and whether the resulting access behavior is safe.",
        next_steps="1. Check the change ticket and current access behavior.\n2. Restore the approved policy if removal was unauthorized.\n3. Validate dependent workloads and record the owner decision.",
        why_it_matters="Removing a file-system policy can change who may access shared data.",
        evidence="CloudTrail recorded an EFS policy deletion.", monitoring_method="AWS CloudTrail EFS policy events.",
        impact="Access may broaden, narrow, or fail for dependent workloads.",
        recovery="Recovery requires deliberate restoration of the approved EFS policy; do not mark recovered from a later mount event.",
        preview_extra={"efs_filesystem_id": "fs-0123"},
    ),
    "efs.mount_target.create": _contract(
        title="EFS mount target created",
        what_happened="A new network mount target was created for an EFS file system.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}{% if event.extra.efs_mount_target_id %}Mount target: {{ event.extra.efs_mount_target_id }}\n{% endif %}{% if event.extra.efs_subnet_id %}Subnet: {{ event.extra.efs_subnet_id }}\n{% endif %}{% if event.extra.efs_availability_zone %}Availability zone: {{ event.extra.efs_availability_zone }}\n{% endif %}{% if event.extra.efs_ip_address %}IP address: {{ event.extra.efs_ip_address }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the subnet, availability zone, and security boundaries are part of the approved design.",
        next_steps="1. Verify the subnet and NFS security groups.\n2. Confirm only intended workloads can reach port 2049.\n3. Check the mount target becomes healthy and is used as expected.",
        why_it_matters="A mount target creates a new network path to shared file data.", evidence="CloudTrail recorded the mount-target creation and available placement fields.", monitoring_method="AWS CloudTrail EFS mount-target events.", impact="Data may become reachable from an unintended network segment.", recovery="Remove the mount target deliberately if unauthorized; creation alone is not a recovery event.", preview_extra={"efs_filesystem_id": "fs-0123", "efs_mount_target_id": "fsmt-1", "efs_subnet_id": "subnet-1", "efs_availability_zone": "us-east-1a", "efs_ip_address": "10.0.2.15"},
    ),
    "efs.mount_target.delete": _contract(
        title="EFS mount target deleted",
        what_happened="An EFS mount target was deleted.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}{% if event.extra.efs_mount_target_id %}Mount target: {{ event.extra.efs_mount_target_id }}\n{% endif %}{% if event.extra.efs_availability_zone %}Availability zone: {{ event.extra.efs_availability_zone }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the deletion was approved and identify workloads that depended on this mount path.", next_steps="1. Check application mount errors and affected subnets.\n2. Recreate the mount target in the approved subnet if needed.\n3. Validate application recovery and connectivity.", why_it_matters="Deleting a mount target can interrupt workloads even when the file system still exists.", evidence="CloudTrail recorded an EFS mount-target deletion.", monitoring_method="AWS CloudTrail EFS mount-target events.", impact="Dependent workloads may lose access to shared files.", recovery="Recovery requires deliberate recreation and health validation of the mount target; no automatic recovery is assumed.", preview_extra={"efs_filesystem_id": "fs-0123", "efs_mount_target_id": "fsmt-1", "efs_availability_zone": "us-east-1a"},
    ),
    "efs.mount_target.sg.modify": _contract(
        title="EFS mount security groups changed",
        what_happened="The security groups applied to an EFS mount target changed.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}{% if event.extra.efs_mount_target_id %}Mount target: {{ event.extra.efs_mount_target_id }}\n{% endif %}{% if event.extra.efs_security_groups %}Security groups: {{ event.extra.efs_security_groups | join(', ') }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Confirm the security groups permit only intended NFS clients and do not expose port 2049 broadly.", next_steps="1. Review inbound and outbound rules for each listed group.\n2. Test intended mounts and reject public or unintended sources.\n3. Record the approved group set.", why_it_matters="Mount-target security groups define who can reach shared file data over NFS.", evidence="CloudTrail recorded the security-group replacement and listed groups when supplied.", monitoring_method="AWS CloudTrail EFS security-group modification events.", impact="Workloads may lose access or shared data may become reachable by unintended clients.", recovery="Restore the approved security-group set deliberately and validate mounts; a later access event is not recovery confirmation.", preview_extra={"efs_filesystem_id": "fs-0123", "efs_mount_target_id": "fsmt-1", "efs_security_groups": ["sg-1", "sg-2"]},
    ),
    "efs.filesystem.delete": _contract(
        title="EFS file system deleted",
        what_happened="An EFS file system was deleted.",
        facts="{% if event.extra.efs_filesystem_id %}File system: {{ event.extra.efs_filesystem_id }}\n{% endif %}{% if event.extra.efs_filesystem_name %}Name: {{ event.extra.efs_filesystem_name }}\n{% endif %}Actor: {{ event.actor.principal }}\nWhen: {{ event.event_time }}",
        decision="Treat this as a critical destructive change and confirm the deletion, backup coverage, and owner immediately.", next_steps="1. Verify the deletion request and last known-good backup.\n2. Check dependent workload failures and data-retention obligations.\n3. Escalate restoration from backup according to the runbook.", why_it_matters="Deleting an EFS file system can remove shared data and break every dependent workload.", evidence="CloudTrail recorded an EFS file-system deletion.", monitoring_method="AWS CloudTrail EFS file-system lifecycle events.", impact="Shared data may be unavailable or permanently lost if no recoverable copy exists.", recovery="Recovery requires deliberate restore from an available backup or snapshot; no automatic recovery is claimed.", preview_extra={"efs_filesystem_id": "fs-0123", "efs_filesystem_name": "prod-files"},
    ),
}


def _network_contract(key: str, title: str, happened: str, facts: str, decision: str, steps: str, why: str, impact: str, preview: dict[str, Any]) -> dict[str, Any]:
    return _contract(
        title=title,
        what_happened=happened,
        facts=facts,
        decision=decision,
        next_steps=steps,
        why_it_matters=why,
        evidence="CloudTrail supplied the network identifiers and provider fields shown above when available.",
        monitoring_method="AWS CloudTrail VPC, peering, transit-gateway, and security-group events.",
        impact=impact,
        recovery="No automatic recovery is claimed; manual resolution requires an approved network change followed by connectivity and exposure validation.",
        preview_extra=preview,
    )


_AWS_NETWORK = {
    "network.igw.attach": _network_contract(
        "network.igw.attach", "Internet gateway attached",
        "An internet gateway was attached to a VPC, creating a potential internet path.",
        "{% if event.extra.gateway_id %}Gateway: {{ event.extra.gateway_id }}\n{% endif %}{% if event.extra.vpc_id %}VPC: {{ event.extra.vpc_id }}\n{% endif %}{% if event.source.account %}Account: {{ event.source.account }}\n{% endif %}{% if event.source.region %}Region: {{ event.source.region }}\n{% endif %}When: {{ event.event_time }}",
        "Confirm the VPC is intended to have internet connectivity and the attachment is approved.",
        "Validate route tables and public subnets; confirm the owner and change ticket; check for newly reachable workloads; detach through the approved process if unauthorized.",
        "An internet gateway can expose a VPC when routes and public addressing permit it.",
        "Connectivity or exposure may have changed; exposure is not inferred without route validation.", {"gateway_id": "igw-123", "vpc_id": "vpc-123"},
    ),
    "network.peering.accept": _network_contract(
        "network.peering.accept", "VPC peering accepted",
        "A VPC peering request was accepted, creating a potential cross-VPC path.",
        "{% if event.extra.peering_id %}Peering: {{ event.extra.peering_id }}\n{% endif %}{% if event.extra.source_vpc_id %}Source VPC: {{ event.extra.source_vpc_id }}\n{% endif %}{% if event.extra.destination_vpc_id %}Destination VPC: {{ event.extra.destination_vpc_id }}\n{% endif %}{% if event.extra.source_account %}Source account: {{ event.extra.source_account }}\n{% endif %}{% if event.extra.destination_account %}Destination account: {{ event.extra.destination_account }}\n{% endif %}When: {{ event.event_time }}",
        "Confirm both VPC owners approved the peering and that routes and security groups allow only intended connectivity.",
        "Validate both accounts and owners; review routes, DNS, and security-group reachability; confirm the change ticket; delete the peering through the approved process if unauthorized.",
        "Peering can bypass assumptions that the two VPCs are isolated.",
        "Cross-VPC connectivity may be available; actual reachability depends on routes and controls.", {"peering_id": "pcx-123", "source_vpc_id": "vpc-a", "destination_vpc_id": "vpc-b", "source_account": "222222222222", "destination_account": "111111111111"},
    ),
    "network.tgw_peering.accept": _network_contract(
        "network.tgw_peering.accept", "Transit gateway peering accepted",
        "A transit gateway peering request was accepted, creating a potential routed cross-network path.",
        "{% if event.extra.peering_id %}Attachment: {{ event.extra.peering_id }}\n{% endif %}{% if event.extra.source_vpc_id %}Source transit gateway: {{ event.extra.source_vpc_id }}\n{% endif %}{% if event.extra.destination_vpc_id %}Destination transit gateway: {{ event.extra.destination_vpc_id }}\n{% endif %}{% if event.extra.source_account %}Source account: {{ event.extra.source_account }}\n{% endif %}{% if event.extra.destination_account %}Destination account: {{ event.extra.destination_account }}\n{% endif %}When: {{ event.event_time }}",
        "Confirm both gateway owners approved the connection and that route propagation is intentional.",
        "Verify gateway owners and change ticket; review propagated routes and reachable CIDRs; test only intended connectivity; delete the peering through the approved process if unauthorized.",
        "Transit-gateway peering can expand the blast radius of a route mistake across multiple networks.",
        "Additional routed networks may become reachable; actual exposure depends on route propagation and controls.", {"peering_id": "tgw-attach-123", "source_account": "222222222222", "destination_account": "111111111111"},
    ),
    "network.sg.ingress.add": _network_contract(
        "network.sg.ingress.add", "Security-group ingress rule added",
        "An inbound security-group rule was added.",
        "{% if event.extra.security_group_id %}Security group: {{ event.extra.security_group_id }}\n{% endif %}{% if event.extra.protocol %}Protocol: {{ event.extra.protocol }}\n{% endif %}{% if event.extra.port_range %}Ports: {{ event.extra.port_range }}\n{% endif %}{% if event.extra.cidrs %}CIDRs: {{ event.extra.cidrs | join(', ') }}\n{% endif %}{% if event.extra.exposure_summary %}Public exposure: {{ event.extra.exposure_summary }}\n{% endif %}When: {{ event.event_time }}",
        "Confirm the rule provides only intended connectivity; treat public or risky exposure as unauthorized until proven otherwise.",
        "Validate CIDR, protocol, and ports against the design; confirm owner and ticket; test intended connectivity and public reachability; revoke through the approved process if unnecessary.",
        "Ingress rules directly define who can reach a workload.",
        "Inbound reachability changed; public or risky exposure is called out only when supported by the provider rule.", {"security_group_id": "sg-123", "protocol": "tcp", "from_port": 22, "to_port": 22, "cidrs": ["0.0.0.0/0"], "public_exposure": True, "risky_exposure": True},
    ),
}


_AWS_SECRETS = {
    "secrets.secret.create": _contract(
        title="Secret created · {{ event.extra.secret_name or event.target.name or event.target.id }}",
        what_happened="A new AWS Secrets Manager secret was created.",
        facts="{% if event.extra.secret_name %}Secret: {{ event.extra.secret_name }}\n{% endif %}{% if event.extra.secret_arn %}ARN: {{ event.extra.secret_arn }}\n{% endif %}{% if event.extra.kms_key_id %}KMS key: {{ event.extra.kms_key_id }}\n{% endif %}{% if event.extra.version_stages %}Stages: {{ event.extra.version_stages | join(', ') }}\n{% endif %}{% if event.extra.description %}Description: {{ event.extra.description }}\n{% endif %}Actor: {{ event.actor.principal }}\nAccount: {{ event.source.account }}\nRegion: {{ event.source.region }}\nWhen: {{ event.event_time }}",
        decision="Confirm the secret, owner, encryption key, and consuming services were approved for creation.",
        next_steps="1. Verify the owner and change ticket.\n2. Confirm the KMS key and resource policy restrict access.\n3. Identify consumers and confirm the initial version was delivered through an approved channel.",
        why_it_matters="A newly created credential can enable access to production systems if ownership or permissions are wrong.",
        evidence="CloudTrail supplied the lifecycle action and the available secret metadata; no secret value is collected.",
        monitoring_method="AWS CloudTrail Secrets Manager lifecycle events.",
        impact="A new credential may change how workloads authenticate to dependent systems.",
        recovery="No automatic recovery is claimed; manual resolution requires owner confirmation and permission review.",
        preview_extra={"secret_name": "prod/db", "secret_arn": "arn:aws:secretsmanager:us-east-1:111111111111:secret:prod/db", "kms_key_id": "key-123", "version_stages": ["AWSCURRENT"], "description": "database credential"},
    ),
    "secrets.secret.update": _contract(
        title="Secret updated · {{ event.extra.secret_name or event.target.name or event.target.id }}",
        what_happened="An AWS Secrets Manager secret or its metadata was updated.",
        facts="{% if event.extra.secret_name %}Secret: {{ event.extra.secret_name }}\n{% endif %}{% if event.extra.secret_arn %}ARN: {{ event.extra.secret_arn }}\n{% endif %}{% if event.extra.change_type %}Change: {{ event.extra.change_type }}\n{% endif %}{% if event.extra.version_id %}Version: {{ event.extra.version_id }}\n{% endif %}{% if event.extra.version_stages %}Stages: {{ event.extra.version_stages | join(', ') }}\n{% endif %}{% if event.extra.kms_key_id %}KMS key: {{ event.extra.kms_key_id }}\n{% endif %}Actor: {{ event.actor.principal }}\nAccount: {{ event.source.account }}\nRegion: {{ event.source.region }}\nWhen: {{ event.event_time }}",
        decision="Determine whether the change was an approved rotation, metadata change, or unauthorized credential replacement.",
        next_steps="1. Confirm the actor and change ticket.\n2. Check consumers for authentication failures and verify the intended version stage.\n3. If unauthorized, revoke access, rotate through the approved process, and review recent secret reads.",
        why_it_matters="A secret update can invalidate workloads or replace a credential trusted by multiple systems.",
        evidence="CloudTrail supplied the change metadata shown above; secret values are intentionally excluded.",
        monitoring_method="AWS CloudTrail Secrets Manager update and version events.",
        impact="Consumers may fail authentication, or an unauthorized actor may have changed a trusted credential.",
        recovery="Recovery requires a confirmed approved version and healthy consumer authentication; no automatic recovery is claimed.",
        preview_extra={"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "change_type": "value or metadata updated", "version_id": "v2", "version_stages": ["AWSCURRENT"], "kms_key_id": "key-123"},
    ),
    "secrets.secret.restore": _contract(
        title="Secret deletion cancelled · {{ event.extra.secret_name or event.target.name or event.target.id }}",
        what_happened="A previously scheduled AWS Secrets Manager deletion was cancelled and the secret was restored.",
        facts="{% if event.extra.secret_name %}Secret: {{ event.extra.secret_name }}\n{% endif %}{% if event.extra.secret_arn %}ARN: {{ event.extra.secret_arn }}\n{% endif %}{% if event.extra.recovery_window_days is not none %}Deletion window: {{ event.extra.recovery_window_days }} days\n{% endif %}Actor: {{ event.actor.principal }}\nAccount: {{ event.source.account }}\nRegion: {{ event.source.region }}\nWhen: {{ event.event_time }}",
        decision="Confirm the restore was intended and that consumers should continue using this secret.",
        next_steps="1. Verify the owner and deletion ticket.\n2. Confirm the active version, resource policy, and consuming workloads.\n3. Close the deletion incident only after consumer health is confirmed.",
        why_it_matters="Restoring a secret preserves access to a credential that may have been scheduled for removal.",
        evidence="CloudTrail supplied the restore action and available identifiers; no secret value is collected.",
        monitoring_method="AWS CloudTrail Secrets Manager restore events.",
        impact="Consumers retain access to the restored credential; an unintended restore may preserve unnecessary access.",
        recovery="This is itself a restore event; consumer recovery is valid only when matching healthy authentication is observed.",
        preview_extra={"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "recovery_window_days": 7},
    ),
    "secrets.secret.delete": _contract(
        title="Secret scheduled for deletion · {{ event.extra.secret_name or event.target.name or event.target.id }}",
        what_happened="An AWS Secrets Manager secret was scheduled for deletion or force-deleted.",
        facts="{% if event.extra.secret_name %}Secret: {{ event.extra.secret_name }}\n{% endif %}{% if event.extra.secret_arn %}ARN: {{ event.extra.secret_arn }}\n{% endif %}{% if event.extra.recovery_window_days is not none %}Recovery window: {{ event.extra.recovery_window_days }} days\n{% endif %}{% if event.extra.force_delete is not none %}Force delete: {{ event.extra.force_delete }}\n{% endif %}Actor: {{ event.actor.principal }}\nAccount: {{ event.source.account }}\nRegion: {{ event.source.region }}\nWhen: {{ event.event_time }}",
        decision="Treat this as high risk until the owner confirms the deletion and all consumers have been assessed.",
        next_steps="1. Identify every consumer and the last known-good credential version.\n2. Confirm the recovery window and whether force deletion was used.\n3. Cancel deletion or restore through the approved process; rotate dependents if the deletion was unauthorized.",
        why_it_matters="Deletion can break production authentication and may remove the recovery path for a trusted credential.",
        evidence="CloudTrail supplied the deletion metadata shown above; secret values are never included.",
        monitoring_method="AWS CloudTrail Secrets Manager deletion events.",
        impact="Dependent workloads may lose authentication, and force deletion can remove the recovery window.",
        recovery="No automatic recovery is claimed; manual resolution requires a matching restore event and verified healthy consumers.",
        preview_extra={"secret_name": "prod/db", "secret_arn": "arn:secret:prod/db", "recovery_window_days": 7, "force_delete": False},
    ),
}


_AWS_STORAGE = {
    "storage.snapshot.modify": _contract(
        title="EBS snapshot sharing changed{{ (' · ' ~ (event.extra.snapshot_id or event.target.id)) if (event.extra.snapshot_id or event.target.id) else '' }}",
        what_happened="An EBS snapshot sharing permission changed.",
        facts=("{% if event.extra.snapshot_id or event.target.id %}Snapshot: {{ event.extra.snapshot_id or event.target.id }}\n{% endif %}"
               "{% if event.extra.volume_id %}Volume: {{ event.extra.volume_id }}\n{% endif %}"
               "{% if event.extra.snapshot_share_scope %}Sharing scope: {{ event.extra.snapshot_share_scope }}\n{% endif %}"
               "{% if event.extra.snapshot_shared_accounts %}Shared accounts: {{ event.extra.snapshot_shared_accounts | join(', ') }}\n{% endif %}"
               "{% if event.extra.snapshot_public %}Public access: yes\n{% endif %}"
               "{% if event.extra.snapshot_removed_accounts %}Removed accounts: {{ event.extra.snapshot_removed_accounts | join(', ') }}\n{% endif %}"
               "{% if event.extra.snapshot_removed_public %}Removed public access: yes\n{% endif %}"
               "{% if event.extra.snapshot_share_scope_before %}Sharing before: {{ event.extra.snapshot_share_scope_before }}\n{% endif %}"
               "{% if event.extra.snapshot_share_scope_current %}Sharing now: {{ event.extra.snapshot_share_scope_current }}\n{% endif %}"
               "{% if event.extra.encrypted is defined and event.extra.encrypted is not none %}Encrypted: {{ event.extra.encrypted }}\n{% endif %}"
               "{% if event.extra.kms_key_id %}KMS key: {{ event.extra.kms_key_id }}\n{% endif %}"
               "Actor: {{ event.actor.principal }}\nAccount: {{ event.source.account }}\nRegion: {{ event.source.region }}\nWhen: {{ event.event_time }}"),
        decision="Treat public exposure as urgent; confirm the permission change is approved before relying on this snapshot for recovery.",
        next_steps="Remove public access immediately if unauthorized; review every shared account, snapshot contents, encryption, retention, and restore permissions; preserve the CloudTrail evidence and approved baseline.",
        why_it_matters="EBS snapshots can contain recoverable copies of sensitive workloads and are directly restorable by permitted principals.",
        evidence="CloudTrail supplied the snapshot permission change and the sharing scope shown above; data access is not inferred from this event alone.",
        monitoring_method="AWS CloudTrail EC2 ModifySnapshotAttribute events.",
        impact="The snapshot's restore boundary changed; public or cross-account access may expose stored data.",
        recovery="No automatic recovery is claimed; manually resolve only after unintended sharing is removed and an approved, restorable snapshot configuration is verified.",
        preview_extra={"snapshot_id": "snap-0123", "volume_id": "vol-0456", "snapshot_share_scope": "public and cross-account", "snapshot_shared_accounts": ["222222222222"], "snapshot_public": True, "encrypted": True},
    ),
}

_ALL = {**_VPN, **_CERT, **_HOST, **_RDS, **_SERVICE, **_AWS_IAM, **_AWS_S3, **_API_GATEWAY, **_AWS_POSTURE, **_AWS_NETWORK, **_AWS_COMPUTE, **_AWS_BACKUP, **_AWS_STORAGE, **_AWS_EFS, **_AWS_SECRETS, **_FINDINGS}


def field_guidance(event_key: str) -> list[str]:
    """Return the editable placeholders that make sense for one event."""
    base = ["{target_name}", "{event_time}", "{severity}", "{evidence}", "{monitoring_method}", "{impact}", "{recovery_event}"]
    if event_key.startswith("vpn."):
        base += ["{principal}", "{source_ip}", "{server}"]
        if event_key.startswith("vpn.service."):
            base += ["{previous_state}", "{current_state}"]
        elif event_key.startswith("vpn.session."):
            base += ["{common_name}", "{identity}", "{source_ips}"]
        elif event_key.startswith("vpn.bruteforce"):
            base += ["{count_in_window}", "{threshold}", "{window_seconds}"]
        elif event_key.startswith("vpn.cert."):
            base += ["{certificate_subject}", "{days_remaining}", "{not_after}", "{certificate_path}", "{certificate_error}"]
    elif event_key.startswith("cert."):
        base += ["{certificate_subject}", "{issuer}", "{sans}", "{days_remaining}", "{not_after}", "{certificate_path}", "{certificate_error}", "{port}"]
    elif event_key.startswith("service.") or event_key.startswith("probe.agent."):
        base += ["{service_name}", "{vpc}", "{monitor_tier}", "{error_signal}", "{latency_ms}", "{consecutive_failures}", "{consecutive_successes}", "{downtime}", "{unknown_duration}", "{age_seconds}", "{last_report}", "{agent_version}", "{monitoring_impact}"]
    elif event_key.startswith(("iam.", "kms.", "cloudtrail.", "auth.")):
        base += ["{principal}", "{source_ip}", "{account}", "{region}", "{event_name}", "{error_code}", "{mfa_used}", "{user_agent}"]
    elif event_key.startswith("s3.object."):
        base += ["{principal}", "{source_ip}", "{operation}", "{http_status}", "{bytes_sent}", "{error_code}", "{auth_type}"]
    elif event_key.startswith("s3.bucket."):
        base += ["{account}", "{region}", "{public}", "{public_reasons}", "{encryption}", "{versioning}", "{last_scan}"]
    elif event_key.startswith("host."):
        base += ["{principal}", "{source_ip}", "{instance_id}"]
        if ".auth." in event_key or event_key.startswith("host.bruteforce"):
            base += ["{user}", "{count_in_window}", "{window_seconds}"]
        elif ".agent." in event_key or ".collector." in event_key:
            base += ["{last_report}", "{agent_version}", "{collector}"]
        elif ".fim." in event_key or event_key in {"host.file.changed", "host.sudoers.changed", "host.cron.changed"}:
            base += ["{path}", "{change_type}", "{hash}", "{owner}"]
        elif ".cpu." in event_key or ".memory." in event_key:
            base += ["{value}", "{baseline}", "{threshold}", "{duration_seconds}"]
        elif ".disk." in event_key:
            base += ["{mount}", "{value}", "{threshold}"]
        elif event_key in {"host.process.first_seen", "host.oom_kill"}:
            base += ["{process}", "{pid}"]
        elif event_key.startswith("host.kernel.module"):
            base += ["{kernel_module}"]
        elif event_key in {"host.packages.changed", "host.package_db.corrupted", "host.package_db.recovered"}:
            base += ["{package}", "{error}"]
        elif event_key == "host.port.opened":
            base += ["{port}", "{process}"]
        elif event_key == "host.service.added":
            base += ["{service_name}", "{state}"]
    elif event_key.startswith("rds."):
        base += ["{principal}", "{source_ip}", "{db_instance}"]
        if event_key.startswith("rds.auth."):
            base += ["{reason}", "{failure_count}", "{window_minutes}"]
        elif event_key.startswith("rds.session."):
            base += ["{database}", "{session_id}", "{duration_seconds}", "{idle_hours}"]
        elif event_key.startswith("rds.proxy."):
            base += ["{source_port}", "{reason}", "{change}"]
        elif event_key.startswith("rds.query."):
            base += ["{query}", "{function}", "{role}", "{object}"]
        elif event_key in {"rds.instance.create", "rds.instance.delete", "rds.instance.modify", "rds.snapshot.modify", "rds.parameter_group.modify"}:
            base += ["{change}"]
        elif event_key == "rds.error":
            base += ["{error}"]
        elif event_key == "rds.user.unknown":
            base += ["{user}", "{trigger}"]
    elif event_key.startswith("api."):
        base += ["{api_name}", "{source_ip}", "{method}", "{route_key}", "{status}", "{integration_status}", "{response_length}", "{response_latency_ms}", "{request_id}"]
        if event_key == "api.auth.failure":
            base += ["{reason}", "{error_message}"]
        elif event_key == "api.auth.burst":
            base += ["{failure_count}", "{window_minutes}"]
        elif event_key == "api.error":
            base += ["{reason}", "{error_message}"]
        elif event_key == "api.error.burst":
            base += ["{error_count}", "{window_minutes}"]
        elif event_key == "api.scanner_ua":
            base += ["{user_agent}", "{scanner_signature}"]
    elif event_key == "network.sg.instance_attach":
        base += ["{account}", "{region}", "{instance_id}", "{sg_ids}"]
    elif event_key.startswith("network."):
        base += ["{vpc_id}", "{subnet_id}", "{gateway_id}", "{peering_id}", "{source_vpc_id}", "{destination_vpc_id}", "{source_account}", "{destination_account}", "{source_region}", "{destination_region}", "{security_group_id}", "{protocol}", "{from_port}", "{to_port}", "{cidrs}", "{public_exposure}", "{risky_exposure}"]
    elif event_key.startswith("backup."):
        base += ["{account}", "{region}", "{job_id}", "{recovery_point_arn}", "{resource_arn}", "{vault_name}", "{vault_arn}", "{source_vault_arn}", "{destination_vault_arn}", "{destination_account}", "{destination_region}", "{plan_name}", "{recovery_point_time}", "{retention_days}", "{policy_summary}", "{backup_vault_policy_wildcard}", "{backup_copy_dest_account}"]
    elif event_key.startswith("storage."):
        base += ["{snapshot_id}", "{volume_id}", "{snapshot_share_scope}", "{snapshot_shared_accounts}", "{snapshot_public}", "{encrypted}", "{kms_key_id}", "{account}", "{region}"]
    elif event_key.startswith("efs."):
        base += ["{account}", "{region}", "{efs_filesystem_id}", "{efs_filesystem_name}", "{efs_mount_target_id}", "{efs_subnet_id}", "{efs_availability_zone}", "{efs_ip_address}", "{efs_security_groups}", "{efs_policy_summary}", "{efs_policy_wildcard}"]
    elif event_key.startswith("secrets.secret."):
        base += ["{secret_name}", "{secret_arn}", "{description}", "{kms_key_id}", "{version_id}", "{version_stages}", "{rotation_enabled}", "{rotation_days}", "{recovery_window_days}", "{force_delete}", "{change_type}", "{account}", "{region}"]
    elif event_key.startswith("aws.posture.finding."):
        base += ["{account}", "{region}", "{finding_id}", "{resource_id}", "{resource_type}", "{finding_type}", "{resolved_at}"]
    elif event_key == "ueba.anomaly" or ".anomaly.first_seen_" in event_key:
        base += ["{principal}", "{source_ip}", "{dimension}", "{baseline_value}", "{principal_type}", "{source_country}", "{source_asn}", "{user_agent_family}", "{hour_of_day}", "{trigger_action}", "{trigger_event_id}"]
    elif event_key == "finding.malware.detected":
        base += ["{signature}", "{detection}", "{resource}", "{object_path}", "{file_hash}", "{scan_time}", "{engine}", "{confidence}", "{containment_state}", "{owner}", "{vendor}"]
    elif event_key == "<finding>.detected" or event_key.startswith("finding."):
        base += ["{finding_type}", "{finding_id}", "{resource}", "{owner}", "{vendor}"]
    if event_key.startswith("aws.posture.finding"):
        base += ["{evidence}"]
    return list(dict.fromkeys(base))


def apply_event_contracts(catalog: Iterable[dict[str, Any]], content_fields: Iterable[str]) -> None:
    """Apply event contracts in place after the profile catalog is built."""
    fields = list(content_fields)
    for module in catalog:
        for event in module.get("events") or []:
            event_key = str(event.get("key"))
            contract = _ALL.get(event_key)
            if contract is None and (event_key == "<category>.anomaly.first_seen_*" or event_key == "ueba.anomaly"):
                contract = _UEBA_DYNAMIC
            if contract is None and event_key == "<finding>.detected":
                contract = _FINDINGS["<finding>.detected"]
            if not contract:
                continue
            defaults = event.setdefault("defaults", {})
            defaults.update({key: value for key, value in contract.items() if key not in {"preview_extra", "preview_sample"}})
            event["content_fields"] = list(fields)
            event["content_status"] = "rolled_out"
            event["content_gap"] = False
            event["available_fields"] = field_guidance(str(event.get("key")))
            sample = dict(event.get("preview_sample") or {})
            sample.update(contract.get("preview_sample") or {})
            extra = dict(sample.get("extra") or {})
            extra.update(contract.get("preview_extra") or {})
            sample["extra"] = extra
            event["preview_sample"] = sample
        if module.get("events") and all(
            event.get("notification_status") != "notifying"
            or (
                (str(event.get("key")) in _ALL or str(event.get("key")) in {"<category>.anomaly.first_seen_*", "<finding>.detected"})
                and event.get("content_status") == "rolled_out"
            )
            for event in module.get("events") or []
        ):
            module["content_status"] = "rolled_out"
            module["content_gap_count"] = sum(bool(item.get("content_gap")) for item in module.get("events") or [])
