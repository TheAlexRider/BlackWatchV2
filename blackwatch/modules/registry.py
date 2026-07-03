"""Adapter registry. Maps a logical module id to the adapter that normalizes it.

Lookups fall back to the generic adapter, so any token->module mapping works
out of the box and can later be upgraded by registering a dedicated adapter
under that module id — no core changes required."""

from __future__ import annotations

from .aws_cloudtrail import AwsCloudTrailAdapter
from .aws_posture import AwsPostureAdapter
from .aws_rds import AwsRdsAdapter
from .aws_s3 import AwsS3Adapter
from .base import Adapter
from .cert_expiry import CertExpiryAdapter
from .ec2_host import Ec2HostAdapter
from .ecs_probe import EcsProbeAdapter
from .generic import GenericAdapter
from .vpn_openvpn import VpnOpenVpnAdapter

_registry: dict[str, Adapter] = {}

GENERIC_MODULE = "generic"


def register(adapter: Adapter) -> None:
    _registry[adapter.module] = adapter


def resolve(module: str) -> Adapter:
    """Return the dedicated adapter for `module`, or the generic fallback."""
    return _registry.get(module) or _registry[GENERIC_MODULE]


def registered_modules() -> list[str]:
    return sorted(_registry.keys())


def register_builtins() -> None:
    register(GenericAdapter())
    register(VpnOpenVpnAdapter())
    register(AwsCloudTrailAdapter())
    register(AwsRdsAdapter())
    register(Ec2HostAdapter())
    register(EcsProbeAdapter())
    register(AwsS3Adapter())
    register(AwsPostureAdapter())
    register(CertExpiryAdapter())
