# BlackWatch ECS probe — per-VPC setup (PowerShell, Windows-safe).
#
# Creates everything needed for ONE VPC's probe:
#   * SQS queue           bw-ecs-probe-reports-<vpc>   (SSE-SQS encryption)
#   * SSM parameter       /blackwatch/ecs-probe/<vpc>/targets  (empty list placeholder)
#   * Per-VPC task role   blackwatch-ecs-probe-task-<vpc>      (scoped to ONLY this VPC's queue + param)
#   * Shared exec role    blackwatch-ecs-probe-exec            (image pulls)
#   * Builds + pushes the agent image, registers a task def, creates the service.
# Idempotent. Run once per VPC.
#
# Auth model:
#   - Probe -> SQS + SSM via IAM (no bearer tokens, no IP allowlists)
#   - BlackWatch (Lightsail) -> SQS via the existing AWS profile it already
#     uses for the IAM-module CloudTrail queue (grant it sqs:ReceiveMessage on
#     this queue too -- see the printed snippet at the bottom).
#
# Required env:
#   $env:VPC = "dev"                          # short label this probe reports under
#   $env:VPC_REGION = "us-west-1"
#   $env:SUBNET_IDS = "subnet-aaa,subnet-bbb" # PUBLIC subnets (probe needs IGW egress to reach SQS+SSM)
#   $env:SECURITY_GROUP_IDS = "sg-xxx"        # SG that can reach intra-VPC + outbound 443
#   $env:CLUSTER = "dev-cluster"

$VPC      = if ($env:VPC) { $env:VPC } else { Write-Host "ERROR: set VPC=dev|prod|..." -ForegroundColor Red; return }
$REGION   = if ($env:VPC_REGION) { $env:VPC_REGION } else { "us-west-1" }
$SUBNETS  = if ($env:SUBNET_IDS) { $env:SUBNET_IDS } else { Write-Host "ERROR: set SUBNET_IDS" -ForegroundColor Red; return }
$SGS      = if ($env:SECURITY_GROUP_IDS) { $env:SECURITY_GROUP_IDS } else { Write-Host "ERROR: set SECURITY_GROUP_IDS" -ForegroundColor Red; return }
$CLUSTER  = if ($env:CLUSTER) { $env:CLUSTER } else { Write-Host "ERROR: set CLUSTER" -ForegroundColor Red; return }
$HERE     = $PSScriptRoot

$REPO_NAME    = "blackwatch-ecs-probe"
$QUEUE_NAME   = "bw-ecs-probe-reports-$VPC"
$SSM_PARAM    = "/blackwatch/ecs-probe/$VPC/targets"
$TASK_FAMILY  = "blackwatch-ecs-probe-$VPC"
$SVC_NAME     = "blackwatch-ecs-probe-$VPC"
$EXEC_ROLE    = "blackwatch-ecs-probe-exec"
$TASK_ROLE    = "blackwatch-ecs-probe-task-$VPC"
$POLICY_NAME  = "blackwatch-ecs-probe-$VPC"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Write-Host "ERROR: AWS CLI not found." -ForegroundColor Red; return }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "ERROR: docker not found." -ForegroundColor Red; return }
$ACCT = aws sts get-caller-identity --query Account --output text
Write-Host "Account=$ACCT Region=$REGION VPC=$VPC Cluster=$CLUSTER"

# 1. SQS queue (SSE-SQS, NOT KMS -- same rationale as the IAM module: KMS-encrypted
#    SQS blocks cross-account/region writes from EventBridge etc.)
#    Attributes go through a file because PowerShell mangles inline JSON
#    arguments to native exes (strips the quotes).
$QUEUE_URL = aws sqs get-queue-url --queue-name $QUEUE_NAME --region $REGION --query QueueUrl --output text 2>$null
if (-not $QUEUE_URL -or $QUEUE_URL -eq "None") {
    $attrPath = Join-Path $env:TEMP "bw-sqs-attrs.json"
    '{"SqsManagedSseEnabled":"true","MessageRetentionPeriod":"86400"}' | Out-File -FilePath $attrPath -Encoding ascii
    $QUEUE_URL = aws sqs create-queue --queue-name $QUEUE_NAME --region $REGION --attributes "file://$attrPath" --query QueueUrl --output text
    if ($LASTEXITCODE -ne 0 -or -not $QUEUE_URL) {
        Write-Host "ERROR: create-queue failed (see message above). Stopping." -ForegroundColor Red; return
    }
    Write-Host "Created queue: $QUEUE_URL" -ForegroundColor Green
} else {
    Write-Host "Queue exists: $QUEUE_URL"
}
$QUEUE_ARN = aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names QueueArn --region $REGION --query "Attributes.QueueArn" --output text
if ($LASTEXITCODE -ne 0 -or -not $QUEUE_ARN) {
    Write-Host "ERROR: could not resolve queue ARN. Stopping." -ForegroundColor Red; return
}

# 2. SSM parameter (placeholder -- discovery script overwrites it with the real targets)
aws ssm get-parameter --name $SSM_PARAM --region $REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws ssm put-parameter --name $SSM_PARAM --type String --value "[]" --region $REGION | Out-Null
    Write-Host "Created SSM param: $SSM_PARAM (empty placeholder)" -ForegroundColor Green
} else {
    Write-Host "SSM param exists: $SSM_PARAM"
}
$SSM_PARAM_ARN = "arn:aws:ssm:${REGION}:${ACCT}:parameter${SSM_PARAM}"

# 3. ECR repo (shared across VPCs -- one image, parameterized at runtime)
aws ecr describe-repositories --repository-names $REPO_NAME --region $REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $REPO_NAME --region $REGION | Out-Null
}
$IMAGE_URI = "${ACCT}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:latest"
Write-Host "Image: $IMAGE_URI"

# 4. Build + push (copies the script next to the Dockerfile first)
$BUILD = Join-Path $env:TEMP "bw-ecs-probe-build"
if (Test-Path $BUILD) { Remove-Item -Recurse -Force $BUILD }
New-Item -ItemType Directory -Path $BUILD | Out-Null
Copy-Item (Join-Path $HERE "Dockerfile") (Join-Path $BUILD "Dockerfile")
Copy-Item (Join-Path $HERE "..\..\scripts\ecs_probe.py") (Join-Path $BUILD "ecs_probe.py")
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "${ACCT}.dkr.ecr.${REGION}.amazonaws.com"
docker build -t $REPO_NAME $BUILD
docker tag "$($REPO_NAME):latest" $IMAGE_URI
docker push $IMAGE_URI

# 5. IAM roles
$trust = Get-Content (Join-Path $HERE "trust-policy.json") -Raw
$trustPath = Join-Path $env:TEMP "bw-ecs-trust.json"
$trust | Out-File -FilePath $trustPath -Encoding ascii
aws iam create-role --role-name $TASK_ROLE --assume-role-policy-document "file://$trustPath" 2>$null | Out-Null
aws iam create-role --role-name $EXEC_ROLE --assume-role-policy-document "file://$trustPath" 2>$null | Out-Null
aws iam attach-role-policy --role-name $EXEC_ROLE --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" 2>$null | Out-Null

# 5a. Per-VPC task policy -- scoped to ONLY this VPC's queue ARN + SSM param ARN.
$polTemplate = Get-Content (Join-Path $HERE "blackwatch-ecs-probe-policy.json") -Raw
$polDoc = $polTemplate.Replace("__QUEUE_ARN__", $QUEUE_ARN).Replace("__SSM_PARAM_ARN__", $SSM_PARAM_ARN)
$polPath = Join-Path $env:TEMP "bw-ecs-policy-$VPC.json"
$polDoc | Out-File -FilePath $polPath -Encoding ascii
$POL_ARN = "arn:aws:iam::${ACCT}:policy/$POLICY_NAME"
# Re-create the policy each run so ARN changes (e.g. new queue) propagate
# without manual cleanup. Detach + delete first, then re-create.
aws iam get-policy --policy-arn $POL_ARN 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    aws iam detach-role-policy --role-name $TASK_ROLE --policy-arn $POL_ARN 2>$null | Out-Null
    aws iam delete-policy --policy-arn $POL_ARN 2>$null | Out-Null
}
aws iam create-policy --policy-name $POLICY_NAME --policy-document "file://$polPath" | Out-Null
aws iam attach-role-policy --role-name $TASK_ROLE --policy-arn $POL_ARN | Out-Null
$TASK_ROLE_ARN = "arn:aws:iam::${ACCT}:role/${TASK_ROLE}"
$EXEC_ROLE_ARN = "arn:aws:iam::${ACCT}:role/${EXEC_ROLE}"

# 6. CloudWatch log group
$LOG_GROUP = "/blackwatch/ecs-probe/$VPC"
aws logs create-log-group --log-group-name $LOG_GROUP --region $REGION 2>$null | Out-Null

# 7. Register task definition
$taskDef = @{
  family = $TASK_FAMILY
  networkMode = "awsvpc"
  requiresCompatibilities = @("FARGATE")
  cpu = "256"
  memory = "512"
  executionRoleArn = $EXEC_ROLE_ARN
  taskRoleArn = $TASK_ROLE_ARN
  containerDefinitions = @(@{
    name = "probe"
    image = $IMAGE_URI
    essential = $true
    environment = @(
      @{name = "PROBE_VPC"; value = $VPC},
      @{name = "SQS_QUEUE_URL"; value = $QUEUE_URL},
      @{name = "SSM_PARAM_NAME"; value = $SSM_PARAM},
      @{name = "AWS_DEFAULT_REGION"; value = $REGION},
      @{name = "INTERVAL_SECONDS"; value = "60"},
      @{name = "AGENT_VERSION"; value = "1.0"}
    )
    logConfiguration = @{
      logDriver = "awslogs"
      options = @{
        "awslogs-group" = $LOG_GROUP
        "awslogs-region" = $REGION
        "awslogs-stream-prefix" = "probe"
      }
    }
  })
}
$tdPath = Join-Path $env:TEMP "bw-ecs-taskdef.json"
($taskDef | ConvertTo-Json -Depth 10) | Out-File -FilePath $tdPath -Encoding ascii
$TASK_DEF_ARN = aws ecs register-task-definition --cli-input-json "file://$tdPath" --region $REGION --query "taskDefinition.taskDefinitionArn" --output text
Write-Host "Task def: $TASK_DEF_ARN" -ForegroundColor Green

# 8. Create or update the ECS service.
#    assignPublicIp=ENABLED -- the probe needs IGW egress to reach sqs.* and ssm.*
#    regional endpoints. IAM is the auth boundary now (no IP allowlist required),
#    so an ephemeral public IP via IGW is the cheapest path. No NAT needed.
$existing = aws ecs describe-services --cluster $CLUSTER --services $SVC_NAME --region $REGION --query "services[?status!='INACTIVE'].serviceName" --output text 2>$null
$netCfg = "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=ENABLED}"
if ($existing) {
    aws ecs update-service --cluster $CLUSTER --service $SVC_NAME --task-definition $TASK_DEF_ARN --desired-count 1 --network-configuration $netCfg --force-new-deployment --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: update-service failed. Stopping." -ForegroundColor Red; return }
    Write-Host "Service updated."
} else {
    aws ecs create-service --cluster $CLUSTER --service-name $SVC_NAME --task-definition $TASK_DEF_ARN --desired-count 1 --launch-type FARGATE --network-configuration $netCfg --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: create-service failed. Service NOT deployed." -ForegroundColor Red; return }
    Write-Host "Service created."
}

Write-Host ""
Write-Host "DONE for $VPC." -ForegroundColor Green
Write-Host "  Cluster   : $CLUSTER"
Write-Host "  Service   : $SVC_NAME"
Write-Host "  Queue     : $QUEUE_URL"
Write-Host "  SSM param : $SSM_PARAM"
Write-Host "  Logs      : aws logs tail $LOG_GROUP --follow --region $REGION"
Write-Host ""
Write-Host "NEXT -- run discovery to populate the targets parameter:" -ForegroundColor Yellow
Write-Host "  python -m scripts.ecs_discover --cluster ${CLUSTER}:${VPC} --region $REGION --emit-ssm"
Write-Host ""
Write-Host "NEXT -- on the BlackWatch (Lightsail) side, register the connector ONCE:" -ForegroundColor Yellow
Write-Host "  docker compose exec app python -c `"from blackwatch import db, storage; import uuid; db.init_pool(); storage.upsert_connector(str(uuid.uuid4()), 'ECS probe reports ($VPC)', 'aws_ecs_probe_sqs', {'queue_url': '$QUEUE_URL', 'aws_region': '$REGION', 'aws_profile': 'blackwatch', 'vpc': '$VPC', 'interval_seconds': 60, 'wait_seconds': 10, 'max_batches': 5})`""
Write-Host ""
Write-Host "Then in the BW UI: enable + test the connector. Verify-on-test reads"
Write-Host "from the queue once; the scheduler then polls every interval_seconds."
Write-Host ""
Write-Host "Make sure the BlackWatch AWS profile has sqs:ReceiveMessage +"
Write-Host "sqs:DeleteMessage on this queue ARN:" -ForegroundColor Yellow
Write-Host "  $QUEUE_ARN"
