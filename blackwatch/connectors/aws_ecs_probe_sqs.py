"""SQS-backed ECS probe report drain.

One queue per VPC. The in-VPC probe agent writes `ecs_probe_report` payloads
with IAM auth; this connector polls the queue and feeds each one through the
shared ingest pipeline targeting the `ecs.probe` module.

The connector knows its own VPC label (`cfg.vpc`) and **overrides** the body's
`vpc` field before ingest. If the probe is ever compromised, an attacker who
manages to PutMessage on the queue still cannot forge reports for a different
VPC — the body's vpc is replaced with what the connector says the queue is
for. This pins authority to the queue-binding, not to the message body."""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import pipeline
from .models import AwsEcsProbeSqsConfig

_log = logging.getLogger(__name__)


def _client(cfg: AwsEcsProbeSqsConfig):
    import boto3  # lazy import — keeps the app runnable without boto3 installed

    session = boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region
    )
    return session.client("sqs")


def drain(cfg: AwsEcsProbeSqsConfig) -> dict[str, Any]:
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
            # Pin the VPC to the queue's identity, not the message contents.
            if isinstance(body, dict):
                body["vpc"] = cfg.vpc
            try:
                result = pipeline.ingest_payload("ecs.probe", body, transport="queue")
                total_ingested += result.get("ingested", 0)
                to_delete.append(
                    {"Id": message["MessageId"], "ReceiptHandle": message["ReceiptHandle"]}
                )
            except Exception as exc:
                _log.exception(
                    "ecs_probe_sqs.ingest_failed vpc=%s message_id=%s: %s",
                    cfg.vpc, message.get("MessageId"), exc,
                )
                continue

        if to_delete:
            sqs.delete_message_batch(QueueUrl=cfg.queue_url, Entries=to_delete)

    return {"ingested": total_ingested, "messages": total_messages}
