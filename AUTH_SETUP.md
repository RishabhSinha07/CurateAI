# CurateAI Authentication Setup Guide

## Overview

CurateAI uses **AWS Cognito** for user authentication and **API Gateway** as the secure entry point. All API requests require a valid JWT token from Cognito.

## Architecture

```
Client → API Gateway (auth check) → ALB → ECS Fargate
         ↓
      Cognito (JWT validation)
```

## Quick Start

### 1. Get Your API Endpoint

After deploying the auth stack, get your API Gateway endpoint:

```bash
aws cloudformation describe-stacks \
  --stack-name CurateAI-Auth \
  --query 'Stacks[0].Outputs[?OutputKey==`APIEndpoint`].OutputValue' \
  --output text
```

**Example:** `https://abc123.execute-api.us-east-1.amazonaws.com`

### 2. Get Cognito Configuration

```bash
# User Pool ID
aws cloudformation describe-stacks \
  --stack-name CurateAI-Auth \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text

# Client ID
aws cloudformation describe-stacks \
  --stack-name CurateAI-Auth \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text
```

Save these values - you'll need them for authentication.

### 3. Set Admin Password

The admin user was created automatically with username `admin` and email `admin@noeticex.com`.

**Set initial password:**

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id <YOUR_USER_POOL_ID> \
  --username admin \
  --password '<YourSecurePassword123!>' \
  --permanent
```

## Authentication Flow

### Option 1: Using AWS CLI (Testing)

#### Step 1: Sign In and Get Tokens

```bash
# Set variables
USER_POOL_ID="us-east-1_xxxxx"
CLIENT_ID="xxxxxxxxxxxxxxxxxxxxx"
USERNAME="admin"
PASSWORD="YourSecurePassword123!"

# Authenticate
aws cognito-idp admin-initiate-auth \
  --user-pool-id $USER_POOL_ID \
  --client-id $CLIENT_ID \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=$USERNAME,PASSWORD=$PASSWORD \
  --query 'AuthenticationResult.IdToken' \
  --output text
```

**Save the ID Token** - this is your JWT authentication token.

#### Step 2: Call API with Token

```bash
# Set your token
ID_TOKEN="eyJraWQ..."

# Set API endpoint
API_ENDPOINT="https://abc123.execute-api.us-east-1.amazonaws.com"

# Test health endpoint (no auth required)
curl $API_ENDPOINT/health

# Test chat endpoint (requires auth)
curl -X POST $API_ENDPOINT/chat \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "I have dark spots on my face"}'
```

### Option 2: Using Python SDK

```python
import boto3
import requests

# Initialize Cognito client
client = boto3.client('cognito-idp', region_name='us-east-1')

# Authenticate
response = client.admin_initiate_auth(
    UserPoolId='us-east-1_xxxxx',
    ClientId='xxxxxxxxxxxxxxxxxxxxx',
    AuthFlow='ADMIN_USER_PASSWORD_AUTH',
    AuthParameters={
        'USERNAME': 'admin',
        'PASSWORD': 'YourSecurePassword123!'
    }
)

# Get ID token
id_token = response['AuthenticationResult']['IdToken']

# Call API
api_endpoint = "https://abc123.execute-api.us-east-1.amazonaws.com"
headers = {
    'Authorization': f'Bearer {id_token}',
    'Content-Type': 'application/json'
}

# Make authenticated request
response = requests.post(
    f"{api_endpoint}/chat",
    headers=headers,
    json={"message": "I have dark spots on my face"}
)

print(response.json())
```

### Option 3: Using JavaScript/TypeScript

```javascript
import { CognitoIdentityProviderClient, AdminInitiateAuthCommand } from "@aws-sdk/client-cognito-identity-provider";

const client = new CognitoIdentityProviderClient({ region: "us-east-1" });

// Authenticate
const command = new AdminInitiateAuthCommand({
  UserPoolId: "us-east-1_xxxxx",
  ClientId: "xxxxxxxxxxxxxxxxxxxxx",
  AuthFlow: "ADMIN_USER_PASSWORD_AUTH",
  AuthParameters: {
    USERNAME: "admin",
    PASSWORD: "YourSecurePassword123!"
  }
});

const response = await client.send(command);
const idToken = response.AuthenticationResult.IdToken;

// Call API
const apiResponse = await fetch("https://abc123.execute-api.us-east-1.amazonaws.com/chat", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${idToken}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({ message: "I have dark spots on my face" })
});

const data = await apiResponse.json();
console.log(data);
```

## User Management

### Create New User

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username newuser \
  --user-attributes Name=email,Value=user@example.com \
  --temporary-password 'TempPassword123!' \
  --message-action SUPPRESS
```

### Set Permanent Password

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id <USER_POOL_ID> \
  --username newuser \
  --password 'NewSecurePassword123!' \
  --permanent
```

### List Users

```bash
aws cognito-idp list-users \
  --user-pool-id <USER_POOL_ID>
```

### Delete User

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id <USER_POOL_ID> \
  --username username-to-delete
```

## Security Configuration

### Password Policy

The default password policy requires:
- Minimum 8 characters
- At least one lowercase letter
- At least one uppercase letter
- At least one number
- At least one special character

### Token Expiration

- **ID Token:** 1 hour
- **Access Token:** 1 hour
- **Refresh Token:** 30 days

### Rate Limiting

API Gateway throttling limits:
- **Burst:** 100 concurrent requests
- **Rate:** 50 requests/second

## Troubleshooting

### 401 Unauthorized Error

**Problem:** API returns 401 Unauthorized

**Solutions:**
1. Check token is valid and not expired
2. Ensure token is included in `Authorization: Bearer <token>` header
3. Verify you're using the **ID Token** (not Access Token)
4. Check token format: `eyJraWQ...` (starts with `eyJ`)

### Token Expired

**Problem:** Token expired after 1 hour

**Solution:** Use refresh token to get new tokens:

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id <USER_POOL_ID> \
  --client-id <CLIENT_ID> \
  --auth-flow REFRESH_TOKEN_AUTH \
  --auth-parameters REFRESH_TOKEN=<YOUR_REFRESH_TOKEN>
```

### Cannot Access Health Endpoint

**Problem:** `/health` endpoint returns error

**Note:** The `/health` endpoint does NOT require authentication. If it fails:
1. Check ALB is healthy
2. Check ECS task is running
3. View ALB target health in AWS Console

### Wrong User Pool or Client ID

**Problem:** Authentication fails with "User pool does not exist"

**Solution:** Verify your User Pool ID and Client ID:

```bash
aws cloudformation describe-stacks --stack-name CurateAI-Auth \
  --query 'Stacks[0].Outputs[?contains(OutputKey, `UserPool`)].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

## Endpoints

### Public (No Auth Required)

- `GET /health` - Health check

### Protected (Auth Required)

- `POST /chat` - Chat with AI
- `GET /*` - All other endpoints require authentication

## Cost Impact

Adding authentication increases monthly costs by:

| Component | Monthly Cost |
|-----------|--------------|
| Application Load Balancer | $16-18 |
| API Gateway (HTTP API) | $1 per million requests + $0.10/GB |
| Cognito | Free tier: 50,000 MAUs, then $0.0055/MAU |
| **Total Added Cost** | **~$17-20/month** |

## Next Steps

1. **Set admin password** (see Step 3 above)
2. **Test authentication** with curl/Python/JavaScript
3. **Create additional users** as needed
4. **Update CORS origins** in API Gateway (currently `*`)
5. **Add custom domain** (optional, requires ACM certificate)
6. **Enable MFA** (optional, for enhanced security)

## Advanced Configuration

### Enable MFA

```bash
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id <USER_POOL_ID> \
  --mfa-configuration ON \
  --software-token-mfa-configuration Enabled=true
```

### Custom Domain (Requires Certificate)

1. Request ACM certificate for your domain
2. Update auth stack to add custom domain to API Gateway
3. Add CNAME record in your DNS

### IP Allowlisting

Update ALB security group to restrict access:

```bash
aws ec2 authorize-security-group-ingress \
  --group-id <ALB_SG_ID> \
  --protocol tcp \
  --port 80 \
  --cidr <YOUR_IP>/32
```

## Resources

- [AWS Cognito Documentation](https://docs.aws.amazon.com/cognito/)
- [API Gateway HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html)
- [JWT Tokens Explained](https://jwt.io/)

## Support

If authentication is not working:
1. Check CloudWatch logs for API Gateway: `/aws/apigateway/<API_ID>`
2. Check ALB access logs
3. Verify Cognito user status: `aws cognito-idp admin-get-user --user-pool-id <ID> --username admin`
