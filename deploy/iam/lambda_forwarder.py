"""BlackWatch CloudTrail forwarder (AWS Lambda).

Dumb forwarder: EventBridge invokes this with a matched CloudTrail event; it
puts the event on the SQS queue verbatim. No parsing/decisions here — BlackWatch's
aws.cloudtrail adapter does that. Set env var QUEUE_URL to your queue.
"""

import json
import os

import boto3

_sqs = boto3.client("sqs")
_QUEUE_URL = os.environ["QUEUE_URL"]


def handler(event, context):
    _sqs.send_message(QueueUrl=_QUEUE_URL, MessageBody=json.dumps(event))
    return {"forwarded": True}
