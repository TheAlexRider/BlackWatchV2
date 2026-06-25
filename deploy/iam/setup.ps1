# BlackWatch IAM/CloudTrail AWS setup (PowerShell, Windows-safe).
# Creates: SQS queue (+DLQ), forwarder Lambda, EventBridge rule, least-priv reader user.
# Idempotent — safe to re-run. Run with admin-ish AWS creds.
# Prereqs: AWS CLI v2 (`aws configure` done), a CloudTrail trail logging management events.
#
#   $env:REGION = "us-east-1"; .\setup.ps1
#
# NOTE: we deliberately do NOT set $ErrorActionPreference='Stop' — in Windows
# PowerShell, AWS CLI writing to stderr would otherwise abort the script even on
# success. Expected "already exists" messages may print in red on re-runs; they
# are harmless. What matters is the final DONE block.

$REGION      = if ($env:REGION) { $env:REGION } else { "us-east-1" }
$QUEUE_NAME  = "blackwatch-cloudtrail"
$DLQ_NAME    = "blackwatch-cloudtrail-dlq"
$LAMBDA_NAME = "blackwatch-cloudtrail-forwarder"
$RULE_NAME   = "blackwatch-cloudtrail-rule"
$ROLE_NAME   = "blackwatch-forwarder-role"
$BW_USER     = "blackwatch-sqs-reader"
$HERE        = $PSScriptRoot

function Write-Json($obj, $path) {
    ($obj | ConvertTo-Json -Compress -Depth 10) | Out-File -FilePath $path -Encoding ascii
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: AWS CLI not found. Install it and run 'aws configure' first." -ForegroundColor Red
    return
}
$ACCOUNT_ID = aws sts get-caller-identity --query Account --output text
if (-not $ACCOUNT_ID) { Write-Host "ERROR: not authenticated to AWS." -ForegroundColor Red; return }
Write-Host "Account=$ACCOUNT_ID Region=$REGION"

# --- 1) DLQ + main queue -----------------------------------------------------
Write-Host "Setting up SQS queues..."
$DLQ_URL = aws sqs create-queue --queue-name $DLQ_NAME --region $REGION --query QueueUrl --output text
$DLQ_ARN = aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
$redrive = (@{ deadLetterTargetArn = $DLQ_ARN; maxReceiveCount = "5" } | ConvertTo-Json -Compress)
$attrsPath = Join-Path $env:TEMP "bw_queue_attrs.json"
Write-Json @{ MessageRetentionPeriod = "86400"; RedrivePolicy = $redrive } $attrsPath
$QUEUE_URL = aws sqs create-queue --queue-name $QUEUE_NAME --region $REGION --attributes "file://$attrsPath" --query QueueUrl --output text
$QUEUE_ARN = aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
Write-Host "QUEUE_URL=$QUEUE_URL"

# --- 2) Lambda role (get-or-create) -----------------------------------------
Write-Host "Setting up Lambda role..."
$trustPath = Join-Path $env:TEMP "bw_trust.json"
Write-Json @{ Version = "2012-10-17"; Statement = @(@{ Effect = "Allow"; Principal = @{ Service = "lambda.amazonaws.com" }; Action = "sts:AssumeRole" }) } $trustPath
$ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query "Role.Arn" --output text 2>$null
if (-not $ROLE_ARN) {
    aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document "file://$trustPath" | Out-Null
    Start-Sleep -Seconds 8
    $ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query "Role.Arn" --output text
}
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole | Out-Null
$sendPath = Join-Path $env:TEMP "bw_send.json"
Write-Json @{ Version = "2012-10-17"; Statement = @(@{ Effect = "Allow"; Action = "sqs:SendMessage"; Resource = $QUEUE_ARN }) } $sendPath
aws iam put-role-policy --role-name $ROLE_NAME --policy-name send-to-queue --policy-document "file://$sendPath" | Out-Null
Start-Sleep -Seconds 5

# --- 3) Lambda (create-or-update) -------------------------------------------
Write-Host "Deploying Lambda..."
$zip = Join-Path $env:TEMP "bw_forwarder.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $HERE "lambda_forwarder.py") -DestinationPath $zip -Force
$LAMBDA_ARN = aws lambda get-function --function-name $LAMBDA_NAME --region $REGION --query "Configuration.FunctionArn" --output text 2>$null
if (-not $LAMBDA_ARN) {
    aws lambda create-function --function-name $LAMBDA_NAME --runtime python3.12 `
        --handler lambda_forwarder.handler --role $ROLE_ARN --timeout 15 `
        --environment "Variables={QUEUE_URL=$QUEUE_URL}" `
        --zip-file "fileb://$zip" --region $REGION | Out-Null
} else {
    aws lambda update-function-code --function-name $LAMBDA_NAME --zip-file "fileb://$zip" --region $REGION | Out-Null
}
Start-Sleep -Seconds 3
$LAMBDA_ARN = aws lambda get-function --function-name $LAMBDA_NAME --region $REGION --query "Configuration.FunctionArn" --output text

# --- 4) EventBridge rule -> Lambda ------------------------------------------
Write-Host "Wiring EventBridge..."
aws events put-rule --name $RULE_NAME --region $REGION --event-pattern "file://$HERE/eventbridge-pattern.json" | Out-Null
aws lambda add-permission --function-name $LAMBDA_NAME --statement-id eventbridge-invoke `
    --action lambda:InvokeFunction --principal events.amazonaws.com `
    --source-arn "arn:aws:events:$($REGION):$($ACCOUNT_ID):rule/$RULE_NAME" --region $REGION 2>$null | Out-Null
aws events put-targets --rule $RULE_NAME --region $REGION --targets "Id=1,Arn=$LAMBDA_ARN" | Out-Null

# --- 5) least-privilege reader user -----------------------------------------
Write-Host "Setting up reader user..."
$null = aws iam get-user --user-name $BW_USER 2>$null
if ($LASTEXITCODE -ne 0) { aws iam create-user --user-name $BW_USER | Out-Null }
$policy = (Get-Content (Join-Path $HERE "blackwatch-sqs-read-policy.json") -Raw) -replace "REGION", $REGION -replace "ACCOUNT_ID", $ACCOUNT_ID
$polPath = Join-Path $env:TEMP "bw_read_policy.json"
$policy | Out-File -FilePath $polPath -Encoding ascii
aws iam put-user-policy --user-name $BW_USER --policy-name read-cloudtrail-queue --policy-document "file://$polPath" | Out-Null
Start-Sleep -Seconds 3
$attachedResource = aws iam get-user-policy --user-name $BW_USER --policy-name read-cloudtrail-queue --query "PolicyDocument.Statement[0].Resource" --output text 2>$null
if ($attachedResource) {
    Write-Host "Read policy attached -> $attachedResource" -ForegroundColor Green
} else {
    Write-Host "WARNING: read policy did NOT attach. Retrying..." -ForegroundColor Red
    aws iam put-user-policy --user-name $BW_USER --policy-name read-cloudtrail-queue --policy-document "file://$polPath"
}

# Remove any existing access keys for this dedicated user so re-runs always end
# with exactly one key (IAM allows max 2). This user is only used by BlackWatch.
$existing = aws iam list-access-keys --user-name $BW_USER --query "AccessKeyMetadata[].AccessKeyId" --output text 2>$null
if ($existing) {
    foreach ($k in ($existing -split "\s+")) {
        if ($k) { aws iam delete-access-key --user-name $BW_USER --access-key-id $k | Out-Null }
    }
}

Write-Host ""
Write-Host "Access key for $BW_USER (save as AWS profile 'blackwatch'):" -ForegroundColor Yellow
aws iam create-access-key --user-name $BW_USER --query "AccessKey.[AccessKeyId,SecretAccessKey]" --output text

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "  Queue URL: $QUEUE_URL"
Write-Host "  Region:    $REGION"
Write-Host "  Profile:   blackwatch"
