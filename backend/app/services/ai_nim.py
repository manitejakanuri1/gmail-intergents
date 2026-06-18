"""NVIDIA NIM client — the secondary model, used for embeddings.

`nv-embedqa-e5-v5` is a retrieval-tuned (query/passage asymmetric) embedding
model. It converts email chunks and user queries into 1024-d vectors that power
the pgvector RAG search. Offloading all high-volume embedding here keeps Gemini
reserved for low-volume reasoning. The NIM embeddings endpoint is OpenAI-compatible.
"""
from __future__ import annotations

import asyncio

import httpx

from ..config import settings

EMBED_DIM = 1024


async def embed(texts: list[str], *, input_type: str = "passage") -> list[list[float]]:
    """Embed a batch of texts. `input_type` is 'passage' (documents) or 'query'."""
    if not texts:
        return []
    url = f"{settings.nim_base_url}/embeddings"
    headers = {"Authorization": f"Bearer {settings.nvidia_nim_api_key}"}
    body = {
        "input": texts,
        "model": settings.nim_embed_model,
        "input_type": input_type,
        "encoding_format": "float",
        # nv-embedqa-e5-v5 caps inputs at 512 tokens; truncate long chunks
        # instead of returning a 400 for the whole batch.
        "truncate": "END",
    }

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(4):
            try:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code == 429 or resp.status_code >= 500:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await asyncio.sleep(2**attempt)
    raise RuntimeError(f"NIM embed failed: {last_err}")


async def embed_query(text: str) -> list[float]:
    out = await embed([text], input_type="query")
    return out[0]
