"""Thread listing + full thread view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_pool
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}")
async def get_thread(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "select id, subject, summary, message_count, last_message_at "
            "from threads where id=$1 and account_id=$2",
            thread_id, user.account_id,
        )
        if not thread:
            raise HTTPException(404, "thread not found")
        messages = await conn.fetch(
            "select id, from_name, from_email, to_emails, subject, body_text, summary, "
            "internal_date, rfc822_message_id from emails "
            "where thread_id=$1 order by internal_date asc",
            thread_id,
        )
    return {"thread": dict(thread), "messages": [dict(m) for m in messages]}
