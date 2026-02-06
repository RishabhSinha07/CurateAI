#!/bin/bash
# Get current ECS task public IP

set -e

echo "Getting current Fargate task IP..."

TASK_ARN=$(aws ecs list-tasks \
  --cluster CurateAI-Cluster \
  --service-name CurateAI-Service \
  --region us-east-1 \
  --desired-status RUNNING \
  --query 'taskArns[0]' \
  --output text)

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" == "None" ]; then
  echo "❌ No running tasks found"
  exit 1
fi

echo "Task ARN: $TASK_ARN"

TASK_IP=$(aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks "$TASK_ARN" \
  --region us-east-1 \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text | \
  xargs -I {} aws ec2 describe-network-interfaces \
  --network-interface-ids {} \
  --region us-east-1 \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

if [ -z "$TASK_IP" ] || [ "$TASK_IP" == "None" ]; then
  echo "❌ Could not retrieve task IP"
  exit 1
fi

echo ""
echo "✅ Current Task IP: $TASK_IP"
echo ""
echo "Direct API endpoint: http://$TASK_IP:8000"
echo ""
echo "Test with:"
echo "  curl http://$TASK_IP:8000/health"
echo ""
