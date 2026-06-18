"""Account/token helpers: fetch a ready-to-use GmailClient for an account,
refreshing the access token when it has expired.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..db import get_pool
from ..security import decrypt, encrypt
from .gmail import GmailClient, refresh_access_token


async def get_gmail_client(account_id: str) -> tuple[GmailClient, str]:
    """Return (client, google_email), refreshing the token if needed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select access_token_enc, refresh_token_enc, token_expiry, google_email "
            "from gmail_accounts where id = $1",
            account_id,
        )
    if not row:
        raise ValueError("account not found")

    access_token = decrypt(row["access_token_enc"])
    expiry = row["token_expiry"]
    now = datetime.now(timezone.utc)

    if expiry is None or expiry <= now + timedelta(seconds=60):
        refreshed = await refresh_access_token(decrypt(row["refresh_token_enc"]))
        access_token = refreshed["access_token"]
        new_expiry = now + timedelta(seconds=refreshed.get("expires_in", 3600))
        async with pool.acquire() as conn:
            await conn.execute(
                "update gmail_accounts set access_token_enc = $1, token_expiry = $2 where id = $3",
                encrypt(access_token), new_expiry, account_id,
            )

    return GmailClient(access_token), row["google_email"]
