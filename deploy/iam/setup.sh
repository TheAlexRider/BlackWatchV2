#!/usr/bin/env bash
# One-time AWS setup for the BlackWatch IAM/CloudTrail module.
# Creates: SQS queue (+DLQ), a forwarder Lambda, an EventBridge rule, and a
# least-privilege IAM user for BlackWatch to read the queue.
#
# Run with admin-ish AWS creds (this CREATES infra). Review before running.
# Prereqs: awscli v2, a CloudTrail trail already logging management events.
#
#   REGION=us-east-1 bash deploy/iam/setup.sh
#
set -euo pipefail

REGION="${REGION:-us-east-1}"
QUEUE_NAME="blackwatch-cloudtrail"
DLQ_NAME="blackwatch-cloudtrail-dlq"
LAMBDA_NAME="blackwatch-cloudtrail-forwarder"
RULE_NAME="blackwatch-cloudtrail-rule"
ROLE_NAME="blackwatch-forwarder-role"
BW_USER="blackwatch-sqs-reader"
HERE="$(cd "$(dirname "$0")" && pwd)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "Account=$ACCOUNT_ID Region=$REGION"

# 1) DLQ + main queue (with redrive after 5 receives)
DLQ_URL="$(aws sqs create-queue --queue-name "$DLQ_NAME" --region "$REGION" --query QueueUrl --output text)"
DLQ_ARN="$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn --region "$REGION" --query 'Attributes.QueueArn' --output text)"
REDRIVE="{\"deadLetterTargetArn\":\"$DLQ_ARN\",\"maxReceiveCount\":\"5\"}"
QUEUE_URL="$(aws sqs create-queue --queue-name "$QUEUE_NAME" --region "$REGION" \
  --attributes "{\"MessageRetentionPeriod\":\"86400\",\"RedrivePolicy\":\"$(echo "$REDRIVE" | sed 's/"/\\"/g')\"}" \
  --query QueueUrl --output text)"
QUEUE_ARN="$(aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --region "$REGION" --query 'Attributes.QueueArn' --output text)"
echo "QUEUE_URL=$QUEUE_URL"

# 2) Lambda role (logs + send to the queue)
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
ROLE_ARN="$(aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST" --query 'Role.Arn' --output text 2>/dev/null || aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name send-to-queue \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sqs:SendMessage\",\"Resource\":\"$QUEUE_ARN\"}]}"
sleep 10  # let the role propagate

# 3) Lambda
( cd "$HERE" && zip -q -j /tmp/bw_forwarder.zip lambda_forwarder.py )
aws lambda create-function --function-name "$LAMBDA_NAME" --runtime python3.12 \
  --handler lambda_forwarder.handler --role "$ROLE_ARN" --timeout 15 \
  --environment "Variables={QUEUE_URL=$QUEUE_URL}" \
  --zip-file fileb:///tmp/bw_forwarder.zip --region "$REGION" 2>/dev/null \
  || aws lambda update-function-code --function-name "$LAMBDA_NAME" --zip-file fileb:///tmp/bw_forwarder.zip --region "$REGION"
LAMBDA_ARN="$(aws lambda get-function --function-name "$LAMBDA_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)"

# 4) EventBridge rule -> Lambda
aws events put-rule --name "$RULE_NAME" --region "$REGION" \
  --event-pattern "file://$HERE/eventbridge-pattern.json"
aws lambda add-permission --function-name "$LAMBDA_NAME" --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$REGION:$ACCOUNT_ID:rule/$RULE_NAME" --region "$REGION" 2>/dev/null || true
aws events put-targets --rule "$RULE_NAME" --region "$REGION" \
  --targets "Id=1,Arn=$LAMBDA_ARN"

# 5) Least-privilege reader user for BlackWatch
aws iam create-user --user-name "$BW_USER" 2>/dev/null || true
POLICY="$(sed "s/REGION/$REGION/; s/ACCOUNT_ID/$ACCOUNT_ID/" "$HERE/blackwatch-sqs-read-policy.json")"
aws iam put-user-policy --user-name "$BW_USER" --policy-name read-cloudtrail-queue --policy-document "$POLICY"
echo "Creating access key for $BW_USER ..."
aws iam create-access-key --user-name "$BW_USER" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text

echo
echo "DONE. Put the access key above into an AWS profile named 'blackwatch', then in BlackWatch:"
echo "  Settings -> Add AWS CloudTrail (SQS) connector"
echo "  Queue URL: $QUEUE_URL"
echo "  Region:    $REGION"
echo "  Profile:   blackwatch"
