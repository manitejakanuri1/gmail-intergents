"""Google Gemini client — the primary reasoning model.

Used for summarization, categorization, compose/reply drafting, and the
chat agent's answer synthesis. Thin httpx wrapper over the REST API so the
behaviour is fully transparent and explainable.
"""
from __future__ import annotations

import asyncio

import httpx

from ..config import settings

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


async def generate(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.3,
    max_output_tokens: int = 1024,
) -> str:
    """Single-shot text generation. Returns the model's text output."""
    url = f"{_BASE}/{settings.gemini_model}:generateContent"
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            # gemini-2.5-* are "thinking" models that consume output tokens on
            # internal reasoning. These tasks are short and deterministic, so we
            # disable thinking for full, fast, cheap responses.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(4):
            try:
                resp = await client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    json=body,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await asyncio.sleep(2**attempt)
    raise RuntimeError(f"Gemini generate failed: {last_err}")
