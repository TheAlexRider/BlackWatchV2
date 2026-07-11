"""BlackWatch CloudWatch Logs forwarder (AWS Lambda).

Subscribed to one or more CloudWatch log groups (RDS + API Gateway) via
subscription filters. Each invocation gets one batch of log events from a
single log group; we shape it into a single SQS message that the matching
BlackWatch adapter can parse.

No parsing / decisions here — BW does all detection. This Lambda's job is
purely: unwrap CloudWatch's gzipped envelope, classify the log group,
forward as one message to the correct queue.

Env vars:
    QUEUE_URL          RDS destination SQS queue (required)
    API_GW_QUEUE_URL   API Gateway destination SQS queue (optional; falls back
                       to QUEUE_URL if the operator wants a single queue)
"""

import base64
import gzip
import io
import json
import os

import boto3

_sqs = boto3.client("sqs")
_RDS_QUEUE_URL = os.environ["QUEUE_URL"]
_API_GW_QUEUE_URL = os.environ.get("API_GW_QUEUE_URL", "")

# CloudWatch caps each subscription payload at ~256KB of *compressed* data
# and Lambda invokes us per batch. One SQS message per invocation keeps the
# batching aligned end-to-end.


def _classify_rds(log_group: str) -> tuple[str, str] | None:
    """Return (db_instance, source_type) for RDS log groups, or None if the
    log group doesn't match an RDS pattern."""
    parts = log_group.split("/")
    if len(parts) >= 5 and parts[2] == "rds" and parts[3] == "instance":
        return parts[4], "postgres"
    if len(parts) >= 5 and parts[2] == "rds" and parts[3] == "proxy":
        return parts[4], "rds_proxy"
    return None


def _classify_api_gw(log_group: str) -> str | None:
    """Return the API name for API Gateway log groups, or None if the log
    group doesn't match. Log group convention:
        /aws/gateway/<api-name>
    (Custom paths are supported — we take whatever comes after the /aws/gateway/
    prefix as the api identifier.)"""
    parts = log_group.split("/")
    if len(parts) >= 4 and parts[2] == "gateway":
        return "/".join(parts[3:]) or "unknown"
    # Also accept /aws/apigateway/ (older naming convention)
    if len(parts) >= 4 and parts[2] == "apigateway":
        return "/".join(parts[3:]) or "unknown"
    return None


def _forward_rds(log_group, log_stream, log_events, owner, db_instance, source_type):
    body = {
        "kind": "rds_log_batch",
        "log_group": log_group,
        "log_stream": log_stream,
        "db_instance": db_instance,
        "source_type": source_type,
        "owner": owner,
        "events": [
            {"ts": e.get("timestamp"), "message": e.get("message")}
            for e in log_events
        ],
    }
    _sqs.send_message(QueueUrl=_RDS_QUEUE_URL, MessageBody=json.dumps(body))
    return {"forwarded": len(log_events), "target": "rds",
            "db_instance": db_instance, "source_type": source_type}


def _forward_api_gw(log_group, log_stream, log_events, owner, api_name):
    """Ship API Gateway access log batches. Each event `message` is expected
    to be a JSON string (per the operator's configured JSON access log
    format). We do NOT parse it here — the BW adapter handles that."""
    queue = _API_GW_QUEUE_URL or _RDS_QUEUE_URL
    body = {
        "kind": "api_gw_log_batch",
        "log_group": log_group,
        "log_stream": log_stream,
        "api_name": api_name,
        "owner": owner,
        "events": [
            {"ts": e.get("timestamp"), "message": e.get("message")}
            for e in log_events
        ],
    }
    _sqs.send_message(QueueUrl=queue, MessageBody=json.dumps(body))
    return {"forwarded": len(log_events), "target": "api_gw", "api_name": api_name}


def handler(event, context):
    raw = event.get("awslogs", {}).get("data")
    if not raw:
        return {"forwarded": 0, "reason": "no awslogs payload"}
    decoded = gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(raw))).read()
    payload = json.loads(decoded)

    log_group = payload.get("logGroup") or ""
    log_stream = payload.get("logStream") or ""
    log_events = payload.get("logEvents") or []
    owner = payload.get("owner")
    if not log_events:
        return {"forwarded": 0}

    # Try API Gateway first — the classifier is cheaper and more specific.
    api_name = _classify_api_gw(log_group)
    if api_name is not None:
        return _forward_api_gw(log_group, log_stream, log_events, owner, api_name)

    rds = _classify_rds(log_group)
    if rds is not None:
        db_instance, source_type = rds
        return _forward_rds(log_group, log_stream, log_events, owner, db_instance, source_type)

    # Unknown log group — still forward to RDS queue with kind=unknown so
    # nothing silently disappears; the adapter will drop it.
    body = {
        "kind": "unknown_log_batch",
        "log_group": log_group,
        "log_stream": log_stream,
        "owner": owner,
        "events": [
            {"ts": e.get("timestamp"), "message": e.get("message")}
            for e in log_events
        ],
    }
    _sqs.send_message(QueueUrl=_RDS_QUEUE_URL, MessageBody=json.dumps(body))
    return {"forwarded": len(log_events), "target": "unknown", "log_group": log_group}
