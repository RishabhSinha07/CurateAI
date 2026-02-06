# CurateAI Quick Reference

Essential commands for working with CurateAI backend.

## 🌐 Production Endpoints

```
API Gateway: https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com
Task IP (current): http://44.203.0.146:8000
```

---

## 🚀 Common Operations

### Get Current Task IP

```bash
./scripts/get_task_ip.sh
```

### Update API Gateway After Deployment

```bash
./scripts/update_api_gateway.sh
```

### Test Health Endpoint

```bash
# API Gateway
curl https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/

# Direct task
curl http://44.203.0.146:8000/health
```

### Test Chat Endpoint

```bash
# Simple query (no auth needed for direct access)
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep quality"}' | python3 -m json.tool
```

### Monitor Logs

```bash
# Real-time
aws logs tail /ecs/curateai-app --follow --region us-east-1

# Last 10 minutes
aws logs tail /ecs/curateai-app --since 10m --region us-east-1
```

### Check Pipeline Status

```bash
aws codepipeline get-pipeline-state \
  --name CurateAI-Pipeline \
  --region us-east-1 \
  --query 'stageStates[*].[stageName, actionStates[0].latestExecution.status]' \
  --output table
```

### Check ECS Service Status

```bash
aws ecs describe-services \
  --cluster CurateAI-Cluster \
  --services CurateAI-Service \
  --region us-east-1 \
  --query 'services[0].deployments[*].[status, desiredCount, runningCount]' \
  --output table
```

---

## 🔐 Authentication (API Gateway)

### Get Admin Password

```bash
aws secretsmanager get-secret-value \
  --secret-id CurateAI-AdminPassword \
  --region us-east-1 \
  --query SecretString \
  --output text
```

### Get Authentication Token

```bash
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 5jsuki7st5po9vj4u0ua1mt7e2 \
  --region us-east-1 \
  --auth-parameters USERNAME=admin,PASSWORD=$(aws secretsmanager get-secret-value --secret-id CurateAI-AdminPassword --region us-east-1 --query SecretString --output text) \
  --query 'AuthenticationResult.IdToken' \
  --output text)
```

### Make Authenticated Request

```bash
curl -X POST https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}' | python3 -m json.tool
```

---

## 📊 Deployment Workflow

```bash
# 1. Make code changes
git add .
git commit -m "Your commit message"
git push origin main

# 2. Monitor pipeline (takes ~8-10 min)
# https://console.aws.amazon.com/codesuite/codepipeline/pipelines/CurateAI-Pipeline

# 3. Update API Gateway with new task IP
./scripts/update_api_gateway.sh

# 4. Test the deployment
curl http://$(./scripts/get_task_ip.sh | grep "Current Task IP" | awk '{print $4}'):8000/health
```

---

## 🧪 Testing Examples

### Multi-Domain Queries

```bash
TASK_IP="44.203.0.146"

# Sleep/Stress
curl -s -X POST http://$TASK_IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I cant sleep well"}' | python3 -m json.tool

# Skin Health
curl -s -X POST http://$TASK_IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}' | python3 -m json.tool

# Energy
curl -s -X POST http://$TASK_IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I feel tired all day"}' | python3 -m json.tool

# Muscle Recovery
curl -s -X POST http://$TASK_IP:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I need help with muscle recovery"}' | python3 -m json.tool
```

### Multi-Turn Conversation

```bash
# First message
RESPONSE=$(curl -s -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to improve my sleep"}')

# Extract session ID
SESSION_ID=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")

# Continue conversation
curl -X POST http://44.203.0.146:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"I sleep 5-6 hours with high stress\", \"session_id\": \"$SESSION_ID\"}" | python3 -m json.tool
```

---

## 🔧 Troubleshooting

### Task not responding

```bash
# Check task status
aws ecs describe-tasks \
  --cluster CurateAI-Cluster \
  --tasks $(aws ecs list-tasks --cluster CurateAI-Cluster --service-name CurateAI-Service --region us-east-1 --desired-status RUNNING --query 'taskArns[0]' --output text) \
  --region us-east-1 \
  --query 'tasks[0].[lastStatus, healthStatus]' \
  --output table

# Check logs for errors
aws logs tail /ecs/curateai-app --since 5m --region us-east-1 | grep -i error
```

### API Gateway not working

```bash
# Update with latest task IP
./scripts/update_api_gateway.sh

# Test direct access first
curl http://44.203.0.146:8000/health
```

### Pipeline stuck or failed

```bash
# Check pipeline status
aws codepipeline get-pipeline-state --name CurateAI-Pipeline --region us-east-1

# View pipeline execution history
aws codepipeline list-pipeline-executions --pipeline-name CurateAI-Pipeline --region us-east-1 --max-results 5
```

---

## 📚 Documentation

- **Full Backend Access Guide:** [BACKEND_ACCESS.md](./BACKEND_ACCESS.md)
- **Scripts Documentation:** [scripts/README.md](./scripts/README.md)
- **Project Guide:** [CLAUDE.md](./CLAUDE.md)
- **Database Schema:** [Database.md](./Database.md)

---

## 🔗 Console Links

- [ECS Service](https://console.aws.amazon.com/ecs/home?region=us-east-1#/clusters/CurateAI-Cluster/services/CurateAI-Service)
- [CloudWatch Logs](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fecs$252Fcurateai-app)
- [API Gateway](https://console.aws.amazon.com/apigateway/main/apis/7c43mgwqr6)
- [CodePipeline](https://console.aws.amazon.com/codesuite/codepipeline/pipelines/CurateAI-Pipeline)
- [Neon Database](https://console.neon.tech/)

---

## ⚙️ Configuration

| Setting | Value |
|---------|-------|
| **Model** | Amazon Nova Lite (`us.amazon.nova-lite-v1:0`) |
| **Bedrock Region** | us-east-2 |
| **Infrastructure Region** | us-east-1 |
| **Products** | 135 (Neon PostgreSQL) |
| **Knowledge Graphs** | 13 YAML domains |
| **User Pool ID** | us-east-1_4g15LXnhb |
| **Client ID** | 5jsuki7st5po9vj4u0ua1mt7e2 |

---

## 📋 Active Domains

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

**Last Updated:** 2026-02-06
**Current Task IP:** 44.203.0.146
