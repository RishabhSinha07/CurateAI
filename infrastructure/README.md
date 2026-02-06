# CurateAI AWS Deployment - Phase 1

This directory contains AWS CDK infrastructure code for deploying CurateAI to AWS Fargate.

## Phase 1: Backend Infrastructure (No Database)

Phase 1 deploys the containerized FastAPI application with CI/CD using YAML-based knowledge graphs (no database connection).

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         AWS Cloud                            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │                    VPC (10.0.0.0/16)                │    │
│  │                                                      │    │
│  │  ┌──────────────┐         ┌──────────────┐         │    │
│  │  │ Public Subnet │         │ Public Subnet │         │    │
│  │  │   us-east-1a  │         │   us-east-1b  │         │    │
│  │  │               │         │               │         │    │
│  │  │  ┌─────────┐  │         │  ┌─────────┐  │         │    │
│  │  │  │ Fargate │  │         │  │ Fargate │  │         │    │
│  │  │  │  Task   │  │         │  │  Task   │  │         │    │
│  │  │  │ (Spot)  │  │         │  │ (backup)│  │         │    │
│  │  │  └────┬────┘  │         │  └────┬────┘  │         │    │
│  │  │       │       │         │       │       │         │    │
│  │  │    Public IP  │         │    Public IP  │         │    │
│  │  └───────┼───────┘         └───────┼───────┘         │    │
│  │          │                         │                 │    │
│  │  ┌───────┴─────────────────────────┴───────┐         │    │
│  │  │         VPC Endpoints (ECR, Logs)        │         │    │
│  │  └──────────────────────────────────────────┘         │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │                  ECS Cluster                        │    │
│  │  - Fargate Spot (70% cost savings)                 │    │
│  │  - 0.5 vCPU, 1GB RAM                                │    │
│  │  - 1 task minimum                                   │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │              CI/CD Pipeline                         │    │
│  │  GitHub → CodeBuild → ECR → ECS Deploy             │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         CloudWatch (Logs, Metrics, Alarms)          │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Cost Breakdown (Ultra-Optimized)

| Component | Configuration | Monthly Cost |
|-----------|--------------|--------------|
| **Fargate Spot** | 1 task, 0.5 vCPU, 1GB RAM | $9-12 |
| **VPC Endpoints** | ECR, Logs, Bedrock | $7 |
| **ECR** | Docker images | $0.20 |
| **CloudWatch Logs** | 3-day retention | $1-2 |
| **CodePipeline** | 1 pipeline | $0-1 |
| **Bedrock** | Pay-per-use (~1K queries) | $2-5 |
| **TOTAL** | | **~$20-30/month** |

### Stacks

1. **CurateAI-Network**: VPC, subnets, security groups, VPC endpoints
2. **CurateAI-ECS**: ECR, Fargate cluster, task definition, service
3. **CurateAI-Pipeline**: GitHub → CodeBuild → ECS deployment
4. **CurateAI-Observability**: CloudWatch dashboards, alarms, SNS notifications

## Prerequisites

### 1. Install AWS CDK

```bash
# Install Node.js (required for CDK CLI)
# macOS
brew install node

# Install CDK CLI globally
npm install -g aws-cdk

# Verify installation
cdk --version
```

### 2. Install Python Dependencies

```bash
cd infrastructure
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure AWS Credentials

```bash
# Configure AWS CLI
aws configure
# Enter:
# - AWS Access Key ID
# - AWS Secret Access Key
# - Default region: us-east-1
# - Default output format: json

# Verify configuration
aws sts get-caller-identity
```

### 4. Create GitHub CodeStar Connection

```bash
# Create connection
aws codestar-connections create-connection \
  --provider-type GitHub \
  --connection-name curateai-github \
  --region us-east-1

# Note the ConnectionArn from output
# Example: arn:aws:codestar-connections:us-east-1:558599919081:connection/xxx

# IMPORTANT: Go to AWS Console and complete the GitHub authorization
# https://console.aws.amazon.com/codesuite/settings/connections
```

## Deployment

### Step 1: Set Environment Variables

```bash
# Required variables
export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="us-east-1"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"
export GITHUB_BRANCH="main"

# Optional variables
export CODESTAR_CONNECTION_ARN="arn:aws:codestar-connections:us-east-1:558599919081:connection/xxx"
export ALARM_EMAIL="admin@noeticex.com"  # Defaults to this if not set

# Note: No AWS access keys needed! ECS Task uses IAM Role for Bedrock permissions
```

### Step 2: Bootstrap CDK (First Time Only)

```bash
cd infrastructure
cdk bootstrap aws://558599919081/us-east-1
```

### Step 3: Preview Changes

```bash
# Synthesize CloudFormation templates
cdk synth

# Preview changes (what will be deployed)
cdk diff
```

### Step 4: Deploy Stacks

```bash
# Deploy all stacks
cdk deploy --all

# OR deploy individually (recommended for first deployment)
cdk deploy CurateAI-Network
cdk deploy CurateAI-ECS
cdk deploy CurateAI-Pipeline
cdk deploy CurateAI-Observability
```

### Step 5: Build and Push Initial Docker Image

```bash
cd ..  # Return to project root

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 558599919081.dkr.ecr.us-east-1.amazonaws.com

# Build production image
docker build -f Dockerfile.prod -t curateai-app:latest .

# Tag image
docker tag curateai-app:latest \
  558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest

# Push to ECR
docker push 558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest
```

### Step 6: Verify Deployment

```bash
# Get task public IP (replace CLUSTER and SERVICE names)
aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $(aws ecs list-tasks --cluster CurateAI-Cluster --service-name CurateAI-Service --query 'taskArns[0]' --output text) \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text | xargs -I {} aws ec2 describe-network-interfaces \
  --network-interface-ids {} \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text

# Test health endpoint
curl http://<TASK_PUBLIC_IP>:8000/health

# Test chat endpoint
curl -X POST http://<TASK_PUBLIC_IP>:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}'
```

## Post-Deployment

### Monitor Application

1. **CloudWatch Dashboard**: Check the CloudFormation outputs for the dashboard URL
2. **ECS Console**: View running tasks and logs
3. **CodePipeline**: Monitor CI/CD deployments

### View Logs

```bash
# Tail logs in real-time
aws logs tail /ecs/curateai-app --follow

# Filter for errors
aws logs filter-pattern /ecs/curateai-app --filter-pattern "ERROR"
```

### Trigger Manual Deployment

```bash
# Push code to GitHub main branch - pipeline will auto-deploy

# OR manually trigger pipeline
aws codepipeline start-pipeline-execution \
  --name CurateAI-Pipeline
```

## Updating the Application

### Update Code

```bash
# Make changes to code
# Commit and push to GitHub
git add .
git commit -m "Your changes"
git push origin main

# Pipeline will automatically:
# 1. Pull latest code from GitHub
# 2. Build Docker image
# 3. Push to ECR
# 4. Deploy to ECS
```

### Update Infrastructure

```bash
# Modify CDK code in infrastructure/stacks/
# Preview changes
cd infrastructure
cdk diff

# Deploy changes
cdk deploy CurateAI-ECS  # or whichever stack you modified
```

## Rollback

### Rollback Application

```bash
# Rollback to previous task definition
aws ecs update-service \
  --cluster CurateAI-Cluster \
  --service CurateAI-Service \
  --task-definition curateai-task:PREVIOUS_REVISION
```

### Rollback Infrastructure

```bash
# Destroy stacks in reverse order
cd infrastructure
cdk destroy CurateAI-Observability
cdk destroy CurateAI-Pipeline
cdk destroy CurateAI-ECS
cdk destroy CurateAI-Network
```

## Troubleshooting

### Task Not Starting

```bash
# Check task stopped reason
aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $(aws ecs list-tasks --cluster CurateAI-Cluster --query 'taskArns[0]' --output text)

# Check logs
aws logs tail /ecs/curateai-app --follow
```

### Pipeline Failing

```bash
# Check CodeBuild logs
aws codebuild list-builds-for-project --project-name CurateAI-Build

# Get build logs
aws codebuild batch-get-builds --ids <BUILD_ID>
```

### High Costs

```bash
# Check Fargate usage
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-02-01 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --filter file://cost-filter.json
```

## Known Limitations (Phase 1)

- ⚠️ **No HTTPS**: Only HTTP on port 8000
- ⚠️ **Dynamic IP**: Task public IP changes on restart
- ⚠️ **No Auto-Scaling**: 1 task only
- ⚠️ **Hardcoded Credentials**: AWS keys in environment variables
- ⚠️ **No Database**: YAML-based knowledge graphs only

These will be addressed in Phase 2 (Database) and Phase 3 (Full Integration).

## Next Steps

After Phase 1 deployment:

1. **Phase 2**: Set up Neon PostgreSQL and migrate knowledge graphs to database
2. **Phase 3**: Connect backend to database and enable DB-backed features
3. **Future**: Add custom domain, HTTPS, auto-scaling, Secrets Manager

## Support

For issues or questions:
- Check CloudWatch logs: `/ecs/curateai-app`
- Review ECS task events
- Verify environment variables in task definition
