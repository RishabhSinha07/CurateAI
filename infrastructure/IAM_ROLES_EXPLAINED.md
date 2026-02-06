# IAM Roles for Bedrock Access - Explained

## Why IAM Roles Instead of Access Keys?

CurateAI uses **IAM Task Roles** for AWS Bedrock access instead of hardcoded access keys. This is the AWS-recommended approach for several reasons:

### Security Benefits

1. **No Credential Storage**: No AWS access keys stored in environment variables or configuration files
2. **No Credential Rotation**: AWS automatically handles credential rotation
3. **Least Privilege**: Can grant only the exact permissions needed (Bedrock model invocation)
4. **Audit Trail**: All API calls are logged with the task role identity
5. **No Accidental Exposure**: Can't accidentally commit credentials to Git

### How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     AWS Account                              │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │              ECS Fargate Task                       │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────┐          │    │
│  │  │   Container: curateai-app            │          │    │
│  │  │                                       │          │    │
│  │  │   boto3.client('bedrock-runtime')   │          │    │
│  │  │         ↓                            │          │    │
│  │  │   [Automatically uses Task Role]    │          │    │
│  │  └──────────────────────────────────────┘          │    │
│  │                                                      │    │
│  │  Task Role: arn:aws:iam::558599919081:role/...    │    │
│  │  Permissions:                                       │    │
│  │  - bedrock:InvokeModel                             │    │
│  │  - bedrock:InvokeModelWithResponseStream           │    │
│  └────────────────────────────────────────────────────┘    │
│                          ↓                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │         AWS Bedrock                                 │    │
│  │  - Claude 3.5 Haiku                                 │    │
│  │  - Titan Embeddings v2                              │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Implementation in CurateAI

### 1. IAM Task Role Definition (CDK)

From `infrastructure/stacks/ecs_stack.py`:

```python
# Task Role - for application runtime (Bedrock access)
self.task_role = iam.Role(
    self,
    "Task-Role",
    assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
)

# Allow Bedrock model invocation
self.task_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=[
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
        ],
        resources=[
            f"arn:aws:bedrock:{self.region}::foundation-model/*",
        ],
    )
)
```

### 2. Task Definition with Role

```python
self.task_definition = ecs.FargateTaskDefinition(
    self,
    "CurateAI-Task",
    cpu=512,
    memory_limit_mib=1024,
    task_role=self.task_role,  # ← Task role attached here
)
```

### 3. Application Code (Automatic)

In your Python application (`app/services/` or `app/agents/`), boto3 automatically uses the task role:

```python
import boto3

# No credentials needed in code!
# boto3 automatically discovers and uses the ECS Task Role
bedrock_client = boto3.client(
    'bedrock-runtime',
    region_name='us-east-1'
)

# Make API calls - automatically authenticated via IAM role
response = bedrock_client.invoke_model(
    modelId='anthropic.claude-3-5-haiku-20241022-v1:0',
    body=json.dumps(request_body)
)
```

### 4. Environment Variables (No Credentials)

```python
environment={
    "AWS_REGION": "us-east-1",  # Just the region
    "BEDROCK_MODEL_ID": "anthropic.claude-3-5-haiku-20241022-v1:0",
    # No AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY needed!
}
```

## How boto3 Discovers Credentials

boto3 uses this credential discovery order:

1. **Environment variables** (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
2. **AWS credentials file** (~/.aws/credentials)
3. **IAM role for EC2/ECS** ← This is what we use!
4. **Assume role provider**

Since we don't provide credentials in steps 1-2, boto3 automatically discovers and uses the ECS Task Role (step 3).

## Verification

After deployment, you can verify the task role is being used:

```bash
# Get the task role ARN
aws ecs describe-task-definition \
  --task-definition curateai-task \
  --query 'taskDefinition.taskRoleArn' \
  --output text

# View the role's permissions
aws iam get-role-policy \
  --role-name <role-name> \
  --policy-name <policy-name>
```

## CloudWatch Logs

You'll see in the application logs that boto3 uses the task role credentials:

```json
{
  "timestamp": "2026-02-05T12:00:00Z",
  "level": "INFO",
  "logger": "botocore.credentials",
  "message": "Found credentials from IAM Role: Task-Role"
}
```

## Comparison: Access Keys vs IAM Roles

| Aspect | Access Keys | IAM Task Role |
|--------|-------------|---------------|
| **Storage** | Environment variables/config | Attached to ECS task |
| **Rotation** | Manual (every 90 days) | Automatic by AWS |
| **Exposure Risk** | High (can leak in logs/Git) | Low (never visible) |
| **Granularity** | IAM user permissions | Task-specific permissions |
| **Audit** | User identity | Task/service identity |
| **Best Practice** | ❌ Not recommended for AWS services | ✅ AWS recommended |

## Local Development

For local development (outside ECS), you still need AWS credentials:

```bash
# Option 1: AWS CLI credentials
aws configure

# Option 2: Environment variables (temporary)
export AWS_ACCESS_KEY_ID="your-dev-key"
export AWS_SECRET_ACCESS_KEY="your-dev-secret"
export AWS_REGION="us-east-1"

# Run locally
python -m uvicorn app.main:app --reload
```

Docker local testing:
```bash
# Mount AWS credentials into container
docker run -p 8000:8000 \
  -e AWS_REGION=us-east-1 \
  -v ~/.aws:/root/.aws:ro \
  curateai-app:latest
```

## Phase 3 Enhancement

In Phase 3, we'll also use IAM roles for database access via Secrets Manager:

```python
# Secrets Manager access via IAM role
self.task_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=["secretsmanager:GetSecretValue"],
        resources=[database_secret.secret_arn],
    )
)
```

This means:
- ✅ No Bedrock access keys
- ✅ No database passwords in environment variables
- ✅ All credentials managed by AWS

## Troubleshooting

### Issue: "Unable to locate credentials"

**Cause**: boto3 can't find the task role

**Solution**:
1. Verify task definition has `taskRoleArn` set
2. Check ECS service is using latest task definition
3. View task details: `aws ecs describe-tasks --cluster CurateAI-Cluster --tasks <task-arn>`

### Issue: "Access Denied" errors

**Cause**: Task role doesn't have required permissions

**Solution**:
1. Check task role policy: `aws iam list-attached-role-policies --role-name <role-name>`
2. Verify Bedrock permissions are attached
3. Ensure region matches (us-east-1)

## Security Best Practices

✅ **Do:**
- Use IAM roles for all AWS service access
- Grant least privilege permissions
- Enable CloudTrail for audit logs
- Regularly review IAM policies

❌ **Don't:**
- Hardcode AWS access keys in code
- Store credentials in environment variables (for ECS)
- Use root account credentials
- Grant overly broad permissions

## Summary

CurateAI uses **IAM Task Roles** for secure, automatic AWS Bedrock access:

- ✅ More secure than access keys
- ✅ AWS best practice for ECS
- ✅ No manual credential rotation
- ✅ Zero configuration in application code
- ✅ Automatic credential discovery via boto3

This is the recommended approach for all AWS services running on ECS, Lambda, EC2, or any other AWS compute service.
