"""Print the CloudTrail eventName allowlist for the EventBridge rule.

EventBridge has a hard 2048-char limit per event pattern. The full allowlist
exceeds that, so we split it by **scope** into two regional rules that share
one Lambda target:

    --rule-global    : ConsoleLogin, federated logins, IAM, CloudTrail trails
                       — events that ALWAYS fire in us-east-1 (global services).
                       Put this in the us-east-1 EventBridge rule.

    --rule-regional  : EC2 / VPC / SG / KMS / S3 / RDS — events that fire in
                       the region the resource lives in. Put this in the
                       us-west-1 EventBridge rule (and any other region you
                       operate in).

Both rules can target the SAME Lambda — cross-region invoke is supported.

Usage:
    python -m scripts.iam_lambda_allowlist                 # full list (humans)
    python -m scripts.iam_lambda_allowlist --json          # JSON array
    python -m scripts.iam_lambda_allowlist --rule-global   # us-east-1 pattern
    python -m scripts.iam_lambda_allowlist --rule-regional # us-west-1 pattern
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
        _print_rule(regional_names, "regional (us-west-1)")
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
