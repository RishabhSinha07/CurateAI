#!/bin/bash
set -e

##############################################################################
# Update API Gateway Backend URL After ECS Deployment
#
# This script:
# 1. Gets the current Fargate task public IP
# 2. Updates API Gateway integration with new backend URL
# 3. Tests the endpoints
#
# Usage:
#   ./scripts/update_api_gateway.sh
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Update API Gateway After Deployment${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Configuration
REGION="us-east-1"
CLUSTER_NAME="CurateAI-Cluster"
SERVICE_NAME="CurateAI-Service"

# Get current task IP
echo -e "${YELLOW}1. Getting current Fargate task IP...${NC}"

TASK_ARN=$(aws ecs list-tasks \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --desired-status RUNNING \
  --region "$REGION" \
  --query 'taskArns[0]' \
  --output text)

if [ "$TASK_ARN" == "None" ] || [ -z "$TASK_ARN" ]; then
  echo -e "${RED}❌ No running tasks found!${NC}"
  echo "Make sure the ECS service has a running task."
  exit 1
fi

echo "Task ARN: $TASK_ARN"

# Get network interface ID
ENI_ID=$(aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

# Get public IP
CURRENT_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids "$ENI_ID" \
  --region "$REGION" \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

echo -e "${GREEN}✅ Current IP: $CURRENT_IP${NC}"
BACKEND_URL="http://$CURRENT_IP:8000"
echo ""

# Test direct access
echo -e "${YELLOW}2. Testing direct Fargate access...${NC}"
HEALTH_CHECK=$(curl -s "$BACKEND_URL/health" || echo "failed")
if [[ "$HEALTH_CHECK" == *"healthy"* ]]; then
  echo -e "${GREEN}✅ Fargate health check passed${NC}"
else
  echo -e "${RED}❌ Fargate health check failed: $HEALTH_CHECK${NC}"
  echo "Continuing anyway..."
fi
echo ""

# Update API Gateway
echo -e "${YELLOW}3. Updating API Gateway backend URL...${NC}"

export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="$REGION"
export BACKEND_URL="$BACKEND_URL"
export ALARM_EMAIL="admin@noeticex.com"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"

cd "$(dirname "$0")/../infrastructure"

echo "Backend URL: $BACKEND_URL"
cdk deploy CurateAI-Auth --require-approval never

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✅ API Gateway updated successfully${NC}"
else
  echo -e "${RED}❌ API Gateway update failed${NC}"
  exit 1
fi

cd - > /dev/null
echo ""

# Get API Gateway endpoint
echo -e "${YELLOW}4. Getting API Gateway endpoint...${NC}"
API_ENDPOINT=$(aws apigatewayv2 get-apis \
  --region "$REGION" \
  --query 'Items[?Name==`CurateAI-API`].ApiEndpoint' \
  --output text)

echo -e "${GREEN}API Endpoint: $API_ENDPOINT${NC}"
echo ""

# Test API Gateway health
echo -e "${YELLOW}5. Testing API Gateway health...${NC}"
API_HEALTH=$(curl -s "$API_ENDPOINT/health" || echo "failed")
if [[ "$API_HEALTH" == *"Welcome"* ]] || [[ "$API_HEALTH" == *"healthy"* ]]; then
  echo -e "${GREEN}✅ API Gateway health check passed${NC}"
else
  echo -e "${YELLOW}⚠️  API Gateway health check response: $API_HEALTH${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  Update Complete!${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "${GREEN}✅ Fargate Task IP:${NC} $CURRENT_IP"
echo -e "${GREEN}✅ Backend URL:${NC} $BACKEND_URL"
echo -e "${GREEN}✅ API Endpoint:${NC} $API_ENDPOINT"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test chat endpoint with Cognito auth"
echo "2. Monitor CloudWatch logs: aws logs tail /ecs/curateai-app --follow"
echo ""
