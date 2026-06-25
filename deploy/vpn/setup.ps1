# BlackWatch OpenVPN agent — AWS setup (PowerShell, Windows-safe).
# Creates: VPN agent SQS queue (+DLQ), a managed policy for the OpenVPN box's
# instance role (SendMessage), and extends the BlackWatch reader to poll it.
# Idempotent. Run with admin-ish AWS creds.
#
#   $env:REGION = "us-west-1"; .\setup.ps1
#
# (No $ErrorActionPreference='Stop' — AWS CLI stderr would abort it in PS.)

$REGION   = if ($env:REGION) { $env:REGION } else { "us-west-1" }
$QUEUE    = "blackwatch-vpn-agents"
$DLQ      = "blackwatch-vpn-agents-dlq"
$POLICY   = "blackwatch-vpn-agent-send"
$READER   = "blackwatch-sqs-reader"
$HERE     = $PSScriptRoot

function Write-Json($obj, $path) { ($obj | ConvertTo-Json -Compress -Depth 10) | Out-File -FilePath $path -Encoding ascii }

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Write-Host "ERROR: AWS CLI not found." -ForegroundColor Red; return }
$ACCT = aws sts get-caller-identity --query Account --output text
Write-Host "Account=$ACCT Region=$REGION"

# 1) DLQ + main VPN agent queue
$DLQ_URL = aws sqs create-queue --queue-name $DLQ --region $REGION --query QueueUrl --output text
$DLQ_ARN = aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
$redrive = (@{ deadLetterTargetArn = $DLQ_ARN; maxReceiveCount = "5" } | ConvertTo-Json -Compress)
$attrs = Join-Path $env:TEMP "bw_vpn_attrs.json"
Write-Json @{ MessageRetentionPeriod = "86400"; RedrivePolicy = $redrive } $attrs
$QUEUE_URL = aws sqs create-queue --queue-name $QUEUE --region $REGION --attributes "file://$attrs" --query QueueUrl --output text
$QUEUE_ARN = aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
Write-Host "QUEUE_URL=$QUEUE_URL"

# 2) Managed policy for the OpenVPN box's instance role (SendMessage to the queue)
$polDoc = (Get-Content (Join-Path $HERE "blackwatch-vpn-agent-send-policy.json") -Raw) -replace "REGION", $REGION -replace "ACCOUNT_ID", $ACCT
$polPath = Join-Path $env:TEMP "bw_vpn_send.json"
$polDoc | Out-File -FilePath $polPath -Encoding ascii
$POL_ARN = aws iam create-policy --policy-name $POLICY --policy-document "file://$polPath" --query "Policy.Arn" --output text 2>$null
if (-not $POL_ARN) {
    $POL_ARN = "arn:aws:iam::${ACCT}:policy/$POLICY"
    # create a new version if it already exists (keep it current)
    aws iam create-policy-version --policy-arn $POL_ARN --policy-document "file://$polPath" --set-as-default 2>$null | Out-Null
}
Write-Host "AGENT_POLICY_ARN=$POL_ARN"

# 3) Extend the BlackWatch reader to poll this queue too (inline policy, named
#    so it lives alongside the ec2 / cloudtrail reader policies without colliding)
$readDoc = @{ Version = "2012-10-17"; Statement = @(@{ Effect = "Allow";
    Action = @("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes");
    Resource = $QUEUE_ARN }) }
$readPath = Join-Path $env:TEMP "bw_vpn_read.json"
Write-Json $readDoc $readPath
aws iam put-user-policy --user-name $READER --policy-name read-vpn-agents-queue --policy-document "file://$readPath" | Out-Null
Write-Host "Reader policy attached for $READER -> $QUEUE_ARN" -ForegroundColor Green

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "  VPN queue URL : $QUEUE_URL"
Write-Host "  Region        : $REGION"
Write-Host "  Agent policy  : $POL_ARN   (attach to the OpenVPN box's instance role)"
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Attach $POL_ARN to the OpenVPN box's instance role (in addition to blackwatch-ec2-agent-send)."
Write-Host "  2. scp scripts/vpn_agent.py + deploy/vpn/install-vpn-agent.sh to the box, then:"
Write-Host "       sudo BLACKWATCH_VPN_SQS_URL=$QUEUE_URL AWS_REGION=$REGION bash install-vpn-agent.sh"
Write-Host "  3. BlackWatch Settings -> Add SQS connector: target module = vpn.openvpn, queue $QUEUE_URL, region $REGION, profile blackwatch."
Write-Host "  4. Test the connector, enable it, and /ui/vpn should populate within ~60s."
