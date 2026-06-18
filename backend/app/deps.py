"""Shared FastAPI dependencies (auth)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, status

from .db import get_pool
from .security import decode_session_token

SESSION_COOKIE = "session"


@dataclass
class CurrentUser:
    user_id: str
    account_id: str


async def get_current_user(session: str | None = Cookie(default=None)) -> CurrentUser:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_session_token(session)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    return CurrentUser(user_id=payload["sub"], account_id=payload["account_id"])


async def db_pool(_=Depends(lambda: None)):
    return await get_pool()
