"""Sync orchestration: initial backfill (paginated, resumable) and incremental
sync via the Gmail History API. Persists messages/threads, then enqueues
per-email enrichment (categorize, summarize, embed).
"""
from __future__ import annotations

import httpx

from ..db import get_pool
from .accounts import get_gmail_client
from .parsing import parse_message

# How many messages to pull on the very first sync. Set high to backfill the
# whole inbox; pagination + bounded concurrency keep this safe for large inboxes.
INITIAL_LIMIT = 500


async def _upsert_message(conn, account_id: str, parsed: dict) -> str | None:
    """Insert thread + email rows. Returns email_id if newly inserted."""
    thread_id = await conn.fetchval(
        """
        insert into threads (account_id, gmail_thread_id, subject, last_message_at, message_count)
        values ($1, $2, $3, $4, 1)
        on conflict (account_id, gmail_thread_id) do update
          set last_message_at = greatest(threads.last_message_at, excluded.last_message_at),
              message_count = threads.message_count + 1,
              updated_at = now()
        returning id
        """,
        account_id, parsed["gmail_thread_id"], parsed["subject"], parsed["internal_date"],
    )

    email_id = await conn.fetchval(
        """
        insert into emails (
            account_id, thread_id, gmail_message_id, rfc822_message_id,
            from_email, from_name, to_emails, cc_emails, subject, snippet,
            body_text, body_html, internal_date, is_unread, label_ids
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        on conflict (account_id, gmail_message_id) do nothing
        returning id
        """,
        account_id, thread_id, parsed["gmail_message_id"], parsed["rfc822_message_id"],
        parsed["from_email"], parsed["from_name"], parsed["to_emails"], parsed["cc_emails"],
        parsed["subject"], parsed["snippet"], parsed["body_text"], parsed["body_html"],
        parsed["internal_date"], parsed["is_unread"], parsed["label_ids"],
    )
    return str(email_id) if email_id else None


async def run_initial_sync(account_id: str, enqueue) -> int:
    """Backfill recent messages. `enqueue(email_id)` schedules enrichment."""
    pool = await get_pool()
    client, _ = await get_gmail_client(account_id)
    synced = 0

    async with pool.acquire() as conn:
        await conn.execute(
            "insert into sync_state (account_id, status, phase) values ($1,'running','initial') "
            "on conflict (account_id) do update set status='running', phase='initial', error=null",
            account_id,
        )

    page_token: str | None = None
    new_email_ids: list[str] = []
    history_id: int | None = None

    async with httpx.AsyncClient(timeout=60) as http:
        # Mirror labels once.
        labels = await client.list_labels(http)
        async with pool.acquire() as conn:
            for lb in labels.get("labels", []):
                await conn.execute(
                    "insert into labels (account_id, gmail_label_id, name, type) values ($1,$2,$3,$4) "
                    "on conflict (account_id, gmail_label_id) do nothing",
                    account_id, lb["id"], lb.get("name", ""), lb.get("type"),
                )

        while synced < INITIAL_LIMIT:
            listing = await client.list_message_ids(http, page_token=page_token)
            ids = [m["id"] for m in listing.get("messages", [])]
            for mid in ids:
                if synced >= INITIAL_LIMIT:
                    break
                full = await client.get_message(http, mid)
                if history_id is None:
                    history_id = int(full.get("historyId", 0)) or None
                parsed = parse_message(full)
                async with pool.acquire() as conn:
                    email_id = await _upsert_message(conn, account_id, parsed)
                if email_id:
                    new_email_ids.append(email_id)
                synced += 1

            page_token = listing.get("nextPageToken")
            async with pool.acquire() as conn:
                await conn.execute(
                    "update sync_state set page_token=$2, total_synced=$3 where account_id=$1",
                    account_id, page_token, synced,
                )
            if not page_token:
                break

    async with pool.acquire() as conn:
        if history_id:
            await conn.execute(
                "update gmail_accounts set history_id=$2 where id=$1", account_id, history_id
            )
        await conn.execute(
            "update sync_state set status='done', phase='initial', last_synced_at=now(), "
            "page_token=null where account_id=$1",
            account_id,
        )

    for eid in new_email_ids:
        await enqueue(eid)
    return len(new_email_ids)


async def run_incremental_sync(account_id: str, enqueue) -> int:
    """Fetch only changes since the stored historyId."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        history_id = await conn.fetchval(
            "select history_id from gmail_accounts where id=$1", account_id
        )
    if not history_id:
        return await run_initial_sync(account_id, enqueue)

    client, _ = await get_gmail_client(account_id)
    new_email_ids: list[str] = []
    latest_history = history_id
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=60) as http:
        while True:
            try:
                hist = await client.history_list(http, history_id, page_token=page_token)
            except Exception:  # history too old/expired -> full resync
                return await run_initial_sync(account_id, enqueue)

            for record in hist.get("history", []):
                latest_history = max(latest_history, int(record.get("id", latest_history)))
                for added in record.get("messagesAdded", []):
                    mid = added["message"]["id"]
                    full = await client.get_message(http, mid)
                    parsed = parse_message(full)
                    async with pool.acquire() as conn:
                        email_id = await _upsert_message(conn, account_id, parsed)
                    if email_id:
                        new_email_ids.append(email_id)

            page_token = hist.get("nextPageToken")
            if not page_token:
                break

    async with pool.acquire() as conn:
        await conn.execute(
            "update gmail_accounts set history_id=$2 where id=$1", account_id, latest_history
        )
        await conn.execute(
            "update sync_state set status='done', phase='incremental', last_synced_at=now(), "
            "total_synced=total_synced+$2 where account_id=$1",
            account_id, len(new_email_ids),
        )

    for eid in new_email_ids:
        await enqueue(eid)
    return len(new_email_ids)
