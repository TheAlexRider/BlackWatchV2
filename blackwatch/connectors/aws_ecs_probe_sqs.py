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

from .. import pipeline, storage
from .models import AwsEcsProbeSqsConfig

_log = logging.getLogger(__name__)


def _session(cfg: AwsEcsProbeSqsConfig):
    import boto3  # lazy import — keeps the app runnable without boto3 installed

    return boto3.session.Session(
        profile_name=cfg.aws_profile or None, region_name=cfg.aws_region
    )


def _sync_targets_from_ssm(cfg: AwsEcsProbeSqsConfig, session) -> None:
    """Mirror the per-VPC SSM targets parameter into the probe_targets table.

    The probe runs off the SSM list directly; BW stores a copy because the UI
    joins probe_targets WITH service_status, and because the projection reads
    each target's tags off probe_targets to route notifications correctly.
    Targets removed from SSM are disabled (not deleted) so their status row
    sticks around for forensic reads."""
    param_name = cfg.ssm_targets_param or f"/blackwatch/ecs-probe/{cfg.vpc}/targets"
    try:
        resp = session.client("ssm").get_parameter(Name=param_name)
        ssm_targets = json.loads(resp["Parameter"]["Value"])
        if not isinstance(ssm_targets, list):
            return
    except Exception as exc:
        _log.warning("ecs_probe_sqs.ssm_sync_failed vpc=%s param=%s: %s",
                     cfg.vpc, param_name, exc)
        return

    seen_ids: set[str] = set()
    for t in ssm_targets:
        tid = t.get("id")
        if not tid:
            continue
        seen_ids.add(tid)
        storage.upsert_probe_target(
            tid,
            name=t.get("name") or tid,
            vpc=cfg.vpc,                   # pin VPC to the connector, not the payload
            tier=t.get("tier") or "unknown",
            config=t.get("config") or {},
            severity_when_down=t.get("severity_when_down") or "medium",
            tags=t.get("tags") or {},
            enabled=True,
        )
    # Anything left in probe_targets for this VPC that SSM no longer lists:
    # mark disabled so it stops showing up as a live target but its history
    # remains queryable.
    for existing in storage.list_probe_targets(vpc=cfg.vpc):
        if existing["id"] not in seen_ids and existing.get("enabled"):
            storage.upsert_probe_target(
                existing["id"],
                name=existing["name"], vpc=existing["vpc"],
                tier=existing["tier"], config=existing.get("config") or {},
                severity_when_down=existing.get("severity_when_down") or "medium",
                tags=existing.get("tags") or {}, enabled=False,
            )


def drain(cfg: AwsEcsProbeSqsConfig) -> dict[str, Any]:
    session = _session(cfg)
    _sync_targets_from_ssm(cfg, session)
    sqs = session.client("sqs")
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
