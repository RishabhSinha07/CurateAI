#!/usr/bin/env python3
"""
Health check script for Docker container.
Used by Docker HEALTHCHECK and ECS health checks.
"""
import sys
import urllib.request
import json


def main():
    """Check if the application is healthy."""
    try:
        # Make HTTP request to health endpoint
        with urllib.request.urlopen("http://localhost:8000/health", timeout=5) as response:
            if response.status != 200:
                print(f"Health check failed: HTTP {response.status}", file=sys.stderr)
                sys.exit(1)

            # Parse JSON response
            data = json.loads(response.read().decode('utf-8'))

            # Verify expected response (accept "degraded" — fail-open for availability)
            if data.get("status") not in ("healthy", "degraded"):
                print(f"Health check failed: unexpected status {data}", file=sys.stderr)
                sys.exit(1)

            print("Health check passed")
            sys.exit(0)

    except Exception as e:
        print(f"Health check failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
