"""
Token encryption/decryption for official IDMC MCP Server.

Tokens are Fernet-encrypted blobs containing pod, username, and password.
The encryption key comes from the ENCRYPTION_KEY environment variable.
"""

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken


class TokenError(Exception):
    pass


def _get_fernet() -> Fernet:
    raw = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not raw:
        raise TokenError("ENCRYPTION_KEY environment variable is not set")
    try:
        return Fernet(raw.encode() if not isinstance(raw, bytes) else raw)
    except Exception:
        raise TokenError("ENCRYPTION_KEY is not a valid Fernet key")


def generate_key() -> str:
    """Generate a new random Fernet key. Run once at deploy time."""
    return Fernet.generate_key().decode()


def create_token(pod: str, username: str, password: str,
                 services: list = None) -> str:
    """Encrypt credentials into an opaque token string."""
    payload = json.dumps({
        "pod": pod,
        "username": username,
        "password": password,
        "services": services or [],  # empty list = all services enabled
    })
    return _get_fernet().encrypt(payload.encode()).decode()


def decode_token(token: str) -> dict:
    """Decrypt a token and return {"pod", "username", "password"}.

    Raises TokenError on any failure.
    """
    try:
        payload = _get_fernet().decrypt(token.encode())
        return json.loads(payload)
    except InvalidToken:
        raise TokenError("Invalid or expired token")
    except Exception as e:
        raise TokenError(f"Token decode failed: {e}")
