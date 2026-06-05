"""
Authentication Stack for CurateAI

Creates:
- AWS Cognito User Pool for admin/dashboard authentication
- DynamoDB table for widget client configs (JWKS URLs, origins)
- Lambda JWT authorizer for widget /chat endpoint
- API Gateway HTTP API with dual auth (Lambda for /chat, Cognito for admin)
- Direct integration with Fargate task (no ALB for cost optimization)

Flow:
Widget → API Gateway → Lambda Authorizer (JWT verify) → ECS Fargate
Dashboard → API Gateway → Cognito Authorizer → ECS Fargate

Note:
- No ALB to save ~$20/month
- API Gateway integrates directly with Fargate task
- Task IP changes on restart (requires stack update)
"""
from pathlib import Path

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_cognito as cognito,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_apigatewayv2_authorizers as authorizers,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
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
        # DynamoDB — Widget Client Configuration
        # ============================================

        self.widget_clients_table = dynamodb.Table(
            self,
            "WidgetClients",
            table_name="CurateAI-WidgetClients",
            partition_key=dynamodb.Attribute(
                name="client_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ============================================
        # Lambda — JWT Authorizer
        # ============================================

        lambda_dir = Path(__file__).parent.parent / "lambda" / "jwt-authorizer"

        self.jwt_authorizer_fn = _lambda.Function(
            self,
            "JWTAuthorizer",
            function_name="CurateAI-JWTAuthorizer",
            runtime=_lambda.Runtime.NODEJS_20_X,
            handler="index.handler",
            code=_lambda.Code.from_asset(str(lambda_dir)),
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "TABLE_NAME": self.widget_clients_table.table_name,
                "EXPECTED_AUD": "curateai",
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant Lambda read access to DynamoDB
        self.widget_clients_table.grant_read_data(self.jwt_authorizer_fn)

        # Lambda authorizer for API Gateway
        self.jwt_authorizer = authorizers.HttpLambdaAuthorizer(
            "JWTLambdaAuthorizer",
            self.jwt_authorizer_fn,
            response_types=[authorizers.HttpLambdaResponseType.SIMPLE],
            identity_source=["$request.header.Authorization"],
            results_cache_ttl=Duration.minutes(5),
        )

        # ============================================
        # AWS Cognito User Pool (admin/dashboard)
        # ============================================

        self.user_pool = cognito.UserPool(
            self,
            "CurateAI-UserPool",
            user_pool_name="CurateAI-Users",
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=True,
            ),
            self_sign_up_enabled=True,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                given_name=cognito.StandardAttribute(required=False, mutable=True),
                family_name=cognito.StandardAttribute(required=False, mutable=True),
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            email=cognito.UserPoolEmail.with_cognito(),
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.user_pool_client = self.user_pool.add_client(
            "CurateAI-Client",
            user_pool_client_name="CurateAI-API-Client",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
                admin_user_password=True,
            ),
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,
        )

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

        # Cognito authorizer for admin/dashboard routes
        self.cognito_authorizer = authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer",
            self.user_pool,
            user_pool_clients=[self.user_pool_client],
            identity_source=["$request.header.Authorization"],
        )

        # ============================================
        # API Gateway HTTP API
        # ============================================

        self.api = apigw.HttpApi(
            self,
            "CurateAI-API",
            api_name="CurateAI-API",
            description="CurateAI API with JWT + Cognito authentication",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "X-Amz-Date",
                    "X-Api-Key",
                ],
                max_age=Duration.days(1),
            ),
        )

        # ============================================
        # Route Integrations
        # ============================================

        health_integration = integrations.HttpUrlIntegration(
            "HealthIntegration",
            f"{backend_url}/health",
        )
        chat_integration = integrations.HttpUrlIntegration(
            "ChatIntegration",
            f"{backend_url}/chat",
        )
        events_integration = integrations.HttpUrlIntegration(
            "EventsIntegration",
            f"{backend_url}/events",
        )
        admin_products_integration = integrations.HttpUrlIntegration(
            "AdminProductsIntegration",
            f"{backend_url}/admin/products",
        )
        admin_keys_integration = integrations.HttpUrlIntegration(
            "AdminKeysIntegration",
            f"{backend_url}/admin/api-keys/rotate",
        )
        # Dashboard uses {proxy+} so all sub-paths (login, overview, traffic, ...)
        # forward to the backend. Auth is handled by FastAPI (self-signed JWT),
        # not by an API Gateway authorizer.
        dashboard_integration = integrations.HttpUrlIntegration(
            "DashboardIntegration",
            f"{backend_url}/admin/dashboard/{{proxy}}",
        )
        widget_config_integration = integrations.HttpUrlIntegration(
            "WidgetConfigIntegration",
            f"{backend_url}/widget/config",
        )

        # --- Public routes (no auth) ---
        self.api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=health_integration,
        )
        self.api.add_routes(
            path="/chat",
            methods=[apigw.HttpMethod.OPTIONS],
            integration=chat_integration,
        )
        self.api.add_routes(
            path="/widget/config",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.OPTIONS],
            integration=widget_config_integration,
        )

        # --- Widget route (Lambda JWT authorizer) ---
        self.api.add_routes(
            path="/chat",
            methods=[apigw.HttpMethod.POST],
            integration=chat_integration,
            authorizer=self.jwt_authorizer,
        )

        # --- Dashboard/admin routes (Cognito authorizer) ---
        self.api.add_routes(
            path="/events",
            methods=[apigw.HttpMethod.POST],
            integration=events_integration,
            authorizer=self.cognito_authorizer,
        )
        self.api.add_routes(
            path="/admin/products",
            methods=[apigw.HttpMethod.POST],
            integration=admin_products_integration,
            authorizer=self.cognito_authorizer,
        )
        self.api.add_routes(
            path="/admin/api-keys/rotate",
            methods=[apigw.HttpMethod.POST],
            integration=admin_keys_integration,
            authorizer=self.cognito_authorizer,
        )

        # --- Dashboard routes (FastAPI handles JWT auth, no API Gateway authorizer) ---
        self.api.add_routes(
            path="/admin/dashboard/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=dashboard_integration,
        )

        # Configure default stage throttle
        cfn_stage = self.api.default_stage.node.default_child
        cfn_stage.add_property_override(
            "DefaultRouteSettings.ThrottlingBurstLimit", 50
        )
        cfn_stage.add_property_override(
            "DefaultRouteSettings.ThrottlingRateLimit", 20
        )

        # ============================================
        # CloudWatch Logs
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
            description="API Gateway endpoint",
            export_name="CurateAI-APIEndpoint",
        )
        CfnOutput(
            self,
            "WidgetClientsTable",
            value=self.widget_clients_table.table_name,
            description="DynamoDB table for widget client configs",
        )
        CfnOutput(
            self,
            "JWTAuthorizerArn",
            value=self.jwt_authorizer_fn.function_arn,
            description="Lambda JWT authorizer ARN",
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
            description="Cognito User Pool Client ID",
            export_name="CurateAI-UserPoolClientId",
        )
        CfnOutput(
            self,
            "AdminUsername",
            value="admin",
            description="Admin username",
        )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
        Tags.of(self).add("Component", "Authentication")
