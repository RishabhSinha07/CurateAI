# CurateAI AWS Deployment Checklist - Phase 1

## Pre-Deployment

### Environment Setup
- [ ] AWS CLI installed and configured
- [ ] AWS account ID: `558599919081`
- [ ] AWS region: `us-east-1`
- [ ] Node.js and npm installed (for CDK CLI)
- [ ] CDK CLI installed: `npm install -g aws-cdk`
- [ ] Python 3.11+ installed
- [ ] Docker installed and running

### AWS Credentials
- [ ] AWS Access Key ID obtained (for Bedrock)
- [ ] AWS Secret Access Key obtained (for Bedrock)
- [ ] AWS CLI configured: `aws configure`
- [ ] Verified credentials: `aws sts get-caller-identity`

### GitHub Setup
- [ ] GitHub repository: `https://github.com/RishabhSinha07/CurateAI`
- [ ] Repository is private
- [ ] Code is on `main` branch
- [ ] Dockerfile.prod exists in repository

### CDK Bootstrap
- [ ] CDK bootstrapped: `cdk bootstrap aws://558599919081/us-east-1`
- [ ] Bootstrap stack exists in CloudFormation

## Deployment Steps

### 1. Install Dependencies
```bash
cd infrastructure
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
- [ ] Virtual environment created
- [ ] Dependencies installed

### 2. Set Environment Variables
```bash
export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="us-east-1"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"
export GITHUB_BRANCH="main"
export AWS_ACCESS_KEY_ID="<your-key>"
export AWS_SECRET_ACCESS_KEY="<your-secret>"
export ALARM_EMAIL="<your-email>"  # Optional
```
- [ ] All required variables set
- [ ] Variables verified: `echo $CDK_DEFAULT_ACCOUNT`

### 3. Create GitHub CodeStar Connection
```bash
aws codestar-connections create-connection \
  --provider-type GitHub \
  --connection-name curateai-github \
  --region us-east-1
```
- [ ] Connection created
- [ ] Connection ARN saved
- [ ] GitHub authorization completed in AWS Console
- [ ] Connection status: AVAILABLE

```bash
export CODESTAR_CONNECTION_ARN="<your-connection-arn>"
```

### 4. Validate CDK Code
```bash
cd infrastructure
cdk synth
```
- [ ] No syntax errors
- [ ] CloudFormation templates generated in `cdk.out/`
- [ ] Reviewed generated templates

### 5. Deploy Network Stack
```bash
cdk deploy CurateAI-Network
```
- [ ] VPC created
- [ ] Public subnets created (2 AZs)
- [ ] VPC endpoints created (ECR, Logs, S3)
- [ ] Security groups created
- [ ] Stack outputs verified

### 6. Deploy ECS Stack
```bash
cdk deploy CurateAI-ECS
```
- [ ] ECR repository created
- [ ] ECS cluster created
- [ ] Task definition created
- [ ] Fargate service created
- [ ] IAM roles created
- [ ] CloudWatch log group created
- [ ] Stack outputs verified

### 7. Build and Push Docker Image
```bash
cd ..  # Return to project root

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 558599919081.dkr.ecr.us-east-1.amazonaws.com

# Build image
docker build -f Dockerfile.prod -t curateai-app:latest .

# Tag image
docker tag curateai-app:latest \
  558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest

# Push to ECR
docker push 558599919081.dkr.ecr.us-east-1.amazonaws.com/curateai-app:latest
```
- [ ] ECR login successful
- [ ] Docker build completed without errors
- [ ] Image tagged correctly
- [ ] Image pushed to ECR
- [ ] Image visible in ECR console

### 8. Deploy Pipeline Stack
```bash
cd infrastructure
cdk deploy CurateAI-Pipeline
```
- [ ] CodeBuild project created
- [ ] CodePipeline created
- [ ] Pipeline stages configured (Source, Build, Deploy)
- [ ] Stack outputs verified
- [ ] Pipeline console URL saved

### 9. Deploy Observability Stack
```bash
cdk deploy CurateAI-Observability
```
- [ ] SNS topic created
- [ ] CloudWatch dashboard created
- [ ] CloudWatch alarms created
- [ ] Email subscription confirmed (if provided)
- [ ] Stack outputs verified

## Post-Deployment Verification

### ECS Service Health
- [ ] ECS service is ACTIVE
- [ ] Desired task count: 1
- [ ] Running task count: 1
- [ ] Task health status: HEALTHY

Get task status:
```bash
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service
```

### Get Task Public IP
```bash
# Get running task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster CurateAI-Cluster \
  --service-name CurateAI-Service \
  --query 'taskArns[0]' \
  --output text)

# Get task details
aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text | xargs -I {} aws ec2 describe-network-interfaces \
  --network-interface-ids {} \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text
```
- [ ] Task public IP obtained: `__________________`

### Application Health Check
```bash
# Replace <IP> with actual task public IP
curl http://<IP>:8000/health
```
- [ ] Response: `{"status":"healthy"}`
- [ ] Response time < 1 second

### Test Chat Endpoint
```bash
curl -X POST http://<IP>:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}'
```
- [ ] Response received
- [ ] Response contains product recommendations
- [ ] No errors in response

### CloudWatch Logs
```bash
aws logs tail /ecs/curateai-app --follow
```
- [ ] Logs streaming successfully
- [ ] Application startup logs visible
- [ ] No error messages
- [ ] JSON log format (production mode)

### CloudWatch Dashboard
- [ ] Dashboard accessible via URL from stack output
- [ ] Metrics visible:
  - [ ] Running task count
  - [ ] CPU utilization
  - [ ] Memory utilization
  - [ ] Log events

### CloudWatch Alarms
- [ ] All alarms in OK state
- [ ] Alarm actions configured (SNS topic)
- [ ] Test alarm notification (optional)

### CodePipeline
- [ ] Pipeline visible in console
- [ ] Source stage configured (GitHub)
- [ ] Build stage configured (CodeBuild)
- [ ] Deploy stage configured (ECS)
- [ ] Pipeline status: Succeeded (or ready to run)

## Test CI/CD Pipeline

### Trigger Pipeline
```bash
# Make a small change to code
echo "# Test comment" >> README.md
git add .
git commit -m "Test CI/CD pipeline"
git push origin main
```
- [ ] Code pushed to GitHub
- [ ] Pipeline triggered automatically
- [ ] Source stage: Succeeded
- [ ] Build stage: Succeeded
- [ ] Deploy stage: Succeeded
- [ ] New task deployed successfully

### Verify New Deployment
- [ ] New task definition revision created
- [ ] New task running
- [ ] Old task terminated gracefully
- [ ] Zero downtime deployment
- [ ] Application still accessible

## Cost Verification

### Check Initial Costs
```bash
# View cost and usage for current month
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-02-05 \
  --granularity DAILY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```
- [ ] Fargate costs visible
- [ ] ECR costs visible
- [ ] VPC endpoint costs visible
- [ ] Total daily cost < $1 (Phase 1)

### Set Budget Alert (Optional)
```bash
# Create monthly budget alert at $50
aws budgets create-budget \
  --account-id 558599919081 \
  --budget file://budget.json
```
- [ ] Budget created
- [ ] Alert email configured
- [ ] Threshold: $50/month

## Documentation

### Update Project Documentation
- [ ] Add deployment notes to main README
- [ ] Document task public IP location
- [ ] Add API endpoint documentation
- [ ] Update environment variables section

### Save Important Information
- [ ] ECR repository URI: `__________________`
- [ ] ECS cluster name: `CurateAI-Cluster`
- [ ] ECS service name: `CurateAI-Service`
- [ ] Task public IP: `__________________`
- [ ] CloudWatch dashboard URL: `__________________`
- [ ] CodePipeline URL: `__________________`
- [ ] CodeStar connection ARN: `__________________`

## Rollback Plan (If Needed)

### Rollback Application Deployment
```bash
# Revert to previous task definition
aws ecs update-service \
  --cluster CurateAI-Cluster \
  --service CurateAI-Service \
  --task-definition curateai-task:1  # Previous revision
```

### Rollback Infrastructure (If Critical Issues)
```bash
cd infrastructure
cdk destroy CurateAI-Observability
cdk destroy CurateAI-Pipeline
cdk destroy CurateAI-ECS
cdk destroy CurateAI-Network
```

## Phase 1 Complete! ✅

- [ ] All stacks deployed successfully
- [ ] Application accessible via public IP
- [ ] CI/CD pipeline working
- [ ] Monitoring configured
- [ ] Costs within budget
- [ ] Documentation updated

**Next**: Proceed to Phase 2 (Database Setup) when ready.

## Phase 2 Preview

Phase 2 will add:
- [ ] Neon PostgreSQL database
- [ ] Knowledge graphs migrated to database (JSONB)
- [ ] Database-backed graph loader
- [ ] Keep existing YAML support with feature flag

## Phase 3 Preview

Phase 3 will add:
- [ ] Secrets Manager for database credentials
- [ ] Secrets Manager for AWS credentials
- [ ] Database connection in task definition
- [ ] Database migrations in Docker CMD
- [ ] Enable DB-backed graphs via environment variable

## Notes

- Task public IP changes when task restarts
- No HTTPS in Phase 1 (HTTP only)
- No auto-scaling in Phase 1
- Estimated cost: $20-30/month
- Deployment time: ~30-45 minutes

## Support

If issues occur:
1. Check CloudWatch logs: `/ecs/curateai-app`
2. Check ECS task events
3. Verify environment variables
4. Check security group rules
5. Verify task has public IP assigned
