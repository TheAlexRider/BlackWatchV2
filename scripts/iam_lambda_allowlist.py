"""Print the CloudTrail eventName allowlist for the EventBridge rule.

The /iam page renders only events that the adapter knows how to normalize.
The EventBridge rule in front of the ingest Lambda MUST forward exactly the
eventName values in `LAMBDA_ALLOWLIST` — anything else is noise that wastes
SQS quota, DB rows, and projector cycles.

Usage:
    python -m scripts.iam_lambda_allowlist           # human-readable list
    python -m scripts.iam_lambda_allowlist --json    # JSON array for the rule
    python -m scripts.iam_lambda_allowlist --rule    # full EventBridge rule
"""

from __future__ import annotations

import json
import sys

from blackwatch.modules.aws_cloudtrail import LAMBDA_ALLOWLIST


def _eventbridge_rule() -> dict:
    """The full EventBridge event pattern. Paste into the rule's
    `EventPattern` field (Terraform / console). The Sign-In service emits
    ConsoleLogin from a different detail-type, so we list both."""
    return {
        "detail-type": [
            "AWS API Call via CloudTrail",
            "AWS Console Sign In via CloudTrail",
        ],
        "detail": {
            "eventName": list(LAMBDA_ALLOWLIST),
        },
    }


def main() -> int:
    if "--json" in sys.argv:
        print(json.dumps(list(LAMBDA_ALLOWLIST), indent=2))
        return 0
    if "--rule" in sys.argv:
        print(json.dumps(_eventbridge_rule(), indent=2))
        return 0

    print(f"# {len(LAMBDA_ALLOWLIST)} eventNames in the allowlist:")
    for name in LAMBDA_ALLOWLIST:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
