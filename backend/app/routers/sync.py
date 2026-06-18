"""Sync trigger + status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..db import get_pool
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("")
async def trigger_sync(
    request: Request,
    incremental: bool = True,
    user: CurrentUser = Depends(get_current_user),
):
    await request.app.state.arq.enqueue_job("sync_account", user.account_id, incremental)
    return {"queued": True, "incremental": incremental}


@router.get("/status")
async def sync_status(user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select status, phase, total_synced, last_synced_at, error "
            "from sync_state where account_id=$1",
            user.account_id,
        )
        counts = await conn.fetchrow(
            "select count(*) as emails, "
            "(select count(*) from email_embeddings where account_id=$1) as embedded "
            "from emails where account_id=$1",
            user.account_id,
        )
    return {
        "status": row["status"] if row else "idle",
        "phase": row["phase"] if row else None,
        "total_synced": row["total_synced"] if row else 0,
        "last_synced_at": row["last_synced_at"] if row else None,
        "error": row["error"] if row else None,
        "emails": counts["emails"] if counts else 0,
        "embedded": counts["embedded"] if counts else 0,
    }
