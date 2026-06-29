"""SQS-backed CloudTrail collection. Receives the events an EventBridge->Lambda
forwarder placed on the queue, runs each through the ingest pipeline, and
deletes only the ones that ingested successfully (failures redeliver / land in
the queue's DLQ). boto3 is imported lazily so the app runs without it until an
AWS connector is actually used."""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import pipeline
from .models import AwsCloudtrailSqsConfig

_log = logging.getLogger(__name__)


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
            except Exception as exc:
                # leave the message on the queue for redelivery / DLQ — but
                # LOG the failure so silent-fail loops are visible. Includes
                # the action/eventName so you can tell what kind of payload
                # the adapter is choking on.
                hint = ""
                if isinstance(body, dict):
                    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
                    hint = f" action={detail.get('eventName') or detail.get('action') or '?'}"
                _log.exception(
                    "sqs.ingest_failed module=%s message_id=%s%s: %s",
                    cfg.target_module, message.get("MessageId"), hint, exc,
                )
                continue

        if to_delete:
            sqs.delete_message_batch(QueueUrl=cfg.queue_url, Entries=to_delete)

    return {"ingested": total_ingested, "messages": total_messages}
