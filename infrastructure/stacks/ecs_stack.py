"""
ECS Stack for CurateAI - Ultra Cost-Optimized (Phase 1)

Creates:
- ECR repository for Docker images
- ECS Cluster (Container Insights disabled)
- Fargate Task Definition (0.5 vCPU, 1GB RAM, Spot pricing)
- Fargate Service with public IP (no ALB)
- IAM roles for Bedrock access

Phase 1 Configuration:
- No database secrets (YAML-based graphs only)
- IAM Task Role for Bedrock permissions (secure, no access keys needed)
- 1 task minimum (no auto-scaling)
- Public IP assignment
- 3-day log retention

Cost Optimization:
- Fargate Spot: 70% savings
- 0.5 vCPU, 1GB RAM: Save $20-30/month
- No ALB: Save $20-25/month
- 1 task minimum: Save $30/month
- 3-day logs: Save $2/month
- Total: ~$9-12/month
"""
from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_logs as logs,
    aws_iam as iam,
    CfnOutput,
    RemovalPolicy,
    Tags,
)
from constructs import Construct


class EcsStack(Stack):
    """ECS infrastructure stack for CurateAI application."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        fargate_sg: ec2.SecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # ECR Repository
        # ============================================
        self.ecr_repository = ecr.Repository(
            self,
            "CurateAI-ECR",
            repository_name="curateai-app",
            removal_policy=RemovalPolicy.RETAIN,  # Keep images on stack deletion
            image_scan_on_push=True,  # Scan for vulnerabilities
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Keep last 10 images",
                    max_image_count=10,
                )
            ],
        )

        # ============================================
        # ECS Cluster
        # ============================================
        self.cluster = ecs.Cluster(
            self,
            "CurateAI-Cluster",
            vpc=vpc,
            cluster_name="CurateAI-Cluster",
            container_insights=False,  # Disable to save $1/month
        )

        # ============================================
        # CloudWatch Logs
        # ============================================
        self.log_group = logs.LogGroup(
            self,
            "CurateAI-Logs",
            log_group_name="/ecs/curateai-app",
            retention=logs.RetentionDays.THREE_DAYS,  # 3-day retention (cost-optimized)
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================
        # IAM Roles
        # ============================================

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

        # Task Role - for application runtime (Bedrock access)
        self.task_role = iam.Role(
            self,
            "Task-Role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # Allow Bedrock model invocation (foundation models + inference profiles, all regions)
        # Inference profiles may route to different regions, so we allow all regions
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                ],
            )
        )

        # ============================================
        # Fargate Task Definition (Ultra Cost-Optimized)
        # ============================================
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "CurateAI-Task",
            family="curateai-task",
            # 0.5 vCPU, 1GB RAM (save $20-30/month vs 1 vCPU, 2GB)
            cpu=512,  # 0.5 vCPU
            memory_limit_mib=1024,  # 1GB RAM
            execution_role=self.task_execution_role,
            task_role=self.task_role,
        )

        # Container definition
        self.container = self.task_definition.add_container(
            "CurateAI-Container",
            container_name="curateai-app",
            image=ecs.ContainerImage.from_ecr_repository(
                repository=self.ecr_repository,
                tag="latest",
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="curateai",
                log_group=self.log_group,
            ),
            environment={
                # Application settings
                "ENVIRONMENT": "production",
                "LOG_LEVEL": "INFO",
                "DEBUG": "false",
                # AWS Bedrock - Region for boto3 client
                # Note: AWS credentials are provided via IAM Task Role (no access keys needed)
                # Using us-east-2 for Bedrock (infrastructure is in us-east-1)
                "AWS_REGION": "us-east-2",
                "BEDROCK_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
                "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
                "EMBEDDING_DIMENSIONS": "1024",
                # Database - Phase 2: Neon PostgreSQL
                "DATABASE_URL": "postgresql+asyncpg://neondb_owner:npg_63rZkjATYsiQ@ep-green-moon-aia3mla2-pooler.c-4.us-east-1.aws.neon.tech/neondb",
                # Knowledge Graphs - Phase 2: Still using YAML (can migrate later)
                "USE_DB_GRAPHS": "false",
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python /app/scripts/healthcheck.py || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(40),
            ),
        )

        # Port mapping
        self.container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                protocol=ecs.Protocol.TCP,
            )
        )

        # ============================================
        # Fargate Service (No ALB - Public IP)
        # ============================================
        self.service = ecs.FargateService(
            self,
            "CurateAI-Service",
            cluster=self.cluster,
            task_definition=self.task_definition,
            service_name="CurateAI-Service",
            # Start with 0 tasks to allow Docker image push first
            # Will update to 1 after image is in ECR
            desired_count=0,
            # Fargate Spot for 70% cost savings
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT",
                    weight=1,
                )
            ],
            # Deploy to public subnets with public IP
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True,  # Required for public subnet without NAT
            security_groups=[fargate_sg],
            # Health check grace period
            health_check_grace_period=Duration.seconds(60),
            # Enable circuit breaker for safe deployments
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )

        # ============================================
        # Outputs
        # ============================================

        # Note: Task IP is dynamic and changes on restart
        # Users need to check ECS console for current IP
        CfnOutput(
            self,
            "ClusterName",
            value=self.cluster.cluster_name,
            description="ECS Cluster name",
        )

        CfnOutput(
            self,
            "ServiceName",
            value=self.service.service_name,
            description="ECS Service name",
        )

        CfnOutput(
            self,
            "ECRRepositoryUri",
            value=self.ecr_repository.repository_uri,
            description="ECR repository URI for Docker images",
        )

        CfnOutput(
            self,
            "TaskPublicIPNote",
            value="Check ECS Console for current task public IP (changes on restart)",
            description="Note about dynamic public IP",
        )

        CfnOutput(
            self,
            "APIEndpointPattern",
            value="http://<TASK_PUBLIC_IP>:8000",
            description="API endpoint pattern (replace with actual task IP)",
        )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
