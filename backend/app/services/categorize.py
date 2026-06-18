"""Email categorization using Gemini, constrained to the fixed taxonomy."""
from __future__ import annotations

from . import ai_gemini

CATEGORIES = {
    "newsletter": "Newsletters — subscription content and digests",
    "job": "Job / Recruitment — applications, offers, rejections, interviews",
    "finance": "Finance — invoices, receipts, bank alerts, payments",
    "notification": "Notifications — system alerts, OTPs, platform updates",
    "personal": "Personal — direct human-to-human communication",
    "work": "Work / Professional — project and team communication",
}

_SYSTEM = (
    "You are an email classifier. Classify the email into exactly ONE category "
    "key from this list and reply with ONLY the key, nothing else.\n"
    + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
)


async def classify(subject: str, sender: str, body: str) -> str:
    prompt = (
        f"From: {sender}\nSubject: {subject}\n\n"
        f"{(body or '')[:2000]}\n\nCategory key:"
    )
    try:
        out = (await ai_gemini.generate(prompt, system=_SYSTEM, temperature=0, max_output_tokens=8)).lower()
    except Exception:  # noqa: BLE001
        return "notification"
    for key in CATEGORIES:
        if key in out:
            return key
    return "notification"
