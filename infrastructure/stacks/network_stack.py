"""
Network Stack for CurateAI

Creates:
- VPC with 2 AZs, public subnets only (no NAT Gateway)
- Security groups for Fargate tasks

Fargate tasks have public IPs and reach AWS services (ECR, CloudWatch,
Bedrock) over the internet gateway — no VPC endpoints or NAT needed.
"""
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    Tags,
)
from constructs import Construct


class NetworkStack(Stack):
    """Network infrastructure stack for CurateAI."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # VPC - Public subnets only (no NAT Gateway)
        # ============================================
        self.vpc = ec2.Vpc(
            self,
            "CurateAI-VPC",
            vpc_name="CurateAI-VPC",
            max_azs=2,
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            nat_gateways=0,
        )

        # ============================================
        # Security Groups
        # ============================================

        # Fargate Task Security Group
        self.fargate_sg = ec2.SecurityGroup(
            self,
            "Fargate-SG",
            vpc=self.vpc,
            description="Security group for CurateAI Fargate tasks",
            allow_all_outbound=True,
        )

        self.fargate_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(8000),
            description="Allow HTTP traffic from internet",
        )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
