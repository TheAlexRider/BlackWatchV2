# BlackWatch ECS probe — per-VPC setup (PowerShell, Windows-safe).
# Builds the agent image, pushes to ECR, creates the IAM role, registers the
# task definition, and outputs everything you need to actually run the service.
# Idempotent. Run once per VPC.
#
#   $env:VPC = "dev"
#   $env:VPC_REGION = "us-west-1"
#   $env:BLACKWATCH_URL = "https://blackwatch.example.com"
#   $env:BLACKWATCH_TOKEN = "<token from BLACKWATCH_PROBE_VPCS for this VPC>"
#   $env:SUBNET_IDS = "subnet-aaa,subnet-bbb"      # private subnets in the VPC
#   $env:SECURITY_GROUP_IDS = "sg-xxx"             # SG that can reach intra-VPC + outbound 443
#   $env:CLUSTER = "dev-cluster"                   # ECS cluster to deploy the probe into
#   .\setup.ps1

$VPC          = if ($env:VPC) { $env:VPC } else { Write-Host "ERROR: set VPC=dev|prod|..." -ForegroundColor Red; return }
$REGION       = if ($env:VPC_REGION) { $env:VPC_REGION } else { "us-west-1" }
$BW_URL       = if ($env:BLACKWATCH_URL) { $env:BLACKWATCH_URL } else { Write-Host "ERROR: set BLACKWATCH_URL" -ForegroundColor Red; return }
$BW_TOKEN     = if ($env:BLACKWATCH_TOKEN) { $env:BLACKWATCH_TOKEN } else { Write-Host "ERROR: set BLACKWATCH_TOKEN" -ForegroundColor Red; return }
$SUBNETS      = if ($env:SUBNET_IDS) { $env:SUBNET_IDS } else { Write-Host "ERROR: set SUBNET_IDS" -ForegroundColor Red; return }
$SGS          = if ($env:SECURITY_GROUP_IDS) { $env:SECURITY_GROUP_IDS } else { Write-Host "ERROR: set SECURITY_GROUP_IDS" -ForegroundColor Red; return }
$CLUSTER      = if ($env:CLUSTER) { $env:CLUSTER } else { Write-Host "ERROR: set CLUSTER" -ForegroundColor Red; return }
$HERE         = $PSScriptRoot

$REPO_NAME    = "blackwatch-ecs-probe"
$TASK_FAMILY  = "blackwatch-ecs-probe-$VPC"
$SVC_NAME     = "blackwatch-ecs-probe-$VPC"
$EXEC_ROLE    = "blackwatch-ecs-probe-exec"
$TASK_ROLE    = "blackwatch-ecs-probe-task"
$POLICY_NAME  = "blackwatch-ecs-probe"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Write-Host "ERROR: AWS CLI not found." -ForegroundColor Red; return }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "ERROR: docker not found." -ForegroundColor Red; return }
$ACCT = aws sts get-caller-identity --query Account --output text
Write-Host "Account=$ACCT Region=$REGION VPC=$VPC Cluster=$CLUSTER"

# 1. ECR repo (idempotent)
aws ecr describe-repositories --repository-names $REPO_NAME --region $REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $REPO_NAME --region $REGION | Out-Null
}
$IMAGE_URI = "${ACCT}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:latest"
Write-Host "Image: $IMAGE_URI"

# 2. Build + push (copies the script next to the Dockerfile first)
$BUILD = Join-Path $env:TEMP "bw-ecs-probe-build"
if (Test-Path $BUILD) { Remove-Item -Recurse -Force $BUILD }
New-Item -ItemType Directory -Path $BUILD | Out-Null
Copy-Item (Join-Path $HERE "Dockerfile") (Join-Path $BUILD "Dockerfile")
Copy-Item (Join-Path $HERE "..\..\scripts\ecs_probe.py") (Join-Path $BUILD "ecs_probe.py")
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "${ACCT}.dkr.ecr.${REGION}.amazonaws.com"
docker build -t $REPO_NAME $BUILD
docker tag "$($REPO_NAME):latest" $IMAGE_URI
docker push $IMAGE_URI

# 3. IAM roles (task role for the probe + exec role for pulling the image)
$trust = Get-Content (Join-Path $HERE "trust-policy.json") -Raw
$trustPath = Join-Path $env:TEMP "bw-ecs-trust.json"
$trust | Out-File -FilePath $trustPath -Encoding ascii
aws iam create-role --role-name $TASK_ROLE --assume-role-policy-document "file://$trustPath" 2>$null | Out-Null
aws iam create-role --role-name $EXEC_ROLE --assume-role-policy-document "file://$trustPath" 2>$null | Out-Null
aws iam attach-role-policy --role-name $EXEC_ROLE --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" 2>$null | Out-Null

$polDoc = Get-Content (Join-Path $HERE "blackwatch-ecs-probe-policy.json") -Raw
$polPath = Join-Path $env:TEMP "bw-ecs-policy.json"
$polDoc | Out-File -FilePath $polPath -Encoding ascii
$POL_ARN = aws iam create-policy --policy-name $POLICY_NAME --policy-document "file://$polPath" --query "Policy.Arn" --output text 2>$null
if (-not $POL_ARN) { $POL_ARN = "arn:aws:iam::${ACCT}:policy/$POLICY_NAME" }
aws iam attach-role-policy --role-name $TASK_ROLE --policy-arn $POL_ARN | Out-Null
$TASK_ROLE_ARN = "arn:aws:iam::${ACCT}:role/${TASK_ROLE}"
$EXEC_ROLE_ARN = "arn:aws:iam::${ACCT}:role/${EXEC_ROLE}"

# 4. CloudWatch log group
$LOG_GROUP = "/blackwatch/ecs-probe/$VPC"
aws logs create-log-group --log-group-name $LOG_GROUP --region $REGION 2>$null | Out-Null

# 5. Register task definition
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
      @{name = "BLACKWATCH_URL"; value = $BW_URL},
      @{name = "BLACKWATCH_TOKEN"; value = $BW_TOKEN},
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

# 6. Create or update the ECS service (desired count 1)
$existing = aws ecs describe-services --cluster $CLUSTER --services $SVC_NAME --region $REGION --query "services[?status!='INACTIVE'].serviceName" --output text 2>$null
if ($existing) {
    aws ecs update-service --cluster $CLUSTER --service $SVC_NAME --task-definition $TASK_DEF_ARN --desired-count 1 --region $REGION | Out-Null
    Write-Host "Service updated."
} else {
    $netCfg = "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=DISABLED}"
    aws ecs create-service --cluster $CLUSTER --service-name $SVC_NAME --task-definition $TASK_DEF_ARN `
        --desired-count 1 --launch-type FARGATE --network-configuration $netCfg --region $REGION | Out-Null
    Write-Host "Service created."
}

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "  VPC label : $VPC"
Write-Host "  Cluster   : $CLUSTER"
Write-Host "  Service   : $SVC_NAME"
Write-Host "  Logs      : aws logs tail $LOG_GROUP --follow --region $REGION"
Write-Host ""
Write-Host "On BlackWatch (Lightsail) make sure these env vars are set:"
Write-Host "  BLACKWATCH_TOKENS=$BW_TOKEN:ecs.probe[,other-tokens...]"
Write-Host "  BLACKWATCH_PROBE_VPCS=$BW_TOKEN:$VPC[,other-tokens...]"
