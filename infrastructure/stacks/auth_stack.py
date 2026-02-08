"""
Authentication Stack for CurateAI

Creates:
- AWS Cognito User Pool for user authentication
- API Gateway HTTP API with Cognito authorizer
- Direct integration with Fargate task (no ALB for cost optimization)

Flow:
Client → API Gateway (auth) → ECS Fargate (direct)

Security:
- Cognito JWT authentication required for all /chat endpoints
- HTTPS only (API Gateway provides TLS)
- Direct integration with Fargate public IP

Note:
- No ALB to save ~$20/month
- API Gateway integrates directly with Fargate task
- Task IP changes on restart (requires stack update)
"""
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_cognito as cognito,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_apigatewayv2_authorizers as authorizers,
    aws_logs as logs,
    RemovalPolicy,
    Tags,
)
from constructs import Construct


class AuthStack(Stack):
    """Authentication and API Gateway stack for CurateAI."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        backend_url: str,
        admin_email: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # AWS Cognito User Pool
        # ============================================

        # Cognito User Pool for authentication
        self.user_pool = cognito.UserPool(
            self,
            "CurateAI-UserPool",
            user_pool_name="CurateAI-Users",
            # Sign-in options
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=True,
            ),
            # Self-service sign-up
            self_sign_up_enabled=True,
            # Auto-verify email
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            # Password policy
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            # Standard attributes
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                given_name=cognito.StandardAttribute(required=False, mutable=True),
                family_name=cognito.StandardAttribute(required=False, mutable=True),
            ),
            # Account recovery
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            # Email settings
            email=cognito.UserPoolEmail.with_cognito(),
            # Removal policy
            removal_policy=RemovalPolicy.RETAIN,  # Keep user data on stack deletion
        )

        # User Pool Client for API access
        self.user_pool_client = self.user_pool.add_client(
            "CurateAI-Client",
            user_pool_client_name="CurateAI-API-Client",
            auth_flows=cognito.AuthFlow(
                user_password=True,  # Allow username/password auth
                user_srp=True,  # Secure Remote Password
                admin_user_password=True,  # Allow admin to create users
            ),
            # Token validity
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            # Prevent user existence errors
            prevent_user_existence_errors=True,
        )

        # Create admin user (will need to set password via console/CLI)
        self.admin_user = cognito.CfnUserPoolUser(
            self,
            "AdminUser",
            user_pool_id=self.user_pool.user_pool_id,
            username="admin",
            user_attributes=[
                cognito.CfnUserPoolUser.AttributeTypeProperty(
                    name="email",
                    value=admin_email,
                ),
            ],
            desired_delivery_mediums=["EMAIL"],
        )

        # ============================================
        # API Gateway HTTP API
        # ============================================

        # Cognito Authorizer for API Gateway
        self.authorizer = authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer",
            self.user_pool,
            user_pool_clients=[self.user_pool_client],
            identity_source=["$request.header.Authorization"],
        )

        # HTTP API (cheaper than REST API)
        self.api = apigw.HttpApi(
            self,
            "CurateAI-API",
            api_name="CurateAI-API",
            description="CurateAI API with Cognito authentication",
            # CORS configuration
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],  # TODO: Restrict to your domain
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Authorization", "Content-Type", "X-Amz-Date", "X-Api-Key"],
                max_age=Duration.days(1),
            ),
        )

        # Backend Integrations - create specific integration for each endpoint with full path

        # Health endpoint integration
        health_integration = integrations.HttpUrlIntegration(
            "HealthIntegration",
            f"{backend_url}/health",
        )

        # Chat endpoint integration
        chat_integration = integrations.HttpUrlIntegration(
            "ChatIntegration",
            f"{backend_url}/chat",
        )

        # Public routes (no auth required)
        # Health check
        self.api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=health_integration,
        )

        # OPTIONS for CORS preflight - must not have authorizer
        self.api.add_routes(
            path="/chat",
            methods=[apigw.HttpMethod.OPTIONS],
            integration=chat_integration,
        )

        # Protected routes (require Cognito auth)
        self.api.add_routes(
            path="/chat",
            methods=[apigw.HttpMethod.POST],
            integration=chat_integration,
            authorizer=self.authorizer,
        )

        # Note: Throttling for HTTP API should be configured via AWS Console or Usage Plans
        # Default throttling limits apply: 10,000 requests/second per account per region

        # ============================================
        # CloudWatch Logs for API Gateway
        # ============================================

        self.api_log_group = logs.LogGroup(
            self,
            "API-Logs",
            log_group_name=f"/aws/apigateway/{self.api.http_api_id}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================
        # Outputs
        # ============================================

        CfnOutput(
            self,
            "APIEndpoint",
            value=self.api.url or "N/A",
            description="API Gateway endpoint (use this instead of direct ECS access)",
            export_name="CurateAI-APIEndpoint",
        )

        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
            export_name="CurateAI-UserPoolId",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID (use for authentication)",
            export_name="CurateAI-UserPoolClientId",
        )

        CfnOutput(
            self,
            "AdminUsername",
            value="admin",
            description="Admin username (set password via AWS Console or CLI)",
        )

        CfnOutput(
            self,
            "AdminEmail",
            value=admin_email,
            description="Admin email for password reset",
        )

        CfnOutput(
            self,
            "AuthenticationGuide",
            value="See AUTH_SETUP.md for instructions on how to authenticate",
            description="Next steps",
        )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
        Tags.of(self).add("Component", "Authentication")
