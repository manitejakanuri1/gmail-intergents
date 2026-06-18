"""Shared FastAPI dependencies (auth)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, status

from .db import get_pool
from .security import decode_session_token

SESSION_COOKIE = "session"


@dataclass
class CurrentUser:
    user_id: str
    account_id: str


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: str | None = Cookie(default=None),
) -> CurrentUser:
    """Authenticate via Bearer token (works cross-domain in production) or, as a
    fallback, the session cookie (convenient for same-origin local dev)."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif session:
        token = session
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_session_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    return CurrentUser(user_id=payload["sub"], account_id=payload["account_id"])


async def db_pool(_=Depends(lambda: None)):
    return await get_pool()
