"""
Network Stack for CurateAI

Creates:
- VPC with 2 AZs, public subnets only (no NAT Gateway)
- IPv6 support (required for Supabase direct connections)
- Security groups for Fargate tasks

Fargate tasks have public IPs and reach AWS services (ECR, CloudWatch,
Bedrock) over the internet gateway — no VPC endpoints or NAT needed.
"""
from aws_cdk import (
    Fn,
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
        # IPv6 Support
        # Supabase direct connections resolve to IPv6 only.
        # ============================================

        # Add Amazon-provided IPv6 CIDR to the VPC
        ipv6_cidr = ec2.CfnVPCCidrBlock(
            self,
            "VPC-IPv6-CIDR",
            vpc_id=self.vpc.vpc_id,
            amazon_provided_ipv6_cidr_block=True,
        )

        # Assign IPv6 CIDR to each public subnet and enable auto-assign
        for i, subnet in enumerate(self.vpc.public_subnets):
            cfn_subnet = subnet.node.default_child

            # Slice a /64 from the VPC's /56 for each subnet
            cfn_subnet.ipv6_cidr_block = Fn.select(
                i,
                Fn.cidr(
                    Fn.select(0, self.vpc.vpc_ipv6_cidr_blocks),
                    256,  # up to 256 /64 subnets in a /56
                    "64",
                ),
            )
            cfn_subnet.add_dependency(ipv6_cidr)

            # Auto-assign IPv6 addresses to instances/tasks in this subnet
            cfn_subnet.assign_ipv6_address_on_creation = True

            # Add IPv6 route (::/0 → IGW) to the subnet's route table
            ec2.CfnRoute(
                self,
                f"IPv6-Route-{i}",
                route_table_id=subnet.route_table.route_table_id,
                destination_ipv6_cidr_block="::/0",
                gateway_id=self.vpc.internet_gateway_id,
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

        self.fargate_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv6(),
            connection=ec2.Port.tcp(8000),
            description="Allow HTTP traffic from internet (IPv6)",
        )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
