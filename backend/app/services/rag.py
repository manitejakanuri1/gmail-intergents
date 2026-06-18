"""RAG pipeline for the chat agent.

query -> (history-aware rewrite) -> embed (NIM) -> hybrid retrieve (pgvector +
full-text) -> assemble cited context -> answer (Gemini) with source clarity and
a hard "not found" guardrail to prevent hallucination.
"""
from __future__ import annotations

import json

from ..db import get_pool, to_vector_literal
from . import ai_gemini, ai_nim

_REWRITE_SYS = (
    "Rewrite the user's latest message into a standalone search query using the "
    "conversation history for context. Reply with ONLY the rewritten query."
)

_ANSWER_SYS = (
    "You are an assistant that answers questions using ONLY the user's emails provided "
    "as context. Each context block is labelled [source N] with sender, subject and date.\n"
    "Rules:\n"
    "- Use only the provided context. Do not use outside knowledge.\n"
    "- After each fact, cite the source like [source 1].\n"
    "- If several emails cover the same topic, synthesize them into one coherent answer.\n"
    "- If the answer is not in the context, reply exactly: "
    "\"I couldn't find that in your emails.\"\n"
    "- Be concise and well organized."
)

SIM_THRESHOLD = 0.20  # cosine similarity floor; below this we treat as 'not found'


async def _rewrite(history: list[dict], question: str) -> str:
    if not history:
        return question
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    prompt = f"History:\n{convo}\n\nLatest message: {question}"
    try:
        return await ai_gemini.generate(prompt, system=_REWRITE_SYS, temperature=0, max_output_tokens=120)
    except Exception:  # noqa: BLE001
        return question


async def retrieve(account_id: str, query: str, k: int = 8) -> list[dict]:
    """Hybrid retrieval: vector ANN + full-text, merged and de-duplicated by email.

    If embeddings aren't available yet (e.g. the NIM key isn't configured), this
    gracefully falls back to full-text-only search so the agent still works.
    """
    pool = await get_pool()

    vector_rows = []
    try:
        qvec = await ai_nim.embed_query(query)
        vec_literal = to_vector_literal(qvec)
        async with pool.acquire() as conn:
            vector_rows = await conn.fetch(
                """
                select e.id as email_id, e.thread_id, e.from_name, e.from_email,
                       e.subject, e.internal_date, ee.content,
                       1 - (ee.embedding <=> $2::vector) as score
                from email_embeddings ee
                join emails e on e.id = ee.email_id
                where ee.account_id = $1
                order by ee.embedding <=> $2::vector
                limit 30
                """,
                account_id, vec_literal,
            )
    except Exception:  # noqa: BLE001
        vector_rows = []  # NIM unavailable -> rely on full-text retrieval below

    async with pool.acquire() as conn:
        # OR-semantics: convert plainto_tsquery's "a & b & c" into "a | b | c" so
        # partial keyword overlaps still surface (much better recall, especially
        # as the no-embeddings fallback). ts_rank still orders by relevance.
        text_rows = await conn.fetch(
            """
            with q as (
              select to_tsquery('english',
                replace(plainto_tsquery('english', $2)::text, ' & ', ' | ')) as tsq
            )
            select e.id as email_id, e.thread_id, e.from_name, e.from_email,
                   e.subject, e.internal_date,
                   coalesce(e.summary, e.snippet, left(e.body_text, 500)) as content,
                   ts_rank(e.tsv, q.tsq) as score
            from emails e, q
            where e.account_id = $1 and q.tsq is not null and e.tsv @@ q.tsq
            order by score desc
            limit 30
            """,
            account_id, query,
        )

    # Merge: keep the best-scoring chunk per email, prefer vector hits above threshold.
    best: dict[str, dict] = {}
    for r in vector_rows:
        d = dict(r)
        if d["score"] is None or d["score"] < SIM_THRESHOLD:
            continue
        key = str(d["email_id"])
        if key not in best or d["score"] > best[key]["score"]:
            best[key] = d
    for r in text_rows:
        d = dict(r)
        key = str(d["email_id"])
        if key not in best:
            d["score"] = float(d["score"] or 0)
            best[key] = d

    ranked = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:k]


def _build_context(rows: list[dict]) -> tuple[str, list[dict]]:
    blocks, sources = [], []
    for i, r in enumerate(rows, start=1):
        date = r["internal_date"].strftime("%Y-%m-%d") if r.get("internal_date") else "unknown date"
        sender = r.get("from_name") or r.get("from_email") or "unknown"
        blocks.append(
            f"[source {i}] from: {sender} | subject: {r.get('subject') or '(no subject)'} | "
            f"date: {date}\n{(r.get('content') or '').strip()}"
        )
        sources.append(
            {
                "n": i,
                "email_id": str(r["email_id"]),
                "thread_id": str(r["thread_id"]),
                "from": sender,
                "subject": r.get("subject"),
                "date": date,
            }
        )
    return "\n\n".join(blocks), sources


async def answer(account_id: str, history: list[dict], question: str) -> dict:
    standalone = await _rewrite(history, question)
    rows = await retrieve(account_id, standalone)
    if not rows:
        return {"answer": "I couldn't find that in your emails.", "sources": []}

    context, sources = _build_context(rows)
    prompt = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer (with [source N] citations):"
    try:
        text = await ai_gemini.generate(
            prompt, system=_ANSWER_SYS, temperature=0.2, max_output_tokens=900
        )
    except Exception:  # noqa: BLE001
        # Gemini unavailable (e.g. rate-limited). Still return the relevant
        # emails we retrieved so the user gets value instead of an error.
        lines = [
            f"{s['n']}. {s['from']} — {s.get('subject') or '(no subject)'} ({s['date']})"
            for s in sources
        ]
        fallback = (
            "The AI writer is rate-limited right now, but here are the most relevant "
            "emails I found for your question:\n\n" + "\n".join(lines)
        )
        return {"answer": fallback, "sources": sources}

    # Only surface sources actually cited in the answer.
    cited = [s for s in sources if f"[source {s['n']}]" in text] or sources
    return {"answer": text, "sources": cited}


def sources_to_json(sources: list[dict]) -> str:
    return json.dumps(sources)
