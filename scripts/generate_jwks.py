"""
Generate RSA key pair and JWKS for a widget client.

Usage:
    python -m scripts.generate_jwks --kid key-1 --out-dir ./keys/rural-equip

Outputs:
    <out-dir>/private.pem     — Private key (give to customer, keep secret)
    <out-dir>/jwks.json       — JWKS file (host publicly at /.well-known/jwks.json)
    <out-dir>/sample_token.py — Sample Python script to mint JWTs
"""

import argparse
import base64
import json
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("ERROR: Install cryptography: pip install cryptography")
    sys.exit(1)


def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def int_to_base64url(n: int) -> str:
    """Convert an integer to base64url encoding."""
    byte_length = (n.bit_length() + 7) // 8
    return base64url_encode(n.to_bytes(byte_length, byteorder="big"))


def generate_keypair(kid: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate RSA 2048-bit key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()

    # Write private key PEM
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path = out_dir / "private.pem"
    private_path.write_bytes(private_pem)
    print(f"  Private key: {private_path}")

    # Build JWKS from public key
    pub_numbers = public_key.public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": int_to_base64url(pub_numbers.n),
                "e": int_to_base64url(pub_numbers.e),
            }
        ]
    }

    jwks_path = out_dir / "jwks.json"
    jwks_path.write_text(json.dumps(jwks, indent=2))
    print(f"  JWKS file:   {jwks_path}")

    # Write sample token generation script
    sample_script = f'''"""
Sample script to mint a CurateAI widget JWT.

Usage:
    pip install PyJWT cryptography
    python sample_token.py
"""
import time
import jwt  # PyJWT

PRIVATE_KEY = open("private.pem").read()

payload = {{
    "iss": "YOUR_DOMAIN",        # e.g., "ruralequip.in"
    "aud": "curateai",
    "sub": "user-123",            # Your user's ID
    "client_id": "YOUR_CLIENT_ID", # We provide this
    "iat": int(time.time()),
    "exp": int(time.time()) + 900, # 15 minutes
}}

token = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={{"kid": "{kid}"}})
print(token)
'''
    sample_path = out_dir / "sample_token.py"
    sample_path.write_text(sample_script)
    print(f"  Sample script: {sample_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate RSA key pair and JWKS for widget auth")
    parser.add_argument("--kid", default="key-1", help="Key ID for the JWKS (default: key-1)")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for keys (e.g., ./keys/rural-equip)",
    )
    args = parser.parse_args()

    print(f"Generating RSA-2048 key pair (kid={args.kid})...")
    generate_keypair(args.kid, Path(args.out_dir))
    print(f"\nDone! Next steps:")
    print(f"  1. Give private.pem to the customer (keep secret)")
    print(f"  2. Host jwks.json at https://DOMAIN/.well-known/jwks.json")
    print(f"  3. Register the client: python -m scripts.create_widget_client ...")


if __name__ == "__main__":
    main()
