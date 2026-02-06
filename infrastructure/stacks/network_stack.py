"""
Network Stack for CurateAI - Ultra Cost-Optimized

Creates:
- VPC with 2 AZs, public subnets only (no NAT Gateway)
- VPC Endpoints for AWS services (ECR, Bedrock, CloudWatch Logs)
- Security groups for Fargate tasks

Cost Savings:
- No NAT Gateway: Save $32/month
- VPC Endpoints instead: $7/month
- Total savings: ~$25/month
"""
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    Tags,
)
from constructs import Construct


class NetworkStack(Stack):
    """Network infrastructure stack with cost optimization."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # VPC - Public subnets only (no NAT Gateway)
        # ============================================
        self.vpc = ec2.Vpc(
            self,
            "CurateAI-VPC",
            vpc_name="CurateAI-VPC",
            max_azs=2,  # 2 AZs for high availability
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            # Public subnets only - Fargate tasks will use public IPs
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            # No NAT Gateway - save $32/month
            nat_gateways=0,
        )

        # ============================================
        # VPC Endpoints - $7/month instead of NAT Gateway
        # ============================================

        # ECR API Endpoint - for pulling Docker images
        self.ecr_api_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "ECR-API-Endpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.ECR,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # ECR Docker Endpoint - for pulling Docker layers
        self.ecr_docker_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "ECR-Docker-Endpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # S3 Gateway Endpoint - for ECR image layers (free)
        self.s3_endpoint = ec2.GatewayVpcEndpoint(
            self,
            "S3-Endpoint",
            vpc=self.vpc,
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        # CloudWatch Logs Endpoint - for container logs
        self.logs_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "CloudWatch-Logs-Endpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # Bedrock Runtime Endpoint - for AI model inference
        # Note: Bedrock may not have VPC endpoints in all regions
        # If not available, Fargate tasks will use public internet (no additional cost)
        try:
            self.bedrock_endpoint = ec2.InterfaceVpcEndpoint(
                self,
                "Bedrock-Runtime-Endpoint",
                vpc=self.vpc,
                service=ec2.InterfaceVpcEndpointService(
                    f"com.amazonaws.{self.region}.bedrock-runtime"
                ),
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            )
        except Exception:
            # Bedrock VPC endpoint not available in this region
            # Tasks will use public internet instead
            pass

        # ============================================
        # Security Groups
        # ============================================

        # Fargate Task Security Group - allows HTTP traffic from internet
        self.fargate_sg = ec2.SecurityGroup(
            self,
            "Fargate-SG",
            vpc=self.vpc,
            description="Security group for CurateAI Fargate tasks",
            allow_all_outbound=True,  # Allow outbound to AWS services
        )

        # Allow inbound HTTP traffic from anywhere (no ALB in Phase 1)
        self.fargate_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(8000),
            description="Allow HTTP traffic from internet",
        )

        # VPC Endpoint Security Group - allows traffic from Fargate
        self.vpc_endpoint_sg = ec2.SecurityGroup(
            self,
            "VPC-Endpoint-SG",
            vpc=self.vpc,
            description="Security group for VPC endpoints",
            allow_all_outbound=False,
        )

        # Allow HTTPS traffic from Fargate tasks to VPC endpoints
        self.vpc_endpoint_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(self.fargate_sg.security_group_id),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from Fargate tasks",
        )

        # Apply VPC endpoint security group to all endpoints
        for endpoint in [
            self.ecr_api_endpoint,
            self.ecr_docker_endpoint,
            self.logs_endpoint,
        ]:
            endpoint.connections.add_security_group(self.vpc_endpoint_sg)

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
