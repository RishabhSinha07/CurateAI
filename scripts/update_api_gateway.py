#!/usr/bin/env python3
"""
Update API Gateway Backend URL After ECS Deployment

This script automatically:
1. Gets the current Fargate task public IP
2. Updates Auth stack with new backend URL
3. Tests the endpoints

Usage:
    python scripts/update_api_gateway.py
"""
import subprocess
import sys
import os


def run_command(cmd, check=True):
    """Run shell command and return output."""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


def main():
    print("=" * 60)
    print("  Update API Gateway After Deployment")
    print("=" * 60)
    print()

    REGION = "us-east-1"
    CLUSTER = "CurateAI-Cluster"
    SERVICE = "CurateAI-Service"

    # 1. Get current task IP
    print("1️⃣  Getting current Fargate task IP...")

    task_arn = run_command(
        f"aws ecs list-tasks --cluster {CLUSTER} --service-name {SERVICE} "
        f"--desired-status RUNNING --region {REGION} "
        f"--query 'taskArns[0]' --output text"
    )

    if not task_arn or task_arn == "None":
        print("❌ No running tasks found!")
        sys.exit(1)

    print(f"   Task ARN: {task_arn}")

    eni_id = run_command(
        f"aws ecs describe-tasks --cluster {CLUSTER} --tasks {task_arn} "
        f"--region {REGION} "
        f"--query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' "
        f"--output text"
    )

    current_ip = run_command(
        f"aws ec2 describe-network-interfaces --network-interface-ids {eni_id} "
        f"--region {REGION} "
        f"--query 'NetworkInterfaces[0].Association.PublicIp' --output text"
    )

    backend_url = f"http://{current_ip}:8000"
    print(f"✅ Current IP: {current_ip}")
    print(f"✅ Backend URL: {backend_url}")
    print()

    # 2. Test direct access
    print("2️⃣  Testing direct Fargate access...")
    health = run_command(f"curl -s {backend_url}/health", check=False)
    if "healthy" in health:
        print("✅ Fargate health check passed")
    else:
        print(f"⚠️  Fargate health response: {health}")
    print()

    # 3. Update API Gateway
    print("3️⃣  Updating API Gateway backend URL...")

    # Set environment variables
    os.environ["CDK_DEFAULT_ACCOUNT"] = "558599919081"
    os.environ["CDK_DEFAULT_REGION"] = REGION
    os.environ["BACKEND_URL"] = backend_url
    os.environ["ALARM_EMAIL"] = "admin@noeticex.com"
    os.environ["GITHUB_OWNER"] = "RishabhSinha07"
    os.environ["GITHUB_REPO"] = "CurateAI"

    # Deploy Auth stack
    os.chdir("infrastructure")
    result = subprocess.run(
        ["cdk", "deploy", "CurateAI-Auth", "--require-approval", "never"],
        capture_output=True,
        text=True,
    )
    os.chdir("..")

    if result.returncode == 0:
        print("✅ API Gateway updated successfully")
    else:
        print("❌ API Gateway update failed")
        print(result.stderr)
        sys.exit(1)
    print()

    # 4. Get API Gateway endpoint
    print("4️⃣  Getting API Gateway endpoint...")
    api_endpoint = run_command(
        f"aws apigatewayv2 get-apis --region {REGION} "
        f"--query 'Items[?Name==`CurateAI-API`].ApiEndpoint' --output text"
    )
    print(f"✅ API Endpoint: {api_endpoint}")
    print()

    # 5. Test API Gateway
    print("5️⃣  Testing API Gateway health...")
    api_health = run_command(f"curl -s {api_endpoint}/health", check=False)
    if "Welcome" in api_health or "healthy" in api_health:
        print("✅ API Gateway health check passed")
    else:
        print(f"⚠️  API Gateway response: {api_health}")
    print()

    # Summary
    print("=" * 60)
    print("  Update Complete!")
    print("=" * 60)
    print()
    print(f"✅ Fargate Task IP: {current_ip}")
    print(f"✅ Backend URL: {backend_url}")
    print(f"✅ API Endpoint: {api_endpoint}")
    print()
    print("Next steps:")
    print("1. Test chat endpoint with Cognito auth")
    print("2. Monitor logs: aws logs tail /ecs/curateai-app --follow")
    print()


if __name__ == "__main__":
    main()
