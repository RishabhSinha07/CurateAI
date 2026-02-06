# CurateAI Backend Access Guide

Complete guide for accessing the CurateAI backend API in production.

## Table of Contents
- [Quick Reference](#quick-reference)
- [Access Methods](#access-methods)
- [Getting Authentication Tokens](#getting-authentication-tokens)
- [API Endpoints](#api-endpoints)
- [Finding Current Task IP](#finding-current-task-ip)
- [Testing Examples](#testing-examples)
- [Troubleshooting](#troubleshooting)

---

## Quick Reference

### Production Endpoints

| Access Method | URL | Auth Required |
|--------------|-----|---------------|
| **API Gateway (Recommended)** | `https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com` | Yes (Cognito) |
| **Direct ECS Task** | `http://<TASK_IP>:8000` | No (for testing only) |

### Cognito Configuration

```bash
User Pool ID: us-east-1_4g15LXnhb
Client ID: 5jsuki7st5po9vj4u0ua1mt7e2
Admin Username: admin
Admin Email: admin@noeticex.com
```

---

## Access Methods

### Method 1: API Gateway (Production - Recommended)

**When to use:**
- Production applications
- Public-facing clients
- When you need HTTPS and authentication

**Pros:**
- ✅ Stable URL (doesn't change)
- ✅ HTTPS secure connection
- ✅ Cognito authentication
- ✅ Rate limiting and monitoring
- ✅ CORS configured

**Cons:**
- ❌ Requires authentication token
- ❌ Slightly higher latency

**Base URL:** `https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com`

**Example:**
```bash
# Health check (no auth required)
curl https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/

# Chat endpoint (auth required)
curl -X POST https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}'
```

---

### Method 2: Direct ECS Task Access (Testing Only)

**When to use:**
- Development and testing
- Debugging
- Quick API verification
- Bypassing authentication for testing

**Pros:**
- ✅ No authentication needed
- ✅ Direct access, lower latency
- ✅ Easy for debugging

**Cons:**
- ❌ IP changes on every deployment
- ❌ HTTP only (no HTTPS)
- ❌ Not recommended for production
- ❌ Task can be stopped/restarted

**Get Current Task IP:**
```bash
./scripts/get_task_ip.sh
# Or manually:
aws ecs list-tasks --cluster CurateAI-Cluster --service-name CurateAI-Service --region us-east-1 --desired-status RUNNING --query 'taskArns[0]' --output text | \
  xargs -I {} aws ecs describe-tasks --cluster CurateAI-Cluster --tasks {} --region us-east-1 --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text | \
  xargs -I {} aws ec2 describe-network-interfaces --network-interface-ids {} --region us-east-1 --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

**Current Task IP:** `44.203.0.146` (as of 2026-02-06)

**Example:**
```bash
# Health check
curl http://44.203.0.146:8000/health

# Chat endpoint (no auth needed)
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}'
```

---

## Getting Authentication Tokens

### Step 1: Get Admin Password

The admin password is stored in AWS Secrets Manager:

```bash
aws secretsmanager get-secret-value \
  --secret-id CurateAI-AdminPassword \
  --region us-east-1 \
  --query SecretString \
  --output text
```

### Step 2: Authenticate and Get Token

**Using AWS CLI:**
```bash
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 5jsuki7st5po9vj4u0ua1mt7e2 \
  --region us-east-1 \
  --auth-parameters USERNAME=admin,PASSWORD=<ADMIN_PASSWORD> \
  --query 'AuthenticationResult.IdToken' \
  --output text
```

**Using curl:**
```bash
# Get password
ADMIN_PASSWORD=$(aws secretsmanager get-secret-value --secret-id CurateAI-AdminPassword --region us-east-1 --query SecretString --output text)

# Authenticate
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 5jsuki7st5po9vj4u0ua1mt7e2 \
  --region us-east-1 \
  --auth-parameters USERNAME=admin,PASSWORD=$ADMIN_PASSWORD \
  --query 'AuthenticationResult.IdToken' \
  --output text)

# Use token
curl -X POST https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}'
```

### Step 3: Token Expiration

- **ID Token validity:** 1 hour (3600 seconds)
- **Refresh token validity:** 30 days
- Re-authenticate when token expires

---

## API Endpoints

### Health Check

**Endpoint:** `GET /` or `GET /health`
**Auth:** Not required
**Description:** Check if API is running

```bash
# API Gateway
curl https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/

# Direct
curl http://44.203.0.146:8000/health
```

**Response:**
```json
{
  "status": "healthy"
}
```

---

### Chat Endpoint

**Endpoint:** `POST /chat`
**Auth:** Required (API Gateway only)
**Description:** Multi-agent consultation system

**Request Body:**
```json
{
  "message": "I want to improve my sleep quality",
  "session_id": "optional-existing-session-id"
}
```

**Response:**
```json
{
  "session_id": "5a7db413-5d93-4645-8cec-d3025c5e09b5",
  "response": "AI-generated response with product recommendations",
  "status": "awaiting_slot",
  "domain_slug": "sleep_stress_mental_calm",
  "intent_type": "query",
  "products": [
    {
      "id": "product-uuid",
      "name": "Product Name",
      "brand": "Wellbeing Nutrition",
      "price": 599.0,
      "currency": "INR",
      "product_url": "https://...",
      "image_url": "https://...",
      "match_reasons": ["Popular in sleep_stress_mental_calm"]
    }
  ],
  "journey_info": null
}
```

**Example:**
```bash
# With API Gateway (auth required)
curl -X POST https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I want to improve my sleep quality"
  }'

# Direct (no auth)
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I want to improve my sleep quality"
  }'
```

**Multi-turn Conversation:**
```bash
# First message (system creates session)
RESPONSE=$(curl -s -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}')

# Extract session_id
SESSION_ID=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")

# Continue conversation with same session
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"I sleep 5-6 hours and have high stress\",
    \"session_id\": \"$SESSION_ID\"
  }"
```

---

## Finding Current Task IP

### After Deployment

Every time the ECS task restarts or is replaced (deployments, crashes, Fargate Spot interruptions), the public IP changes.

**Quick Method:**
```bash
./scripts/update_api_gateway.sh
```
This script:
1. Gets current task IP
2. Tests health endpoint
3. Updates API Gateway with new IP
4. Displays the new IP

**Manual Method:**
```bash
# Get running task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster CurateAI-Cluster \
  --service-name CurateAI-Service \
  --region us-east-1 \
  --desired-status RUNNING \
  --query 'taskArns[0]' \
  --output text)

# Get task's network interface
ENI=$(aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $TASK_ARN \
  --region us-east-1 \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

# Get public IP
aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI \
  --region us-east-1 \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text
```

**Via AWS Console:**
1. Navigate to ECS: https://console.aws.amazon.com/ecs
2. Select `CurateAI-Cluster`
3. Click `CurateAI-Service`
4. Go to "Tasks" tab
5. Click on running task
6. Find "Public IP" under "Network"

---

## Testing Examples

### 1. Basic Health Check

```bash
# Test both endpoints
curl https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/
curl http://44.203.0.146:8000/health
```

### 2. Simple Chat Query

```bash
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}' | python3 -m json.tool
```

### 3. Multi-Domain Queries

```bash
# Sleep/Stress domain
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I cant sleep well"}'

# Skin health domain
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want glowing skin"}'

# Energy domain
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I feel tired all day"}'

# Muscle recovery domain
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I need help with muscle recovery after workouts"}'
```

### 4. Continue Conversation

```bash
# Start conversation
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}' > response1.json

# Get session ID
SESSION_ID=$(cat response1.json | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")

# Answer follow-up questions
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"I sleep 5 hours with high stress\", \"session_id\": \"$SESSION_ID\"}" | python3 -m json.tool
```

### 5. Test with API Gateway (Authenticated)

```bash
# Get token
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 5jsuki7st5po9vj4u0ua1mt7e2 \
  --region us-east-1 \
  --auth-parameters USERNAME=admin,PASSWORD=$(aws secretsmanager get-secret-value --secret-id CurateAI-AdminPassword --region us-east-1 --query SecretString --output text) \
  --query 'AuthenticationResult.IdToken' \
  --output text)

# Make authenticated request
curl -X POST https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}' | python3 -m json.tool
```

---

## Troubleshooting

### Issue: API Gateway returns "Service Unavailable"

**Cause:** Task IP changed but API Gateway not updated

**Solution:**
```bash
./scripts/update_api_gateway.sh
```

---

### Issue: Direct task connection timeout

**Causes:**
1. Task crashed or restarted (new IP)
2. Security group blocking connection
3. Task in unhealthy state

**Solutions:**

**Check task status:**
```bash
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service \
  --region us-east-1 \
  --query 'services[0].deployments[*].[status, runningCount, desiredCount]' \
  --output table
```

**Check task health:**
```bash
TASK_ARN=$(aws ecs list-tasks --cluster CurateAI-Cluster --service-name CurateAI-Service --region us-east-1 --desired-status RUNNING --query 'taskArns[0]' --output text)

aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $TASK_ARN \
  --region us-east-1 \
  --query 'tasks[0].[lastStatus, healthStatus, containers[0].lastStatus, containers[0].healthStatus]' \
  --output table
```

**Check logs:**
```bash
aws logs tail /ecs/curateai-app --follow --region us-east-1
```

---

### Issue: Cognito authentication fails

**Cause:** Invalid credentials or token expired

**Solutions:**

**Verify admin password:**
```bash
aws secretsmanager get-secret-value \
  --secret-id CurateAI-AdminPassword \
  --region us-east-1 \
  --query SecretString \
  --output text
```

**Get fresh token:**
```bash
# Delete cached token and re-authenticate
unset TOKEN
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 5jsuki7st5po9vj4u0ua1mt7e2 \
  --region us-east-1 \
  --auth-parameters USERNAME=admin,PASSWORD=$(aws secretsmanager get-secret-value --secret-id CurateAI-AdminPassword --region us-east-1 --query SecretString --output text) \
  --query 'AuthenticationResult.IdToken' \
  --output text)
```

---

### Issue: Chat returns errors or unexpected responses

**Debug steps:**

1. **Check application logs:**
```bash
aws logs tail /ecs/curateai-app --follow --region us-east-1
```

2. **Verify database connection:**
```bash
# Check environment variables
TASK_ARN=$(aws ecs list-tasks --cluster CurateAI-Cluster --service-name CurateAI-Service --region us-east-1 --desired-status RUNNING --query 'taskArns[0]' --output text)

aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $TASK_ARN \
  --region us-east-1 \
  --query 'tasks[0].overrides.containerOverrides[0].environment'
```

3. **Test with minimal query:**
```bash
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}' -v
```

4. **Check Nova Lite model access:**
```bash
# From your local machine
aws bedrock-runtime invoke-model \
  --model-id us.amazon.nova-lite-v1:0 \
  --region us-east-2 \
  --body '{"messages":[{"role":"user","content":[{"text":"Hello"}]}],"inferenceConfig":{"maxTokens":100}}' \
  --cli-binary-format raw-in-base64-out \
  /dev/stdout
```

---

## Monitoring

### CloudWatch Logs

**Real-time monitoring:**
```bash
aws logs tail /ecs/curateai-app --follow --region us-east-1
```

**Last 10 minutes:**
```bash
aws logs tail /ecs/curateai-app --since 10m --region us-east-1
```

**Filter for errors:**
```bash
aws logs tail /ecs/curateai-app --follow --region us-east-1 --filter-pattern ERROR
```

### Pipeline Status

```bash
aws codepipeline get-pipeline-state \
  --name CurateAI-Pipeline \
  --region us-east-1 \
  --query 'stageStates[*].[stageName, actionStates[0].latestExecution.status]' \
  --output table
```

### ECS Service Health

```bash
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service \
  --region us-east-1 \
  --query 'services[0].[serviceName, status, runningCount, desiredCount, deployments[0].status]' \
  --output table
```

---

## Current Configuration

**Deployment Date:** 2026-02-06
**Model:** Amazon Nova Lite (`us.amazon.nova-lite-v1:0`)
**Region:** us-east-2 (Bedrock), us-east-1 (Infrastructure)
**Database:** Neon PostgreSQL (135 products)
**Knowledge Graphs:** 13 YAML-based domains

**Active Domains:**
1. sleep_stress_mental_calm
2. energy_stamina_performance
3. weight_management_metabolism
4. hair_health_growth
5. healthy_aging_longevity
6. sexual_wellness_vitality
7. joint_bone_mobility
8. gut_health_digestion
9. immunity_recovery
10. brain_focus_memory
11. muscle_strength_recovery
12. hormonal_balance
13. skin_health_radiance

---

## Quick Links

- **ECS Console:** https://console.aws.amazon.com/ecs/home?region=us-east-1#/clusters/CurateAI-Cluster/services/CurateAI-Service
- **CloudWatch Logs:** https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fecs$252Fcurateai-app
- **API Gateway:** https://console.aws.amazon.com/apigateway/main/apis/7c43mgwqr6/resources?api=7c43mgwqr6&region=us-east-1
- **Cognito User Pool:** https://console.aws.amazon.com/cognito/v2/idp/user-pools/us-east-1_4g15LXnhb
- **CodePipeline:** https://console.aws.amazon.com/codesuite/codepipeline/pipelines/CurateAI-Pipeline
- **Neon Database:** https://console.neon.tech/

---

## Security Notes

⚠️ **Important Security Considerations:**

1. **Direct Task Access:** HTTP only, no encryption. Use for testing only.
2. **API Gateway:** Always use HTTPS with proper authentication in production.
3. **Admin Password:** Stored in AWS Secrets Manager, rotate regularly.
4. **Token Storage:** Never commit tokens to git. Use environment variables.
5. **CORS:** Configured for `*` in development. Restrict in production.
6. **Database:** Connection string includes credentials. Use IAM auth in future.

---

## Support

For issues or questions:
1. Check CloudWatch logs for errors
2. Verify task is running and healthy
3. Ensure API Gateway is updated with latest task IP
4. Test direct task access first, then API Gateway
5. Check this documentation's troubleshooting section

**Deployment Updates:** After any deployment, run `./scripts/update_api_gateway.sh` to update the API Gateway with the new task IP.
