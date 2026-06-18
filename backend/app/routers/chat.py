"""AI chat agent endpoints (RAG over the user's emails)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_pool
from ..deps import CurrentUser, get_current_user
from ..services import rag

router = APIRouter(prefix="/chat", tags=["chat"])


class AskReq(BaseModel):
    session_id: str | None = None
    message: str


@router.post("/ask")
async def ask(req: AskReq, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        session_id = req.session_id
        if session_id:
            owner = await conn.fetchval(
                "select 1 from chat_sessions where id=$1 and account_id=$2",
                session_id, user.account_id,
            )
            if not owner:
                raise HTTPException(404, "session not found")
        else:
            session_id = str(
                await conn.fetchval(
                    "insert into chat_sessions (account_id, title) values ($1,$2) returning id",
                    user.account_id, req.message[:60],
                )
            )
        history = [
            dict(r)
            for r in await conn.fetch(
                "select role, content from chat_messages where session_id=$1 "
                "order by created_at asc limit 12",
                session_id,
            )
        ]

    result = await rag.answer(user.account_id, history, req.message)

    async with pool.acquire() as conn:
        await conn.execute(
            "insert into chat_messages (session_id, role, content) values ($1,'user',$2)",
            session_id, req.message,
        )
        await conn.execute(
            "insert into chat_messages (session_id, role, content, sources) "
            "values ($1,'assistant',$2,$3::jsonb)",
            session_id, result["answer"], rag.sources_to_json(result["sources"]),
        )

    return {"session_id": session_id, "answer": result["answer"], "sources": result["sources"]}


@router.get("/sessions")
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select id, title, created_at from chat_sessions where account_id=$1 "
            "order by created_at desc limit 50",
            user.account_id,
        )
    return [dict(r) for r in rows]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "select 1 from chat_sessions where id=$1 and account_id=$2",
            session_id, user.account_id,
        )
        if not owner:
            raise HTTPException(404, "session not found")
        rows = await conn.fetch(
            "select role, content, sources, created_at from chat_messages "
            "where session_id=$1 order by created_at asc",
            session_id,
        )
    return [dict(r) for r in rows]
