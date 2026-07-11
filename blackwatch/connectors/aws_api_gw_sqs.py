"""SQS-backed API Gateway access-log drain.

The BW `bw-rds-forwarder` Lambda (extended in Phase 1 to handle
/aws/gateway/* log groups) subscribes to each API Gateway stage's access
log group and puts one message per log batch on a dedicated queue. This
connector polls the queue, feeds each batch through the aws.api_gw
adapter, deletes successfully-ingested messages, and leaves failures for
redelivery / DLQ.

Same shape as aws_rds_sqs.py — different target_module."""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import pipeline
from .models import AwsApiGwSqsConfig

_log = logging.getLogger(__name__)


def _client(cfg: AwsApiGwSqsConfig):
    import boto3
    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region,
    )
    return session.client("sqs")


def drain(cfg: AwsApiGwSqsConfig) -> dict[str, Any]:
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
                result = pipeline.ingest_payload("aws.api_gw", body, transport="queue")
                total_ingested += result.get("ingested", 0)
                to_delete.append(
                    {"Id": message["MessageId"], "ReceiptHandle": message["ReceiptHandle"]}
                )
            except Exception as exc:
                _log.exception(
                    "aws_api_gw_sqs.ingest_failed message_id=%s: %s",
                    message.get("MessageId"), exc,
                )
                continue

        if to_delete:
            sqs.delete_message_batch(QueueUrl=cfg.queue_url, Entries=to_delete)

    return {"ingested": total_ingested, "messages": total_messages}
