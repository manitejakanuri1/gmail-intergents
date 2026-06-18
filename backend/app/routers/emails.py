"""List + read emails."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_pool
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/emails", tags=["emails"])


_PRIORITY_ORDER = (
    "case e.priority when 'urgent' then 1 when 'high' then 2 "
    "when 'medium' then 3 when 'low' then 4 else 5 end"
)


@router.get("")
async def list_emails(
    category: str | None = None,
    sort: str = "priority",  # 'priority' (default, for the dashboard) or 'date'
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    limit = min(limit, 100)
    order = (
        f"order by {_PRIORITY_ORDER}, e.internal_date desc nulls last"
        if sort == "priority"
        else "order by e.internal_date desc nulls last"
    )
    select = """
        select e.id, e.subject, e.from_name, e.from_email, e.snippet, e.summary,
               e.internal_date, e.is_unread, e.thread_id, c.key as category,
               e.priority, e.action_item, e.needs_action, t.message_count
        from emails e
        left join categories c on c.id = e.category_id
        join threads t on t.id = e.thread_id
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if category:
            rows = await conn.fetch(
                f"{select} where e.account_id=$1 and c.key=$2 {order} limit $3 offset $4",
                user.account_id, category, limit, offset,
            )
        else:
            rows = await conn.fetch(
                f"{select} where e.account_id=$1 {order} limit $2 offset $3",
                user.account_id, limit, offset,
            )
    return [dict(r) for r in rows]


@router.get("/{email_id}")
async def get_email(email_id: str, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select e.*, c.key as category from emails e "
            "left join categories c on c.id=e.category_id "
            "where e.id=$1 and e.account_id=$2",
            email_id, user.account_id,
        )
    if not row:
        raise HTTPException(404, "email not found")
    return dict(row)
