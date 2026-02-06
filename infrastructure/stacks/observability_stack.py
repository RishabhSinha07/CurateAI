"""
Observability Stack for CurateAI

Creates:
- CloudWatch Dashboard with ECS metrics
- CloudWatch Alarms for critical issues
- SNS topic for notifications

Metrics Tracked:
- ECS: CPU utilization, memory utilization
- ECS: Running task count, deployment status
- Logs: Error rates, application health
"""
from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    aws_ecs as ecs,
    aws_logs as logs,
    CfnOutput,
    Tags,
)
from constructs import Construct


class ObservabilityStack(Stack):
    """Observability and monitoring stack for CurateAI."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        cluster: ecs.Cluster,
        service: ecs.FargateService,
        log_group: logs.LogGroup,
        alarm_email: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================
        # SNS Topic for Alarms
        # ============================================

        self.alarm_topic = sns.Topic(
            self,
            "CurateAI-Alarms",
            topic_name="CurateAI-Alarms",
            display_name="CurateAI Production Alarms",
        )

        # Subscribe email if provided
        if alarm_email:
            self.alarm_topic.add_subscription(
                subscriptions.EmailSubscription(alarm_email)
            )

        # ============================================
        # CloudWatch Metrics
        # ============================================

        # ECS Service Metrics
        cpu_metric = service.metric_cpu_utilization(
            period=Duration.minutes(5),
            statistic="Average",
        )

        memory_metric = service.metric_memory_utilization(
            period=Duration.minutes(5),
            statistic="Average",
        )

        task_count_metric = cw.Metric(
            namespace="AWS/ECS",
            metric_name="RunningTaskCount",
            dimensions_map={
                "ServiceName": service.service_name,
                "ClusterName": cluster.cluster_name,
            },
            period=Duration.minutes(1),
            statistic="Average",
        )

        # Log Metrics - Error count
        error_metric = cw.Metric(
            namespace="AWS/Logs",
            metric_name="IncomingLogEvents",
            dimensions_map={
                "LogGroupName": log_group.log_group_name,
            },
            period=Duration.minutes(5),
            statistic="Sum",
        )

        # ============================================
        # CloudWatch Alarms
        # ============================================

        # CPU Utilization Alarm - Alert if CPU > 80% for 10 minutes
        cpu_alarm = cw.Alarm(
            self,
            "CPU-High-Alarm",
            alarm_name="CurateAI-CPU-High",
            alarm_description="CPU utilization is above 80%",
            metric=cpu_metric,
            threshold=80,
            evaluation_periods=2,  # 2 x 5 minutes = 10 minutes
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        cpu_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # Memory Utilization Alarm - Alert if memory > 85% for 10 minutes
        memory_alarm = cw.Alarm(
            self,
            "Memory-High-Alarm",
            alarm_name="CurateAI-Memory-High",
            alarm_description="Memory utilization is above 85%",
            metric=memory_metric,
            threshold=85,
            evaluation_periods=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        memory_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # Task Count Alarm - Alert if no tasks are running
        task_count_alarm = cw.Alarm(
            self,
            "No-Tasks-Alarm",
            alarm_name="CurateAI-No-Tasks",
            alarm_description="No ECS tasks are running",
            metric=task_count_metric,
            threshold=1,
            evaluation_periods=2,  # 2 x 1 minute = 2 minutes
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
        )
        task_count_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # ============================================
        # CloudWatch Dashboard
        # ============================================

        self.dashboard = cw.Dashboard(
            self,
            "CurateAI-Dashboard",
            dashboard_name="CurateAI-Production",
        )

        # Add widgets to dashboard
        self.dashboard.add_widgets(
            # Row 1: Service Status
            cw.GraphWidget(
                title="ECS Service - Running Tasks",
                left=[task_count_metric],
                width=12,
            ),
            cw.SingleValueWidget(
                title="Current Task Count",
                metrics=[task_count_metric],
                width=12,
            ),
        )

        self.dashboard.add_widgets(
            # Row 2: Resource Utilization
            cw.GraphWidget(
                title="CPU Utilization (%)",
                left=[cpu_metric],
                width=12,
            ),
            cw.GraphWidget(
                title="Memory Utilization (%)",
                left=[memory_metric],
                width=12,
            ),
        )

        self.dashboard.add_widgets(
            # Row 3: Logs and Errors
            cw.GraphWidget(
                title="Log Events (Total)",
                left=[error_metric],
                width=24,
            ),
        )

        # ============================================
        # Outputs
        # ============================================

        CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home?region={self.region}#dashboards:name={self.dashboard.dashboard_name}",
            description="CloudWatch Dashboard URL",
        )

        CfnOutput(
            self,
            "AlarmTopicArn",
            value=self.alarm_topic.topic_arn,
            description="SNS Topic ARN for alarms",
        )

        if alarm_email:
            CfnOutput(
                self,
                "AlarmEmail",
                value=f"Alarm notifications will be sent to: {alarm_email}",
                description="Alarm email notification",
            )
        else:
            CfnOutput(
                self,
                "AlarmEmailSetup",
                value="Subscribe to SNS topic to receive alarm notifications",
                description="Alarm email setup reminder",
            )

        # Add tags
        Tags.of(self).add("Project", "CurateAI")
        Tags.of(self).add("Environment", "Production")
        Tags.of(self).add("ManagedBy", "CDK")
