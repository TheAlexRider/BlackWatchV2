"""SQS-backed RDS log drain.

The BW `bw-log-forwarder` Lambda subscribes to each RDS CloudWatch log group
and puts one message per log batch on this queue. The connector polls the
queue, feeds each batch through the aws.rds adapter (which does all the
parsing + normalization), deletes successfully-ingested messages, and leaves
failures for redelivery / DLQ.

Mirrors the shape of blackwatch/connectors/aws_sqs.py (CloudTrail) and
aws_ecs_probe_sqs.py -- same pattern, different target_module."""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import pipeline
from .models import AwsRdsSqsConfig

_log = logging.getLogger(__name__)


def _client(cfg: AwsRdsSqsConfig):
    import boto3
    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region,
    )
    return session.client("sqs")


def drain(cfg: AwsRdsSqsConfig) -> dict[str, Any]:
    sqs = _client(cfg)
    total_messages = 0
    total_ingested = 0

    for _ in range(max(1, cfg.max_batches)):
        resp = sqs.receive_message(
            QueueUrl=cfg.queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=cfg.wait_seconds,
        )
        messages = resp.get("Messages", [])
        if not messages:
            break

        to_delete = []
        for message in messages:
            total_messages += 1
            try:
                body = json.loads(message["Body"])
            except (ValueError, KeyError):
                body = {"raw": message.get("Body")}
            try:
                result = pipeline.ingest_payload("aws.rds", body, transport="queue")
                total_ingested += result.get("ingested", 0)
                to_delete.append(
                    {"Id": message["MessageId"], "ReceiptHandle": message["ReceiptHandle"]}
                )
            except Exception as exc:
                _log.exception(
                    "aws_rds_sqs.ingest_failed message_id=%s: %s",
                    message.get("MessageId"), exc,
                )
                continue

        if to_delete:
            sqs.delete_message_batch(QueueUrl=cfg.queue_url, Entries=to_delete)

    return {"ingested": total_ingested, "messages": total_messages}
