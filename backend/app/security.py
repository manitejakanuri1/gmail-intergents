"""JWT session handling + at-rest encryption for OAuth tokens."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import jwt

from .config import settings

ALGORITHM = "HS256"
SESSION_TTL = timedelta(days=7)


def _fernet() -> Fernet:
    """Derive a valid Fernet key from the configured secret.

    Accepts any string; we hash it to a stable 32-byte urlsafe key so the
    operator does not have to generate a perfectly formatted Fernet key.
    """
    raw = settings.token_encryption_key or settings.app_jwt_secret
    digest = hashlib.sha256(raw.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt(value: bytes) -> str:
    return _fernet().decrypt(value).decode()


def create_session_token(user_id: str, account_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "account_id": account_id,
        "iat": now,
        "exp": now + SESSION_TTL,
    }
    return jwt.encode(payload, settings.app_jwt_secret, algorithm=ALGORITHM)


def decode_session_token(token: str) -> dict:
    return jwt.decode(token, settings.app_jwt_secret, algorithms=[ALGORITHM])
