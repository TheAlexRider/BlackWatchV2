# BlackWatch RDS log-forwarder setup (PowerShell, Windows-safe).
#
# Creates:
#   * SQS queue + DLQ                 bw-rds-logs / bw-rds-logs-dlq
#   * Lambda role                     bw-rds-forwarder-role
#   * Lambda function                 bw-rds-forwarder
#   * CloudWatch Logs subscription    one per RDS log group in $LOG_GROUPS
#   * IAM policy for BW reader        bw-read-rds-queue (attached to blackwatch-sqs-reader)
#
# Auth model:
#   * Forwarder Lambda -> SQS via its own role (sqs:SendMessage)
#   * BW (Lightsail)   -> SQS via existing blackwatch-sqs-reader user
#
# Env vars (set before running):
#   $env:REGION      = "us-west-1"                              # AWS region
#   $env:LOG_GROUPS  = "/aws/rds/instance/prod-database-healthlake/postgresql,/aws/rds/proxy/proxy-1768332114756-prod-database-healthlake"
#
# Idempotent. Safe to re-run whenever you add a new DB.

$REGION       = if ($env:REGION) { $env:REGION } else { "us-west-1" }
$LOG_GROUPS   = if ($env:LOG_GROUPS) { $env:LOG_GROUPS } else { Write-Host "ERROR: set LOG_GROUPS=..." -ForegroundColor Red; return }
$HERE         = $PSScriptRoot

$QUEUE_NAME   = "bw-rds-logs"
$DLQ_NAME     = "bw-rds-logs-dlq"
$LAMBDA_NAME  = "bw-rds-forwarder"
$ROLE_NAME    = "bw-rds-forwarder-role"
$BW_USER      = "blackwatch-sqs-reader"
$READ_POLICY  = "bw-read-rds-queue"

function Write-Json($obj, $path) {
    ($obj | ConvertTo-Json -Compress -Depth 10) | Out-File -FilePath $path -Encoding ascii
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: AWS CLI not found." -ForegroundColor Red; return
}
$ACCT = aws sts get-caller-identity --query Account --output text
if (-not $ACCT) { Write-Host "ERROR: not authenticated to AWS." -ForegroundColor Red; return }
Write-Host "Account=$ACCT Region=$REGION"

# --- 1) DLQ + main queue ---------------------------------------------------
Write-Host "Setting up SQS queues..."
$DLQ_URL = aws sqs create-queue --queue-name $DLQ_NAME --region $REGION --query QueueUrl --output text
$DLQ_ARN = aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
$redrive = (@{ deadLetterTargetArn = $DLQ_ARN; maxReceiveCount = "5" } | ConvertTo-Json -Compress)
$attrsPath = Join-Path $env:TEMP "bw_rds_queue_attrs.json"
Write-Json @{ MessageRetentionPeriod = "86400"; RedrivePolicy = $redrive; SqsManagedSseEnabled = "true" } $attrsPath
$QUEUE_URL = aws sqs create-queue --queue-name $QUEUE_NAME --region $REGION --attributes "file://$attrsPath" --query QueueUrl --output text
if ($LASTEXITCODE -ne 0 -or -not $QUEUE_URL) {
    Write-Host "ERROR: create-queue failed. Stopping." -ForegroundColor Red; return
}
$QUEUE_ARN = aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
Write-Host "QUEUE_URL=$QUEUE_URL"

# --- 2) Lambda role --------------------------------------------------------
Write-Host "Setting up Lambda role..."
$trustPath = Join-Path $env:TEMP "bw_rds_trust.json"
Write-Json @{ Version = "2012-10-17"; Statement = @(@{ Effect = "Allow"; Principal = @{ Service = "lambda.amazonaws.com" }; Action = "sts:AssumeRole" }) } $trustPath
$ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query "Role.Arn" --output text 2>$null
if (-not $ROLE_ARN) {
    aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document "file://$trustPath" | Out-Null
    Start-Sleep -Seconds 8
    $ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query "Role.Arn" --output text
}
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole | Out-Null

$sendPath = Join-Path $env:TEMP "bw_rds_send.json"
Write-Json @{ Version = "2012-10-17"; Statement = @(@{ Effect = "Allow"; Action = "sqs:SendMessage"; Resource = $QUEUE_ARN }) } $sendPath
aws iam put-role-policy --role-name $ROLE_NAME --policy-name "send-to-rds-queue" --policy-document "file://$sendPath" | Out-Null
Start-Sleep -Seconds 5

# --- 3) Lambda (create or update) -----------------------------------------
Write-Host "Deploying Lambda..."
$zip = Join-Path $env:TEMP "bw_rds_forwarder.zip"
if (Test-Path $zip) { Remove-Item $zip }
# Zip contains just the source file; boto3 is provided by the Lambda runtime.
$stagingDir = Join-Path $env:TEMP "bw_rds_forwarder_src"
if (Test-Path $stagingDir) { Remove-Item -Recurse -Force $stagingDir }
New-Item -ItemType Directory -Path $stagingDir | Out-Null
Copy-Item (Join-Path $HERE "bw_log_forwarder.py") (Join-Path $stagingDir "bw_log_forwarder.py")
Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zip -Force

$exists = aws lambda get-function --function-name $LAMBDA_NAME --region $REGION 2>$null | Out-String
if ([string]::IsNullOrEmpty($exists)) {
    aws lambda create-function --function-name $LAMBDA_NAME --runtime python3.12 --role $ROLE_ARN `
        --handler bw_log_forwarder.handler --zip-file "fileb://$zip" `
        --environment "Variables={QUEUE_URL=$QUEUE_URL}" `
        --timeout 30 --memory-size 128 --region $REGION | Out-Null
    Start-Sleep -Seconds 5
} else {
    aws lambda update-function-code --function-name $LAMBDA_NAME --zip-file "fileb://$zip" --region $REGION | Out-Null
    Start-Sleep -Seconds 3
    aws lambda update-function-configuration --function-name $LAMBDA_NAME `
        --environment "Variables={QUEUE_URL=$QUEUE_URL}" --region $REGION | Out-Null
}
$LAMBDA_ARN = aws lambda get-function --function-name $LAMBDA_NAME --region $REGION --query "Configuration.FunctionArn" --output text
Write-Host "LAMBDA_ARN=$LAMBDA_ARN"

# --- 4) Subscription filters (one per log group) --------------------------
Write-Host "Wiring subscription filters..."
$groups = $LOG_GROUPS -split ","
foreach ($lg in $groups) {
    $lg = $lg.Trim()
    if (-not $lg) { continue }
    # Grant CW Logs permission to invoke Lambda (idempotent -- one statement id per log group).
    $sid = "bw-cwlogs-" + ($lg -replace "[^A-Za-z0-9]", "-").Trim("-")
    aws lambda remove-permission --function-name $LAMBDA_NAME --statement-id $sid --region $REGION 2>$null | Out-Null
    aws lambda add-permission --function-name $LAMBDA_NAME --statement-id $sid `
        --action lambda:InvokeFunction --principal "logs.$REGION.amazonaws.com" `
        --source-arn "arn:aws:logs:${REGION}:${ACCT}:log-group:${lg}:*" --region $REGION | Out-Null

    # PowerShell strips bare "" when passing to native exes, so wrap it as
    # '""' — CLI receives a literal empty string (matches every log line).
    aws logs put-subscription-filter --log-group-name $lg --filter-name "bw-forwarder" `
        --filter-pattern '""' --destination-arn $LAMBDA_ARN --region $REGION
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  subscribed: $lg" -ForegroundColor Green
    } else {
        Write-Host "  FAILED to subscribe: $lg" -ForegroundColor Red
    }
}

# --- 5) BW reader user gets sqs:Receive+Delete on the queue ---------------
Write-Host "Granting BlackWatch reader user access..."
$readPath = Join-Path $env:TEMP "bw_rds_read.json"
Write-Json @{
    Version = "2012-10-17"; Statement = @(@{
        Effect = "Allow"
        Action = @("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:DeleteMessageBatch", "sqs:GetQueueAttributes")
        Resource = $QUEUE_ARN
    })
} $readPath
$existing = aws iam list-attached-user-policies --user-name $BW_USER --query "AttachedPolicies[?PolicyName=='$READ_POLICY'].PolicyArn" --output text 2>$null
if ($existing) {
    # Bump the version
    $polArn = $existing
    aws iam create-policy-version --policy-arn $polArn --policy-document "file://$readPath" --set-as-default | Out-Null
} else {
    $polArn = aws iam create-policy --policy-name $READ_POLICY --policy-document "file://$readPath" --query "Policy.Arn" --output text
    aws iam attach-user-policy --user-name $BW_USER --policy-arn $polArn | Out-Null
}

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "  Queue     : $QUEUE_URL"
Write-Host "  Queue ARN : $QUEUE_ARN"
Write-Host "  Lambda    : $LAMBDA_ARN"
Write-Host "  Subscribed to $($groups.Count) log group(s)."
Write-Host ""
Write-Host "NEXT -- register the connector on BlackWatch (Lightsail):" -ForegroundColor Yellow
Write-Host "  docker compose exec app python -c `"from blackwatch import db, storage; import uuid; db.init_pool(); storage.upsert_connector(str(uuid.uuid4()), 'RDS logs', 'aws_rds_sqs', {'queue_url': '$QUEUE_URL', 'aws_region': '$REGION', 'aws_profile': 'blackwatch', 'interval_seconds': 60, 'wait_seconds': 10, 'max_batches': 5})`""
Write-Host ""
Write-Host "Then in the BW UI: Connectors -> Test -> Enable."
