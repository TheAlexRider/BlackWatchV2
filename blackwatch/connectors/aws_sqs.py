"""SQS-backed CloudTrail collection. Receives the events an EventBridge->Lambda
forwarder placed on the queue, runs each through the ingest pipeline, and
deletes only the ones that ingested successfully (failures redeliver / land in
the queue's DLQ). boto3 is imported lazily so the app runs without it until an
AWS connector is actually used."""

from __future__ import annotations

import json
from typing import Any

from .. import pipeline
from .models import AwsCloudtrailSqsConfig


def _client(cfg: AwsCloudtrailSqsConfig):
    import boto3  # lazy import

    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region
    )
    return session.client("sqs")


def drain(cfg: AwsCloudtrailSqsConfig) -> dict[str, Any]:
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
                result = pipeline.ingest_payload(cfg.target_module, body, transport="queue")
                total_ingested += result.get("ingested", 0)
                to_delete.append(
                    {"Id": message["MessageId"], "ReceiptHandle": message["ReceiptHandle"]}
                )
            except Exception:
                # leave the message on the queue for redelivery / DLQ
                continue

        if to_delete:
            sqs.delete_message_batch(QueueUrl=cfg.queue_url, Entries=to_delete)

    return {"ingested": total_ingested, "messages": total_messages}
