"""Email + thread summarization (map-reduce for long threads)."""
from __future__ import annotations

from . import ai_gemini

_EMAIL_SYS = (
    "Summarize the email in 1-2 concise sentences. Capture the key point and any "
    "action or deadline. No preamble, just the summary."
)

_THREAD_SYS = (
    "You are given an ordered list of message summaries from one email thread. "
    "Write a short summary of the whole conversation arc: what it is about, what was "
    "decided, and what (if anything) is pending. 2-4 sentences."
)


async def summarize_email(subject: str, sender: str, body: str) -> str:
    prompt = f"From: {sender}\nSubject: {subject}\n\n{(body or '')[:6000]}"
    return await ai_gemini.generate(prompt, system=_EMAIL_SYS, temperature=0.2, max_output_tokens=160)


async def summarize_thread(subject: str, ordered_summaries: list[str]) -> str:
    """Reduce step: combine per-message summaries into a thread-level summary."""
    joined = "\n".join(f"{i+1}. {s}" for i, s in enumerate(ordered_summaries))
    prompt = f"Thread subject: {subject}\n\nMessage summaries:\n{joined}"
    return await ai_gemini.generate(prompt, system=_THREAD_SYS, temperature=0.2, max_output_tokens=240)
