"""OAuth 2.0 login flow with Google / Gmail."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config import settings
from ..db import get_pool
from ..deps import SESSION_COOKIE, CurrentUser, get_current_user
from ..security import create_session_token, encrypt
from ..services import gmail

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/start")
async def google_start():
    state = secrets.token_urlsafe(24)
    return {"url": gmail.build_consent_url(state)}


@router.get("/google/callback")
async def google_callback(code: str, request: Request):
    tokens = await gmail.exchange_code(code)
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    if not refresh_token:
        raise HTTPException(400, "No refresh token returned; revoke access and retry with prompt=consent.")

    info = await gmail.get_userinfo(access_token)
    google_email = info["email"]
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    pool = await get_pool()
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "insert into users (email, display_name) values ($1,$2) "
            "on conflict (email) do update set display_name=excluded.display_name returning id",
            google_email, info.get("name"),
        )
        account_id = await conn.fetchval(
            """
            insert into gmail_accounts
              (user_id, google_email, access_token_enc, refresh_token_enc, token_expiry)
            values ($1,$2,$3,$4,$5)
            on conflict (user_id, google_email) do update
              set access_token_enc=excluded.access_token_enc,
                  refresh_token_enc=excluded.refresh_token_enc,
                  token_expiry=excluded.token_expiry
            returning id
            """,
            user_id, google_email, encrypt(access_token), encrypt(refresh_token), expiry,
        )
        await conn.execute(
            "insert into sync_state (account_id, status) values ($1,'idle') "
            "on conflict (account_id) do nothing",
            account_id,
        )

    # Kick off the initial sync in the background.
    await request.app.state.arq.enqueue_job("sync_account", str(account_id), False)

    token = create_session_token(str(user_id), str(account_id))
    # Pass the token to the frontend in the URL fragment (#), which never reaches
    # the server/logs. The SPA reads it, stores it, and strips it from the URL.
    # Also set a cookie for convenient same-origin local dev.
    resp = RedirectResponse(url=f"{settings.frontend_origin}/#token={token}")
    resp.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        max_age=7 * 24 * 3600, secure=False,
    )
    return resp


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select google_email from gmail_accounts where id=$1", user.account_id
        )
    return {"account_id": user.account_id, "email": row["google_email"] if row else None}


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url=settings.frontend_origin, status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
