#!/usr/bin/env python3
"""
AWS CDK App for CurateAI - Phase 1 Deployment

Deploys CurateAI backend infrastructure to AWS Fargate with CI/CD.
Phase 1: Backend only (YAML-based knowledge graphs, no database)

Required Environment Variables:
- CDK_DEFAULT_ACCOUNT: AWS account ID
- CDK_DEFAULT_REGION: AWS region (default: us-east-1)
- GITHUB_OWNER: GitHub repository owner
- GITHUB_REPO: GitHub repository name
- GITHUB_BRANCH: GitHub branch (default: main)
- CODESTAR_CONNECTION_ARN: CodeStar connection ARN (optional, can create later)
- ALARM_EMAIL: Email for CloudWatch alarms (optional, default: admin@noeticex.com)

Usage:
    # Set environment variables
    export CDK_DEFAULT_ACCOUNT="558599919081"
    export CDK_DEFAULT_REGION="us-east-1"
    export GITHUB_OWNER="RishabhSinha07"
    export GITHUB_REPO="CurateAI"
    export GITHUB_BRANCH="main"
    export ALARM_EMAIL="admin@noeticex.com"  # Optional

    # Bootstrap CDK (first time only)
    cdk bootstrap aws://558599919081/us-east-1

    # Deploy all stacks
    cdk deploy --all

    # Deploy specific stack
    cdk deploy CurateAI-Network
"""
import os
from aws_cdk import App, Environment, Tags

from stacks.network_stack import NetworkStack
from stacks.ecs_stack import EcsStack
from stacks.pipeline_stack import PipelineStack
from stacks.observability_stack import ObservabilityStack


def get_env_var(name: str, default: str | None = None, required: bool = True) -> str:
    """Get environment variable with validation."""
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(
            f"Environment variable {name} is required. "
            f"Set it with: export {name}=<value>"
        )
    return value or ""


def main():
    """Main CDK app entry point."""
    app = App()

    # ============================================
    # Environment Configuration
    # ============================================

    # AWS Environment
    account = get_env_var("CDK_DEFAULT_ACCOUNT")
    region = get_env_var("CDK_DEFAULT_REGION", default="us-east-1")

    env = Environment(account=account, region=region)

    # GitHub Configuration
    github_owner = get_env_var("GITHUB_OWNER")
    github_repo = get_env_var("GITHUB_REPO")
    github_branch = get_env_var("GITHUB_BRANCH", default="main")

    # CodeStar Connection (optional - can create manually later)
    codestar_connection_arn = get_env_var(
        "CODESTAR_CONNECTION_ARN",
        default=None,
        required=False,
    )

    # Monitoring Configuration
    alarm_email = get_env_var("ALARM_EMAIL", default="admin@noeticex.com", required=False)

    # ============================================
    # Deploy Stacks
    # ============================================

    # Stack 1: Network Infrastructure
    network_stack = NetworkStack(
        app,
        "CurateAI-Network",
        env=env,
        description="Network infrastructure for CurateAI (VPC, subnets, security groups)",
    )

    # Stack 2: ECS Infrastructure (depends on Network)
    # Note: Uses IAM Task Role for Bedrock permissions (no access keys needed)
    ecs_stack = EcsStack(
        app,
        "CurateAI-ECS",
        vpc=network_stack.vpc,
        fargate_sg=network_stack.fargate_sg,
        env=env,
        description="ECS Fargate infrastructure for CurateAI (IAM role-based Bedrock access)",
    )
    ecs_stack.add_dependency(network_stack)

    # Stack 3: CI/CD Pipeline (depends on ECS)
    pipeline_stack = PipelineStack(
        app,
        "CurateAI-Pipeline",
        ecr_repository=ecs_stack.ecr_repository,
        ecs_service=ecs_stack.service,
        github_owner=github_owner,
        github_repo=github_repo,
        github_branch=github_branch,
        codestar_connection_arn=codestar_connection_arn,
        env=env,
        description="CI/CD pipeline for CurateAI (GitHub -> CodeBuild -> ECS)",
    )
    pipeline_stack.add_dependency(ecs_stack)

    # Stack 4: Observability (depends on ECS)
    observability_stack = ObservabilityStack(
        app,
        "CurateAI-Observability",
        cluster=ecs_stack.cluster,
        service=ecs_stack.service,
        log_group=ecs_stack.log_group,
        alarm_email=alarm_email,
        env=env,
        description="Monitoring and observability for CurateAI (CloudWatch, SNS)",
    )
    observability_stack.add_dependency(ecs_stack)

    # ============================================
    # Global Tags
    # ============================================

    Tags.of(app).add("Project", "CurateAI")
    Tags.of(app).add("Environment", "Production")
    Tags.of(app).add("ManagedBy", "CDK")
    Tags.of(app).add("Phase", "1")
    Tags.of(app).add("Repository", f"{github_owner}/{github_repo}")

    # Synthesize CloudFormation templates
    app.synth()


if __name__ == "__main__":
    main()
