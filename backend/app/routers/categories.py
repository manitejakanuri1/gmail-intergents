"""Category list with per-category email counts (for the sidebar)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import get_pool
from ..deps import CurrentUser, get_current_user
from ..services.categorize import CATEGORIES

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
async def list_categories(user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            select c.key, c.label, count(e.id) as count
            from categories c
            left join emails e on e.category_id = c.id and e.account_id = $1
            where c.account_id = $1
            group by c.key, c.label
            """,
            user.account_id,
        )
    found = {r["key"]: dict(r) for r in rows}
    # Always return the full taxonomy, even before enrichment has populated counts.
    return [
        found.get(key, {"key": key, "label": label.split(" — ")[0], "count": 0})
        for key, label in CATEGORIES.items()
    ]
