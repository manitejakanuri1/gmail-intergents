"""ARQ background worker.

Jobs:
  - sync_account(account_id, incremental): run Gmail sync, then fan out enrich jobs
  - enrich_email(email_id): categorize + summarize + embed one email, refresh thread summary

Run with:  arq app.workers.tasks.WorkerSettings
"""
from __future__ import annotations

from arq.connections import RedisSettings

from ..config import settings
from ..db import close_pool, get_pool, to_vector_literal
from ..services import ai_nim, analyze, summarize, sync
from ..services.categorize import CATEGORIES
from ..services.parsing import chunk_text


async def _ensure_categories(conn, account_id: str) -> dict[str, str]:
    """Make sure the taxonomy rows exist for this account; return key -> id."""
    for key, label in CATEGORIES.items():
        await conn.execute(
            "insert into categories (account_id, key, label, is_system) values ($1,$2,$3,true) "
            "on conflict (account_id, key) do nothing",
            account_id, key, label.split(" — ")[0],
        )
    rows = await conn.fetch(
        "select id, key from categories where account_id=$1", account_id
    )
    return {r["key"]: str(r["id"]) for r in rows}


async def sync_account(ctx, account_id: str, incremental: bool = False) -> int:
    async def enqueue(email_id: str) -> None:
        await ctx["redis"].enqueue_job("enrich_email", email_id)

    if incremental:
        return await sync.run_incremental_sync(account_id, enqueue)
    return await sync.run_initial_sync(account_id, enqueue)


async def enrich_email(ctx, email_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        email = await conn.fetchrow(
            "select id, account_id, thread_id, subject, from_name, from_email, body_text, snippet "
            "from emails where id=$1",
            email_id,
        )
        if not email:
            return
        cats = await _ensure_categories(conn, str(email["account_id"]))

    sender = email["from_name"] or email["from_email"] or ""
    body = email["body_text"] or email["snippet"] or ""
    subject = email["subject"] or ""

    # 1. One structured call: category + priority + summary + action
    result = await analyze.analyze(subject, sender, body)
    category_id = cats.get(result["category"])
    summary = result["summary"] or email["snippet"] or ""

    async with pool.acquire() as conn:
        await conn.execute(
            "update emails set category_id=$2, summary=$3, summary_model=$4, "
            "priority=$5, action_item=$6, needs_action=$7 where id=$1",
            email_id, category_id, summary, settings.gemini_model,
            result["priority"], result["action"], result["needs_action"],
        )

    # 3. Embed chunks (subject + body) via NIM
    text = f"{subject}\n{body}".strip()
    chunks = chunk_text(text)
    if chunks:
        try:
            vectors = await ai_nim.embed(chunks, input_type="passage")
            async with pool.acquire() as conn:
                await conn.execute(
                    "delete from email_embeddings where email_id=$1", email_id
                )
                for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    await conn.execute(
                        "insert into email_embeddings "
                        "(account_id, email_id, thread_id, chunk_index, content, embedding) "
                        "values ($1,$2,$3,$4,$5,$6::vector)",
                        email["account_id"], email_id, email["thread_id"], idx,
                        chunk, to_vector_literal(vec),
                    )
        except Exception:  # noqa: BLE001
            pass

    # 4. Refresh thread-level summary (reduce over per-email summaries)
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "select subject from threads where id=$1", email["thread_id"]
        )
        msg_summaries = await conn.fetch(
            "select summary from emails where thread_id=$1 and summary is not null "
            "order by internal_date asc",
            email["thread_id"],
        )
    summaries = [r["summary"] for r in msg_summaries if r["summary"]]
    if summaries:
        try:
            thread_summary = (
                summaries[0]
                if len(summaries) == 1
                else await summarize.summarize_thread(thread["subject"] or "", summaries)
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    "update threads set summary=$2, summary_model=$3 where id=$1",
                    email["thread_id"], thread_summary, settings.gemini_model,
                )
        except Exception:  # noqa: BLE001
            pass


async def startup(ctx) -> None:
    await get_pool()


async def shutdown(ctx) -> None:
    await close_pool()


class WorkerSettings:
    functions = [sync_account, enrich_email]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5  # bounded concurrency keeps us under Gmail + AI rate limits
