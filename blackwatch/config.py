"""Runtime configuration, read from environment. Kept deliberately small."""

from __future__ import annotations

import os


def _parse_token_map(raw: str) -> dict[str, str]:
    """Parse "token1:module1,token2:module2" -> {token1: module1, ...}.

    The token a source presents determines which logical module its events are
    stamped with. If no dedicated adapter is registered for that module, the
    generic passthrough adapter handles it (see modules/registry.py)."""
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        token, module = part.split(":", 1)
        token, module = token.strip(), module.strip()
        if token and module:
            mapping[token] = module
    return mapping


def _parse_probe_vpcs(raw: str) -> dict[str, str]:
    """Parse "tokenA:prod,tokenB:dev" -> {tokenA: 'prod', tokenB: 'dev'}.
    Each probe agent presents this token when fetching its target list; the
    token tells BW which VPC's targets to return. Tokens here MUST also appear
    in BLACKWATCH_TOKENS with module=ecs.probe so the same token works for
    POST /ingest."""
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        token, vpc = part.split(":", 1)
        token, vpc = token.strip(), vpc.strip()
        if token and vpc:
            mapping[token] = vpc
    return mapping


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.environ.get(
            "DATABASE_URL",
            "postgresql://blackwatch:blackwatch@localhost:5432/blackwatch",
        )
        self.token_module_map: dict[str, str] = _parse_token_map(
            os.environ.get("BLACKWATCH_TOKENS", "devtoken:generic")
        )
        # Per-VPC probe agent tokens. The same token must also appear in
        # BLACKWATCH_TOKENS mapped to module=ecs.probe.
        self.probe_token_vpc_map: dict[str, str] = _parse_probe_vpcs(
            os.environ.get("BLACKWATCH_PROBE_VPCS", "")
        )
        self.default_account: str | None = os.environ.get("BLACKWATCH_ACCOUNT") or None
        self.rules_dir: str = os.environ.get("RULES_DIR", "rules")
        self.notifications_file: str = os.environ.get(
            "NOTIFICATIONS_FILE", "notifications.yaml"
        )


settings = Settings()
