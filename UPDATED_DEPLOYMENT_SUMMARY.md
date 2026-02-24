# Updated Deployment - IAM Roles & Email Configuration

## ✅ Key Updates Applied

### 1. IAM Role-Based Bedrock Access (Security Best Practice)

**Changed from:**
- ❌ Hardcoded AWS access keys in environment variables
- ❌ Manual credential rotation required
- ❌ Risk of credential exposure

**Changed to:**
- ✅ IAM Task Role with Bedrock permissions
- ✅ Automatic credential management by AWS
- ✅ Zero credentials in code or environment variables
- ✅ AWS recommended security best practice

### 2. Email Configuration

**Alarm email set to:** `admin@noeticex.com`

All CloudWatch alarms and SNS notifications will be sent to this email address.

## How IAM Roles Work

### CDK Automatically Creates the Role

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

### Application Code (No Changes Needed)

Your application code in `app/agents/` and `app/services/` already uses boto3 correctly:


```python
import boto3

# boto3 automatically discovers and uses the ECS Task Role
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')

# Make API calls - authenticated via IAM role (no keys needed!)
response = bedrock_client.invoke_model(...)
```

## Updated Environment Variables

### Before (Removed)
```bash
export AWS_ACCESS_KEY_ID="your-key"          # ❌ REMOVED
export AWS_SECRET_ACCESS_KEY="your-secret"   # ❌ REMOVED
```

### After (Required)
```bash
export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="us-east-1"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"
export GITHUB_BRANCH="main"
export ALARM_EMAIL="admin@noeticex.com"  # Optional (defaults to this)
```

**That's it!** No AWS credentials needed for deployment.

## Files Updated

### Infrastructure Code
1. ✅ `infrastructure/stacks/ecs_stack.py`
   - Removed AWS credentials parameters
   - Added comments explaining IAM role usage
   - Environment variables no longer include access keys

2. ✅ `infrastructure/app.py`
   - Removed AWS credentials requirements
   - Updated email to `admin@noeticex.com`
   - Removed credential parameters from ECS stack instantiation

### Documentation
3. ✅ `infrastructure/README.md`
   - Removed AWS credentials from setup instructions
   - Added IAM role explanation
   - Updated email address

4. ✅ `infrastructure/QUICK_START.md`
   - Simplified environment variables (no credentials)
   - Updated email address
   - Added IAM role note

5. ✅ `infrastructure/DEPLOYMENT_CHECKLIST.md`
   - Removed credential setup steps
   - Updated email address
   - Added IAM role verification step

6. ✅ `PHASE_1_DEPLOYMENT_SUMMARY.md`
   - Removed "Hardcoded Credentials" limitation
   - Updated environment variables example
   - Added security benefits section

### New Documentation
7. ✅ `infrastructure/IAM_ROLES_EXPLAINED.md`
   - Complete guide to IAM roles vs access keys
   - How boto3 credential discovery works
   - Security benefits and best practices

8. ✅ `infrastructure/IAM_ROLE_SETUP.md`
   - Detailed walkthrough of CDK IAM role creation
   - Verification commands
   - Troubleshooting guide

## Deployment Changes

### What Changed
```bash
# OLD (removed)
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."

# NEW (just these)
export CDK_DEFAULT_ACCOUNT="558599919081"
export CDK_DEFAULT_REGION="us-east-1"
export GITHUB_OWNER="RishabhSinha07"
export GITHUB_REPO="CurateAI"
export ALARM_EMAIL="admin@noeticex.com"
```

### Deployment Command (Unchanged)
```bash
cd infrastructure
pip install -r requirements.txt
cdk deploy --all
```

## Verification After Deployment

### 1. Verify IAM Role Created
```bash
# List IAM roles
aws iam list-roles --query 'Roles[?contains(RoleName, `CurateAI`)].RoleName' --output table
```

### 2. Check Task Role Permissions
```bash
# Get task role ARN
TASK_ROLE=$(aws ecs describe-task-definition \
  --task-definition curateai-task \
  --query 'taskDefinition.taskRoleArn' \
  --output text | awk -F'/' '{print $NF}')

# View permissions
aws iam list-role-policies --role-name $TASK_ROLE
```

### 3. Test Application
```bash
# Get task public IP
# ... (see QUICK_START.md)

# Test health endpoint
curl http://<TASK_IP>:8000/health

# Test chat endpoint (uses Bedrock via IAM role)
curl -X POST http://<TASK_IP>:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}'
```

### 4. Check CloudWatch Logs
```bash
# Verify IAM role is being used
aws logs tail /ecs/curateai-app --follow | grep -i "credentials"
```

You should see:
```
Found credentials from IAM Role: CurateAI-ECS-TaskRole-XXXXX
```

## Security Improvements

| Aspect | Before | After |
|--------|--------|-------|
| **Credential Storage** | Environment variables | IAM role (none stored) |
| **Credential Rotation** | Manual | Automatic by AWS |
| **Exposure Risk** | High (can leak) | Zero (not visible) |
| **Audit Trail** | User identity | Task role identity |
| **Best Practice** | ❌ Not recommended | ✅ AWS recommended |

## Cost Impact

**No change** - IAM roles are free!

## Breaking Changes

**None!** - Your application code doesn't need any changes. boto3 automatically uses the IAM role.

## Local Development

For local testing (outside ECS), you still need AWS credentials:

```bash
# Option 1: AWS CLI (recommended)
aws configure

# Option 2: Environment variables (temporary)
export AWS_ACCESS_KEY_ID="your-dev-key"
export AWS_SECRET_ACCESS_KEY="your-dev-secret"

# Run locally
uvicorn app.main:app --reload
```

## Summary

✅ **More Secure:** No credentials in environment variables or code
✅ **Simpler:** Fewer environment variables to manage
✅ **AWS Best Practice:** Recommended approach for ECS workloads
✅ **Zero Changes:** Application code works without modification
✅ **Email Configured:** Alarms go to admin@noeticex.com
✅ **Production Ready:** Follows AWS security best practices

## Next Steps

1. **Deploy with simplified variables:**
   ```bash
   export CDK_DEFAULT_ACCOUNT="558599919081"
   export CDK_DEFAULT_REGION="us-east-1"
   export GITHUB_OWNER="RishabhSinha07"
   export GITHUB_REPO="CurateAI"

   cd infrastructure
   cdk deploy --all
   ```

2. **Verify IAM role creation** (see verification commands above)

3. **Test application** to confirm Bedrock access works via IAM role

4. **Check email** (`admin@noeticex.com`) for alarm subscription confirmation

5. **Proceed to Phase 2** when ready (database setup)

## Questions?

See detailed guides:
- `infrastructure/IAM_ROLES_EXPLAINED.md` - How IAM roles work
- `infrastructure/IAM_ROLE_SETUP.md` - CDK role creation details
- `infrastructure/QUICK_START.md` - Fast deployment guide
- `infrastructure/README.md` - Full deployment documentation
