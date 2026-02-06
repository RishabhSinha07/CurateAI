# IAM Role Setup with CDK - Complete Guide

## YES! We Create the IAM Role Automatically with CDK

The CDK code in `infrastructure/stacks/ecs_stack.py` automatically creates an IAM Task Role with all required Bedrock permissions. **No manual IAM configuration needed.**

## What Gets Created

When you run `cdk deploy CurateAI-ECS`, CDK automatically creates:

1. **Task Execution Role** - For ECS to pull images and write logs
2. **Task Role** - For your application to invoke Bedrock models

## Code Walkthrough

### 1. Task Execution Role (ECS Operations)

From `infrastructure/stacks/ecs_stack.py` (lines 98-109):

```python
# Task Execution Role - for pulling images and writing logs
self.task_execution_role = iam.Role(
    self,
    "Task-Execution-Role",
    assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    managed_policies=[
        iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AmazonECSTaskExecutionRolePolicy"
        )
    ],
)
```

**Permissions granted:**
- Pull Docker images from ECR
- Write logs to CloudWatch Logs
- (AWS managed policy provides these)

### 2. Task Role (Bedrock Access) ⭐

From `infrastructure/stacks/ecs_stack.py` (lines 111-130):

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

**This grants:**
- ✅ `bedrock:InvokeModel` - Invoke Claude and Titan models
- ✅ `bedrock:InvokeModelWithResponseStream` - Streaming responses
- ✅ Scoped to all foundation models in us-east-1

### 3. Attach Role to Task Definition

From `infrastructure/stacks/ecs_stack.py` (lines 135-144):

```python
self.task_definition = ecs.FargateTaskDefinition(
    self,
    "CurateAI-Task",
    family="curateai-task",
    cpu=512,  # 0.5 vCPU
    memory_limit_mib=1024,  # 1GB RAM
    execution_role=self.task_execution_role,  # ← For ECS operations
    task_role=self.task_role,  # ← For Bedrock access
)
```

## Generated CloudFormation

When you run `cdk synth`, CDK generates CloudFormation that creates these resources:

```yaml
# Task Role Resource
CurateAITaskRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal:
            Service: ecs-tasks.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: BedrockInvokePolicy
        PolicyDocument:
          Statement:
            - Effect: Allow
              Action:
                - bedrock:InvokeModel
                - bedrock:InvokeModelWithResponseStream
              Resource: "arn:aws:bedrock:us-east-1::foundation-model/*"

# Task Definition with Role
CurateAITaskDefinition:
  Type: AWS::ECS::TaskDefinition
  Properties:
    TaskRoleArn: !GetAtt CurateAITaskRole.Arn  # ← Role attached here
    ExecutionRoleArn: !GetAtt CurateAITaskExecutionRole.Arn
    # ... other properties
```

## Verification After Deployment

### Check Created IAM Role

```bash
# List IAM roles created by CDK
aws iam list-roles --query 'Roles[?contains(RoleName, `CurateAI`)].RoleName' --output table

# Expected output:
# ---------------------------------
# |          ListRoles            |
# +-------------------------------+
# |  CurateAI-ECS-TaskRole-XXXXX  |
# |  CurateAI-ECS-TaskExecRole-XXX|
# +-------------------------------+
```

### View Task Role Permissions

```bash
# Get the task role name
TASK_ROLE=$(aws ecs describe-task-definition \
  --task-definition curateai-task \
  --query 'taskDefinition.taskRoleArn' \
  --output text | awk -F'/' '{print $NF}')

echo "Task Role: $TASK_ROLE"

# View inline policies
aws iam list-role-policies --role-name $TASK_ROLE

# Get policy document
POLICY_NAME=$(aws iam list-role-policies --role-name $TASK_ROLE --query 'PolicyNames[0]' --output text)
aws iam get-role-policy --role-name $TASK_ROLE --policy-name $POLICY_NAME
```

**Expected output:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/*"
    }
  ]
}
```

### Check Task Definition Uses Role

```bash
# View task definition with role
aws ecs describe-task-definition \
  --task-definition curateai-task \
  --query 'taskDefinition.{TaskRole:taskRoleArn,ExecutionRole:executionRoleArn}' \
  --output table
```

**Expected output:**
```
---------------------------------------------------------------------
|                     DescribeTaskDefinition                        |
+-------------------+-----------------------------------------------+
|  ExecutionRole    |  arn:aws:iam::558599919081:role/CurateAI-... |
|  TaskRole         |  arn:aws:iam::558599919081:role/CurateAI-... |
+-------------------+-----------------------------------------------+
```

## How Your Application Uses the Role

### In Python (boto3)

When your FastAPI app creates a Bedrock client:

```python
# In app/agents/ or app/services/
import boto3
import os

# boto3 automatically discovers the ECS Task Role
bedrock_client = boto3.client(
    'bedrock-runtime',
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

# Make API calls - authenticated via IAM role
response = bedrock_client.invoke_model(
    modelId='anthropic.claude-3-5-haiku-20241022-v1:0',
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": "Hello"}]
    })
)
```

### Credential Chain

boto3 uses this order to find credentials:

1. ❌ Environment variables (AWS_ACCESS_KEY_ID) - Not set
2. ❌ ~/.aws/credentials file - Doesn't exist in container
3. ✅ **ECS Task Role** - Found and used automatically!

## CloudWatch Logs Show Role Usage

After deployment, check logs to confirm role is being used:

```bash
aws logs tail /ecs/curateai-app --follow
```

You'll see boto3 messages like:
```json
{
  "timestamp": "2026-02-05T12:00:00Z",
  "level": "DEBUG",
  "logger": "botocore.credentials",
  "message": "Found credentials from IAM Role: CurateAI-ECS-TaskRole-ABC123"
}
```

## What You DON'T Need to Do

❌ **Manually create IAM roles in AWS Console**
❌ **Configure AWS access keys**
❌ **Store credentials in environment variables**
❌ **Rotate credentials manually**
❌ **Add AWS SDK authentication code**

✅ **CDK does it all automatically!**

## Security Benefits

### Trust Policy (Who Can Assume the Role)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**This means:**
- ✅ Only ECS tasks can assume this role
- ✅ Not accessible from outside AWS
- ✅ Not accessible from other services
- ✅ Scoped to your account only

### Least Privilege

The role ONLY grants:
- `bedrock:InvokeModel` - Can invoke models
- `bedrock:InvokeModelWithResponseStream` - Can stream responses

**It CANNOT:**
- ❌ Create/delete Bedrock models
- ❌ Modify IAM policies
- ❌ Access other AWS services (S3, DynamoDB, etc.)
- ❌ Access other accounts

## Summary

### What CDK Creates Automatically

| Resource | Purpose | Permissions |
|----------|---------|-------------|
| **Task Execution Role** | ECS operations | ECR pull, CloudWatch logs |
| **Task Role** | Application runtime | Bedrock invoke only |

### Deployment Flow

```
cdk deploy CurateAI-ECS
    ↓
CloudFormation creates IAM roles
    ↓
ECS Task Definition references roles
    ↓
Fargate task starts with roles attached
    ↓
boto3 in your app automatically uses task role
    ↓
Bedrock API calls authenticated ✅
```

### Zero Configuration Needed

In your application code, you just need:

```python
import boto3

# That's it! The role is automatically used
client = boto3.client('bedrock-runtime', region_name='us-east-1')
```

**No access keys, no authentication code, no credential management!**

## Phase 3 Enhancement

In Phase 3, we'll add Secrets Manager access to the same task role:

```python
# Add to task role
self.task_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=["secretsmanager:GetSecretValue"],
        resources=[database_secret.secret_arn],
    )
)
```

This will allow:
- ✅ Bedrock access (existing)
- ✅ Database credentials from Secrets Manager (new)
- ✅ Still no hardcoded credentials anywhere

## Conclusion

**YES**, we absolutely create the IAM role with required permissions using CDK!

The `infrastructure/stacks/ecs_stack.py` file automatically creates:
1. IAM Task Role with Bedrock permissions
2. IAM Task Execution Role for ECS operations
3. Attaches both roles to the task definition

**You don't need to:**
- Create roles manually in AWS Console
- Configure AWS access keys
- Write any authentication code

**CDK handles everything** - just run `cdk deploy` and it works! 🎉
