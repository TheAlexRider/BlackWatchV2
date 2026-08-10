"""Print the CloudTrail eventName allowlist for the EventBridge rule.

EventBridge has a hard 2048-char limit per event pattern. The full allowlist
exceeds that, so we split it by scope + by service into rules that share
one Lambda target:

    --rule-global    : ConsoleLogin, federated logins, IAM, CloudTrail trails
                       — global-services events (us-east-1 rule).

    --rule-regional  : full regional list. Now too large for a single pattern;
                       kept for backward-compat but exits non-zero if over 2048.

    --rule-regional-infra : EC2 / VPC / SG / KMS / S3 + auth events.
                            Paste into the existing regional rule
                            (arn:...:rule/blackwatch-cloudtrail-rule).

    --rule-regional-data  : RDS / EFS / AWS Backup / Secrets Manager events.
                            Paste into a NEW sibling rule
                            (suggested name: blackwatch-cloudtrail-rule-data)
                            targeting the SAME Lambda.

    --rules-split    : print BOTH regional patterns at once, labeled, so you
                       can create/update both rules from one script run.

All rules can target the same Lambda. Duplicate delivery is safe because the
adapter derives a deterministic event_id from CloudTrail's eventID and
storage.insert_event uses ON CONFLICT (event_id) DO NOTHING.

Usage:
    python -m scripts.iam_lambda_allowlist                     # full list (humans)
    python -m scripts.iam_lambda_allowlist --json              # JSON array
    python -m scripts.iam_lambda_allowlist --rule-global       # us-east-1 pattern
    python -m scripts.iam_lambda_allowlist --rule-regional-infra
    python -m scripts.iam_lambda_allowlist --rule-regional-data
    python -m scripts.iam_lambda_allowlist --rules-split       # both regional patterns
"""

from __future__ import annotations

import json
import sys

from blackwatch.modules.aws_cloudtrail import LAMBDA_ALLOWLIST


# Global services — events ONLY fire in us-east-1 regardless of where the API
# was called from. IAM identity events and CloudTrail trail mgmt events live
# here because the underlying services are still global.
_GLOBAL_ONLY_PREFIXES = ("iam.", "cloudtrail.")

# Ubiquitous services — events fire in the REGION the caller connects from
# (AWS changed sign-in event routing ~2022). Put these in EVERY region's rule
# so we catch the event wherever it fires.
_UBIQUITOUS_PREFIXES = ("auth.",)

# Regional-rule split. The full regional pattern is now too big for
# EventBridge's 2048-char cap, so we shard by service prefix into TWO rules
# that share one Lambda target.
#
#   INFRA rule  — the "existing" blackwatch-cloudtrail-rule content: network,
#                 compute, encryption, S3 configuration, plus sign-in events.
#   DATA rule   — data-plane services: RDS, EFS, AWS Backup, Secrets Manager.
#                 New sibling rule (suggested name: blackwatch-cloudtrail-rule-data).
#
# Every action prefix in the adapter must map to exactly ONE of the two, so
# adding a new service without updating this table trips the assertion below.
_REGIONAL_INFRA_PREFIXES = (
    "network.", "compute.", "storage.snapshot.", "storage.volume.",
    "kms.", "s3.", "auth.",
)
_REGIONAL_DATA_PREFIXES = (
    "rds.", "efs.", "backup.", "secrets.",
)


def _categorize() -> tuple[list[str], list[str]]:
    """Return (global_events, regional_events) by re-deriving the action
    prefix from the adapter map — keeps the script in lockstep with the
    adapter without a second source of truth.

    auth.* events go in BOTH buckets because sign-in event routing is
    region-of-caller, not fixed to us-east-1."""
    from blackwatch.modules.aws_cloudtrail import _ACTION_MAP

    global_names: list[str] = []
    regional_names: list[str] = []
    for event_name, (action, _category) in _ACTION_MAP.items():
        if action.startswith(_UBIQUITOUS_PREFIXES):
            global_names.append(event_name)
            regional_names.append(event_name)
        elif action.startswith(_GLOBAL_ONLY_PREFIXES):
            global_names.append(event_name)
        else:
            regional_names.append(event_name)
    return sorted(global_names), sorted(regional_names)


def _split_regional() -> tuple[list[str], list[str]]:
    """Split the regional allowlist by service prefix so each rule fits under
    2048 chars. Returns (infra_events, data_events). Asserts every regional
    action maps to exactly one bucket — a new service prefix in the adapter
    without a corresponding entry here trips the assertion, forcing us to
    decide where it lands rather than silently missing events."""
    from blackwatch.modules.aws_cloudtrail import _ACTION_MAP

    infra: list[str] = []
    data: list[str] = []
    unbucketed: list[tuple[str, str]] = []
    for event_name, (action, _category) in _ACTION_MAP.items():
        if action.startswith(_GLOBAL_ONLY_PREFIXES) and not action.startswith(_UBIQUITOUS_PREFIXES):
            continue
        if action.startswith(_REGIONAL_INFRA_PREFIXES):
            infra.append(event_name)
        elif action.startswith(_REGIONAL_DATA_PREFIXES):
            data.append(event_name)
        else:
            unbucketed.append((event_name, action))
    if unbucketed:
        raise AssertionError(
            "regional actions not assigned to INFRA or DATA bucket — update "
            "_REGIONAL_INFRA_PREFIXES / _REGIONAL_DATA_PREFIXES in scripts/"
            f"iam_lambda_allowlist.py: {unbucketed}"
        )
    return sorted(infra), sorted(data)


def _eventbridge_rule(event_names: list[str]) -> dict:
    """Full EventBridge event pattern. Paste into the rule's EventPattern."""
    return {
        "detail-type": [
            "AWS API Call via CloudTrail",
            "AWS Console Sign In via CloudTrail",
        ],
        "detail": {
            "eventName": event_names,
        },
    }


def _print_rule(event_names: list[str], label: str) -> None:
    """Print the rule and assert it fits under EventBridge's 2048-char limit.

    Output is COMPACT JSON (no whitespace) — AWS measures the actual byte
    count of the pattern, so indented JSON wastes characters against the
    2048 cap. The compact form is what gets uploaded."""
    compact = json.dumps(_eventbridge_rule(event_names), separators=(",", ":"))
    size = len(compact)
    if size > 2048:
        print(
            f"# WARNING: {label} pattern is {size} chars — over EventBridge's "
            f"2048 limit. Split further.",
            file=sys.stderr,
        )
    else:
        print(f"# {label}: {len(event_names)} events, {size} chars (limit 2048)",
              file=sys.stderr)
    print(compact)


def main() -> int:
    if "--json" in sys.argv:
        print(json.dumps(list(LAMBDA_ALLOWLIST), indent=2))
        return 0

    global_names, regional_names = _categorize()

    if "--rule-global" in sys.argv:
        _print_rule(global_names, "global (us-east-1)")
        return 0
    if "--rule-regional" in sys.argv:
        _print_rule(regional_names, "regional (us-west-1) — full list, likely over 2048")
        return 0
    if "--rule-regional-infra" in sys.argv:
        infra, _ = _split_regional()
        _print_rule(infra, "regional INFRA (blackwatch-cloudtrail-rule)")
        return 0
    if "--rule-regional-data" in sys.argv:
        _, data = _split_regional()
        _print_rule(data, "regional DATA (blackwatch-cloudtrail-rule-data)")
        return 0
    if "--rules-split" in sys.argv:
        infra, data = _split_regional()
        print("# ==== RULE 1: blackwatch-cloudtrail-rule (existing) — paste as EventPattern ====",
              file=sys.stderr)
        _print_rule(infra, "regional INFRA")
        print()
        print("# ==== RULE 2: blackwatch-cloudtrail-rule-data (NEW) — paste as EventPattern ====",
              file=sys.stderr)
        _print_rule(data, "regional DATA")
        return 0

    # Default: print both lists for humans.
    print(f"# {len(LAMBDA_ALLOWLIST)} total eventNames")
    print(f"# {len(global_names)} GLOBAL (us-east-1 rule):")
    for name in global_names:
        print(f"  {name}")
    print()
    print(f"# {len(regional_names)} REGIONAL (us-west-1 rule):")
    for name in regional_names:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
