"""
Register a widget client in DynamoDB.

Usage:
    python -m scripts.create_widget_client \
        --client-id re_001 \
        --tenant-id 6a77550b-d69b-4f8c-ba73-6436aac988f9 \
        --jwks-url https://ruralequip.in/.well-known/jwks.json \
        --origins https://ruralequip.in,https://www.ruralequip.in \
        --iss ruralequip.in

Requires AWS credentials with DynamoDB write access.
"""

import argparse
import json
import sys

try:
    import boto3
except ImportError:
    print("ERROR: Install boto3: pip install boto3")
    sys.exit(1)

TABLE_NAME = "CurateAI-WidgetClients"
REGION = "us-east-1"


def create_client(
    client_id: str,
    tenant_id: str,
    jwks_url: str,
    origins: list[str],
    expected_iss: str,
    rate_limit_rpm: int = 60,
    theme: dict | None = None,
) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    item = {
        "client_id": client_id,
        "tenant_id": tenant_id,
        "jwks_url": jwks_url,
        "allowed_origins": origins,
        "expected_iss": expected_iss,
        "rate_limit_rpm": rate_limit_rpm,
        "is_active": True,
    }
    if theme:
        item["theme"] = theme

    table.put_item(Item=item)

    print(f"\nWidget client registered!")
    print(f"  client_id:    {client_id}")
    print(f"  tenant_id:    {tenant_id}")
    print(f"  jwks_url:     {jwks_url}")
    print(f"  origins:      {origins}")
    print(f"  iss:          {expected_iss}")
    print(f"  rate_limit:   {rate_limit_rpm} RPM")
    print(f"\nRequired JWT claims:")
    print(f'  {{')
    print(f'    "iss": "{expected_iss}",')
    print(f'    "aud": "curateai",')
    print(f'    "sub": "<user-id>",')
    print(f'    "client_id": "{client_id}",')
    print(f'    "exp": <unix-timestamp>,')
    print(f'  }}')
    print(f"\nWidget snippet:")
    print(f"  <script>")
    print(f"    window.CurateAIConfig = {{")
    print(f"      apiUrl: 'https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com',")
    print(f"      getAuthToken: async () => {{")
    print(f"        const res = await fetch('/api/curateai-token');")
    print(f"        const data = await res.json();")
    print(f"        return data.token;")
    print(f"      }},")
    print(f"    }};")
    print(f"  </script>")
    print(f'  <script src="https://curateai-widget.vercel.app/curateai-widget.js"></script>')


def main():
    parser = argparse.ArgumentParser(description="Register a CurateAI widget client")
    parser.add_argument("--client-id", required=True, help="Unique client ID (e.g., re_001)")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID from the tenants table")
    parser.add_argument("--jwks-url", required=True, help="Customer's JWKS endpoint URL")
    parser.add_argument(
        "--origins",
        required=True,
        help="Comma-separated allowed origins (e.g., https://ruralequip.in)",
    )
    parser.add_argument("--iss", required=True, help="Expected JWT issuer claim")
    parser.add_argument("--rpm", type=int, default=60, help="Rate limit RPM (default: 60)")
    parser.add_argument(
        "--theme",
        default=None,
        help=(
            "Theme as JSON string or @path/to/theme.json. Keys mirror the widget "
            'CurateAIWidgetConfig fields (e.g. {"primaryColor":"#A57548",'
            '"title":"Acme Help"}). Served by /widget/config to the widget at runtime.'
        ),
    )
    parser.add_argument(
        "--profile",
        default="CurateAI",
        help="AWS profile name (default: CurateAI)",
    )

    args = parser.parse_args()

    theme: dict | None = None
    if args.theme:
        raw = args.theme
        if raw.startswith("@"):
            with open(raw[1:], "r", encoding="utf-8") as f:
                raw = f.read()
        try:
            theme = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"ERROR: --theme is not valid JSON: {e}")
            sys.exit(1)
        if not isinstance(theme, dict):
            print("ERROR: --theme must be a JSON object")
            sys.exit(1)

    # Set AWS profile
    import os
    os.environ["AWS_PROFILE"] = args.profile

    create_client(
        client_id=args.client_id,
        tenant_id=args.tenant_id,
        jwks_url=args.jwks_url,
        origins=args.origins.split(","),
        expected_iss=args.iss,
        rate_limit_rpm=args.rpm,
        theme=theme,
    )


if __name__ == "__main__":
    main()
