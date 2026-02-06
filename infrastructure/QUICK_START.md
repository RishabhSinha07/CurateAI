# CurateAI AWS Deployment - Quick Start

Ultra-fast deployment guide for Phase 1.

## Prerequisites (5 minutes)

```bash
# 1. Install CDK CLI
npm install -g aws-cdk

# 2. Verify installations
aws --version      # AWS CLI v2
cdk --version      # CDK CLI
docker --version   # Docker
python3 --version  # Python 3.11+

# 3. Configure AWS
aws configure
```

## Deployment (30 minutes)

### Step 1: Environment Setup

```bash
# Set required variables
export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="us-east-1"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"
export GITHUB_BRANCH="main"
export ALARM_EMAIL="admin@noeticex.com"  # Optional (defaults to this if not set)

# Note: No AWS access keys needed! ECS Task uses IAM Role for Bedrock permissions
```

### Step 2: Create GitHub Connection

```bash
# Create CodeStar connection
aws codestar-connections create-connection \
  --provider-type GitHub \
  --connection-name curateai-github \
  --region us-east-1

# Copy the ConnectionArn from output
export CODESTAR_CONNECTION_ARN="<your-connection-arn>"

# IMPORTANT: Go to AWS Console and authorize the connection
# https://console.aws.amazon.com/codesuite/settings/connections
```

### Step 3: Bootstrap and Deploy

```bash
# Navigate to infrastructure directory
cd infrastructure

# Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Bootstrap CDK (first time only)
cdk bootstrap aws://558599919081/us-east-1

# Deploy all stacks
cdk deploy --all
# Type 'y' to confirm each stack
```

### Step 4: Build and Push Docker Image

```bash
# Return to project root
cd ..

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 558599919081.dkr.ecr.us-east-1.amazonaws.com

# Build production image
docker build -f Dockerfile.prod -t curateai-app:latest .

# Tag and push
docker tag curateai-app:latest 558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest
docker push 558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest
```

### Step 5: Get Task Public IP

```bash
# Get running task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster CurateAI-Cluster \
  --service-name CurateAI-Service \
  --query 'taskArns[0]' \
  --output text)

# Get ENI ID
ENI_ID=$(aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

# Get public IP
PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI_ID \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

echo "Task Public IP: $PUBLIC_IP"
```

### Step 6: Test Application

```bash
# Test health endpoint
curl http://$PUBLIC_IP:8000/health

# Expected output: {"status":"healthy"}

# Test chat endpoint
curl -X POST http://$PUBLIC_IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}'
```

## Verify Deployment

```bash
# Check ECS service status
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service \
  --query 'services[0].[serviceName,status,desiredCount,runningCount]' \
  --output table

# View logs
aws logs tail /ecs/curateai-app --follow

# Check CloudWatch dashboard
echo "Dashboard: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=CurateAI-Production"
```

## Common Issues

### Task Not Starting

```bash
# Check task stopped reason
aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $(aws ecs list-tasks --cluster CurateAI-Cluster --query 'taskArns[0]' --output text) \
  --query 'tasks[0].stoppedReason'
```

### Pipeline Failing

```bash
# Check pipeline status
aws codepipeline get-pipeline-state --name CurateAI-Pipeline

# View build logs
aws codebuild list-builds-for-project --project-name CurateAI-Build
```

### No Public IP

```bash
# Ensure service is configured for public IP
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service \
  --query 'services[0].networkConfiguration.awsvpcConfiguration.assignPublicIp'
```

## Update Application

```bash
# Make code changes
# Commit and push to GitHub
git add .
git commit -m "Your changes"
git push origin main

# Pipeline automatically:
# 1. Builds new Docker image
# 2. Pushes to ECR
# 3. Deploys to ECS
```

## Rollback

```bash
# Rollback to previous task definition revision
aws ecs update-service \
  --cluster CurateAI-Cluster \
  --service CurateAI-Service \
  --task-definition curateai-task:1  # Change revision number
```

## Clean Up

```bash
# Destroy all resources (in reverse order)
cd infrastructure
cdk destroy CurateAI-Observability
cdk destroy CurateAI-Pipeline
cdk destroy CurateAI-ECS
cdk destroy CurateAI-Network
```

## Cost Monitoring

```bash
# View current month costs
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-02-05 \
  --granularity DAILY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --output table
```

## Useful Links

- **ECS Console**: https://console.aws.amazon.com/ecs/v2/clusters/CurateAI-Cluster
- **ECR Console**: https://console.aws.amazon.com/ecr/repositories/curateai-app
- **Pipeline Console**: https://console.aws.amazon.com/codesuite/codepipeline/pipelines/CurateAI-Pipeline
- **CloudWatch Logs**: https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fecs$252Fcurateai-app

## Environment Variables Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `CDK_DEFAULT_ACCOUNT` | AWS account ID (558599919081) | Yes |
| `CDK_DEFAULT_REGION` | AWS region (us-east-1) | Yes |
| `GITHUB_OWNER` | GitHub username (RishabhSinha07) | Yes |
| `GITHUB_REPO` | GitHub repository name (CurateAI) | Yes |
| `GITHUB_BRANCH` | Git branch (main) | Yes |
| `CODESTAR_CONNECTION_ARN` | CodeStar connection ARN | Optional |
| `ALARM_EMAIL` | Email for alarms (admin@noeticex.com) | Optional |

**Note**: No AWS access keys needed! The ECS Task uses an IAM Role for Bedrock permissions (more secure than access keys).

## Cost Estimate

- **Fargate Spot**: $9-12/month
- **VPC Endpoints**: $7/month
- **ECR**: $0.20/month
- **CloudWatch**: $1-2/month
- **CodePipeline**: $0-1/month
- **Bedrock**: $2-5/month (usage-based)

**Total**: ~$20-30/month

## Next Steps

After Phase 1 deployment:
1. Monitor application health via CloudWatch dashboard
2. Test CI/CD pipeline by pushing code changes
3. Proceed to Phase 2 (Database Setup) when ready

For detailed documentation, see:
- `infrastructure/README.md` - Full deployment guide
- `infrastructure/DEPLOYMENT_CHECKLIST.md` - Step-by-step checklist
- `PHASE_1_DEPLOYMENT_SUMMARY.md` - Implementation summary
