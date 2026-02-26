"""
Pipeline Stack for CurateAI CI/CD

Creates:
- CodePipeline from GitHub (private repo via CodeStar Connection)
- CodeBuild for Docker image builds
- ECS deployment stage

Workflow:
1. Source: GitHub repository (main branch)
2. Build: Docker build + push to ECR
3. Deploy: ECS blue/green deployment
"""
from aws_cdk import (
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as cpactions,
    aws_iam as iam,
    aws_ecr as ecr,
    aws_ecs as ecs,
    CfnOutput,
    Tags,
)
from constructs import Construct


class PipelineStack(Stack):
    """CI/CD pipeline stack for CurateAI application."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        ecr_repository: ecr.Repository,
        ecs_service: ecs.FargateService,
        github_owner: str,
        github_repo: str,
        github_branch: str = "main",
        codestar_connection_arn: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # CodeBuild Project
        # ============================================

        # Build environment for Docker
        build_environment = codebuild.BuildEnvironment(
            build_image=codebuild.LinuxBuildImage.STANDARD_7_0,  # Latest Ubuntu image
            privileged=True,  # Required for Docker builds
            compute_type=codebuild.ComputeType.SMALL,  # 3GB RAM, 2 vCPU (cost-optimized)
        )

        # CodeBuild project
        self.build_project = codebuild.PipelineProject(
            self,
            "CurateAI-Build",
            project_name="CurateAI-Build",
            description="Build Docker images for CurateAI",
            environment=build_environment,
            environment_variables={
                "ECR_REPOSITORY_URI": codebuild.BuildEnvironmentVariable(
                    value=ecr_repository.repository_uri
                ),
                "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(
                    value=self.region
                ),
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=self.account
                ),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "echo Logging in to Amazon ECR...",
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $ECR_REPOSITORY_URI",
                            "COMMIT_HASH=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)",
                            "IMAGE_TAG=${COMMIT_HASH:=latest}",
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Build started on `date`",
                            "echo Building Docker image...",
                            "docker build -f Dockerfile.prod -t $ECR_REPOSITORY_URI:latest .",
                            "docker tag $ECR_REPOSITORY_URI:latest $ECR_REPOSITORY_URI:$IMAGE_TAG",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Build completed on `date`",
                            "echo Pushing Docker images...",
                            "docker push $ECR_REPOSITORY_URI:latest",
                            "docker push $ECR_REPOSITORY_URI:$IMAGE_TAG",
                            "echo Writing image definitions file...",
                            'printf \'[{"name":"curateai-app","imageUri":"%s"}]\' $ECR_REPOSITORY_URI:latest > imagedefinitions.json',
                            "cat imagedefinitions.json",
                        ]
                    },
                },
                "artifacts": {
                    "files": ["imagedefinitions.json"]
                },
            }),
        )

        # Grant CodeBuild access to ECR
        ecr_repository.grant_pull_push(self.build_project)

        # ============================================
        # UpdateAPIGateway CodeBuild Project
        # ============================================

        self.update_api_gw_project = codebuild.PipelineProject(
            self,
            "CurateAI-UpdateAPIGW",
            project_name="CurateAI-UpdateAPIGW",
            description="Update API Gateway integrations with new Fargate task IP",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables={
                "CLUSTER_NAME": codebuild.BuildEnvironmentVariable(value="CurateAI-Cluster"),
                "SERVICE_NAME": codebuild.BuildEnvironmentVariable(value="CurateAI-Service"),
                "API_NAME":     codebuild.BuildEnvironmentVariable(value="CurateAI-API"),
            },
            build_spec=codebuild.BuildSpec.from_source_filename("buildspecs/update_api_gateway.yml"),
        )

        self.update_api_gw_project.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["ecs:ListTasks", "ecs:DescribeTasks"],
            resources=["*"],
        ))
        self.update_api_gw_project.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["ec2:DescribeNetworkInterfaces"],
            resources=["*"],
        ))
        self.update_api_gw_project.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["apigateway:GET", "apigateway:PATCH"],
            resources=["arn:aws:apigateway:*::/*"],
        ))

        # ============================================
        # Pipeline Artifacts
        # ============================================

        source_output = codepipeline.Artifact("SourceOutput")
        build_output = codepipeline.Artifact("BuildOutput")

        # ============================================
        # Pipeline Stages
        # ============================================

        # Source stage - GitHub
        source_action = cpactions.CodeStarConnectionsSourceAction(
            action_name="GitHub-Source",
            owner=github_owner,
            repo=github_repo,
            branch=github_branch,
            output=source_output,
            connection_arn=codestar_connection_arn or self._get_connection_arn_placeholder(),
        )

        # Build stage - CodeBuild
        build_action = cpactions.CodeBuildAction(
            action_name="Docker-Build",
            project=self.build_project,
            input=source_output,
            outputs=[build_output],
        )

        # Deploy stage - ECS
        deploy_action = cpactions.EcsDeployAction(
            action_name="ECS-Deploy",
            service=ecs_service,
            input=build_output,
        )

        # UpdateAPIGateway stage - patch integrations with new Fargate task IP
        update_api_gw_action = cpactions.CodeBuildAction(
            action_name="Update-APIGateway",
            project=self.update_api_gw_project,
            input=source_output,
        )

        # ============================================
        # Pipeline
        # ============================================

        self.pipeline = codepipeline.Pipeline(
            self,
            "CurateAI-Pipeline",
            pipeline_name="CurateAI-Pipeline",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[source_action],
                ),
                codepipeline.StageProps(
                    stage_name="Build",
                    actions=[build_action],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[deploy_action],
                ),
                codepipeline.StageProps(
                    stage_name="UpdateAPIGateway",
                    actions=[update_api_gw_action],
                ),
            ],
        )

        # ============================================
        # Outputs
        # ============================================

        CfnOutput(
            self,
            "PipelineName",
            value=self.pipeline.pipeline_name,
            description="CodePipeline name",
        )

        CfnOutput(
            self,
            "PipelineUrl",
            value=f"https://{self.region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/{self.pipeline.pipeline_name}/view",
            description="CodePipeline console URL",
        )

        if not codestar_connection_arn:
            CfnOutput(
                self,
                "CodeStarConnectionSetup",
                value="IMPORTANT: Create CodeStar connection and update pipeline. See deployment guide.",
                description="CodeStar connection setup reminder",
            )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")

    def _get_connection_arn_placeholder(self) -> str:
        """
        Return a placeholder ARN for CodeStar connection.
        User must create the connection manually and update the pipeline.
        """
        return f"arn:aws:codestar-connections:{self.region}:{self.account}:connection/PLACEHOLDER-UPDATE-ME"
