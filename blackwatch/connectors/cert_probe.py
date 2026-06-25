"""TLS cert expiry probe — connects to a list of `host:port` endpoints,
reads their leaf certificate, computes days until expiry, and ships a report
through the standard ingest pipeline (`cert` module).

No agent / no remote install required. Works against any plain HTTPS endpoint:
ALBs, internal nginx, the Lightsail box's own cert, third-party APIs.

**Known gap:** OpenVPN's UDP-based handshake does not respond to a vanilla
`openssl s_client`-style probe. Catching the OpenVPN server cert (the one
that expired June 4) needs an SSH-based read of `/etc/openvpn/server/issued/
server_*.crt` — that's a follow-up connector variant.
"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from typing import Any

from .. import pipeline
from .models import CertProbeConfig


def _parse_cert(der: bytes) -> dict[str, Any]:
    """Parse a DER-encoded X.509 cert into the fields we care about.
    Uses `cryptography` because the stdlib ssl module only returns the parsed
    dict form when CERT_REQUIRED succeeded — which never includes the case we
    most care about (an *expired* cert that we want to detect)."""
    from cryptography import x509  # local import — keeps cold start fast
    from cryptography.x509.oid import ExtensionOID

    cert = x509.load_der_x509_certificate(der)

    # not_valid_after_utc is the modern API (cryptography >= 42). Fall back to
    # the deprecated naive accessor for older versions.
    try:
        not_after_dt = cert.not_valid_after_utc
    except AttributeError:
        not_after_dt = cert.not_valid_after.replace(tzinfo=timezone.utc)

    sans: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        sans = [str(n.value) for n in ext.value]
    except x509.ExtensionNotFound:
        pass

    days_remaining = (not_after_dt - datetime.now(timezone.utc)).total_seconds() / 86400

    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_after": not_after_dt.isoformat(),
        "days_remaining": round(days_remaining, 2),
        "sans": sans,
    }


def _probe_one(name: str, host: str, port: int, sni: str | None, timeout: int) -> dict[str, Any]:
    """Probe a single host:port. Returns a target-shaped dict that the adapter
    knows how to consume. Failures are captured into the dict — they never
    raise."""
    base: dict[str, Any] = {
        "name": name or f"{host}:{port}",
        "host": host,
        "port": port,
    }
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # we WANT to read expired certs
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=sni or host) as ssock:
                der = ssock.getpeercert(binary_form=True)
        if not der:
            return {**base, "ok": False, "error": "no certificate returned by peer"}
        parsed = _parse_cert(der)
        return {**base, **parsed, "ok": True}
    except Exception as exc:
        return {**base, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def scan(cfg: CertProbeConfig) -> dict[str, Any]:
    """Run all configured probes. Returns the report shape the adapter wants."""
    targets: list[dict[str, Any]] = []
    for t in cfg.targets:
        targets.append(_probe_one(
            name=t.name, host=t.host, port=t.port,
            sni=t.sni, timeout=cfg.timeout_seconds,
        ))
    return {
        "scan_completed_at": datetime.now(timezone.utc).isoformat(),
        "targets": targets,
    }


def poll(cfg: CertProbeConfig) -> dict[str, Any]:
    """Connector entry — called by the scheduler. Same pipeline path as any
    other ingest source."""
    report = scan(cfg)
    stats = pipeline.ingest_payload("cert", report, transport="poll")
    ok = sum(1 for t in report["targets"] if t.get("ok"))
    failed = sum(1 for t in report["targets"] if not t.get("ok"))
    return {
        "ingested": stats.get("ingested", 0),
        "targets_checked": len(report["targets"]),
        "ok": ok,
        "failed": failed,
    }
