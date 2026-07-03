"""BlackWatch CloudWatch Logs forwarder (AWS Lambda).

Subscribed to one or more RDS log groups via CloudWatch Logs subscription
filters. Each invocation gets one batch of log events from a single log
group; we shape it into a single SQS message that BlackWatch's aws.rds
adapter can parse.

No parsing / decisions here -- BW does all detection. This Lambda's job is
purely: unwrap CloudWatch's gzipped envelope, add a bit of routing metadata
(which DB, which source type), forward as one message.

Env vars:
    QUEUE_URL   destination SQS queue (required)
"""

import base64
import gzip
import io
import json
import os

import boto3

_sqs = boto3.client("sqs")
_QUEUE_URL = os.environ["QUEUE_URL"]

# CloudWatch caps each subscription payload at ~256KB of *compressed* data
# and Lambda invokes us per batch. One SQS message per invocation keeps the
# batching aligned end-to-end.


def _classify(log_group: str) -> tuple[str, str]:
    """Return (db_instance, source_type) parsed from the log group name.

    Log group name conventions:
        /aws/rds/instance/<db>/postgresql
        /aws/rds/instance/<db>/mysql
        /aws/rds/instance/<db>/general
        /aws/rds/proxy/<proxy-name>            (Proxy has no per-DB grouping)
    """
    parts = log_group.split("/")
    # /aws/rds/instance/<db>/<stream>
    if len(parts) >= 5 and parts[2] == "rds" and parts[3] == "instance":
        return parts[4], "postgres"  # engine detection could branch on parts[5]
    if len(parts) >= 5 and parts[2] == "rds" and parts[3] == "proxy":
        # Proxy names often carry the DB name at the end; keep the raw proxy
        # name so the adapter can still associate messages back to the DB.
        return parts[4], "rds_proxy"
    return log_group, "unknown"


def handler(event, context):
    raw = event.get("awslogs", {}).get("data")
    if not raw:
        return {"forwarded": 0, "reason": "no awslogs payload"}
    decoded = gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(raw))).read()
    payload = json.loads(decoded)

    log_group = payload.get("logGroup") or ""
    log_stream = payload.get("logStream") or ""
    log_events = payload.get("logEvents") or []
    if not log_events:
        return {"forwarded": 0}

    db_instance, source_type = _classify(log_group)

    body = {
        "kind": "rds_log_batch",
        "log_group": log_group,
        "log_stream": log_stream,
        "db_instance": db_instance,
        "source_type": source_type,
        "owner": payload.get("owner"),
        "events": [
            {"ts": e.get("timestamp"), "message": e.get("message")}
            for e in log_events
        ],
    }
    _sqs.send_message(QueueUrl=_QUEUE_URL, MessageBody=json.dumps(body))
    return {"forwarded": len(log_events), "db_instance": db_instance, "source_type": source_type}
