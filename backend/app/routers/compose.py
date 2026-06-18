"""Compose new emails and thread-aware replies from short prompts."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_pool
from ..deps import CurrentUser, get_current_user
from ..services import ai_gemini, gmail
from ..services.accounts import get_gmail_client

router = APIRouter(prefix="/compose", tags=["compose"])

_COMPOSE_SYS = (
    "You draft professional emails from a short instruction. Return the email body only "
    "(no subject line, no preamble). Keep it clear and appropriately concise."
)
_SUBJECT_SYS = "Write a short, specific email subject line for this instruction. Subject only."
_REPLY_SYS = (
    "You draft a reply to an email thread. You are given the prior messages and an "
    "instruction. Write only the reply body, responding appropriately to what was said. "
    "No subject line, no preamble."
)


class ComposeReq(BaseModel):
    prompt: str


class ComposeDraft(BaseModel):
    subject: str
    body: str


@router.post("/draft", response_model=ComposeDraft)
async def compose_draft(req: ComposeReq, user: CurrentUser = Depends(get_current_user)):
    body = await ai_gemini.generate(req.prompt, system=_COMPOSE_SYS, temperature=0.4, max_output_tokens=600)
    subject = await ai_gemini.generate(req.prompt, system=_SUBJECT_SYS, temperature=0.3, max_output_tokens=40)
    return ComposeDraft(subject=subject.strip().strip('"'), body=body)


class ReplyReq(BaseModel):
    thread_id: str
    prompt: str


@router.post("/reply/draft", response_model=ComposeDraft)
async def reply_draft(req: ReplyReq, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "select subject from threads where id=$1 and account_id=$2",
            req.thread_id, user.account_id,
        )
        if not thread:
            raise HTTPException(404, "thread not found")
        msgs = await conn.fetch(
            "select from_name, from_email, body_text, summary from emails "
            "where thread_id=$1 order by internal_date asc",
            req.thread_id,
        )
    context = "\n\n".join(
        f"From: {m['from_name'] or m['from_email']}\n{(m['body_text'] or m['summary'] or '')[:1500]}"
        for m in msgs
    )
    prompt = f"Thread so far:\n{context}\n\nInstruction: {req.prompt}\n\nReply:"
    body = await ai_gemini.generate(prompt, system=_REPLY_SYS, temperature=0.4, max_output_tokens=600)
    subject = thread["subject"] or ""
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return ComposeDraft(subject=subject, body=body)


class SendReq(BaseModel):
    to: str
    subject: str
    body: str
    thread_id: str | None = None
    reply_to_email_id: str | None = None


@router.post("/send")
async def send_email(req: SendReq, user: CurrentUser = Depends(get_current_user)):
    pool = await get_pool()
    in_reply_to = references = gmail_thread_id = None

    if req.reply_to_email_id:
        async with pool.acquire() as conn:
            target = await conn.fetchrow(
                "select e.rfc822_message_id, t.gmail_thread_id from emails e "
                "join threads t on t.id=e.thread_id where e.id=$1 and e.account_id=$2",
                req.reply_to_email_id, user.account_id,
            )
        if target:
            in_reply_to = target["rfc822_message_id"]
            references = target["rfc822_message_id"]
            gmail_thread_id = target["gmail_thread_id"]

    client, google_email = await get_gmail_client(user.account_id)
    raw = gmail.build_mime(
        to=req.to, subject=req.subject, body=req.body, from_email=google_email,
        in_reply_to=in_reply_to, references=references,
    )
    async with httpx.AsyncClient(timeout=30) as http:
        result = await client.send_message(http, raw, thread_id=gmail_thread_id)
    return {"sent": True, "id": result.get("id")}
