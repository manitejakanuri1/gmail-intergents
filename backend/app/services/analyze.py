"""Single-call email analysis: category + priority + summary + action.

Folding everything the dashboard needs into ONE Gemini call (instead of separate
categorize + summarize calls) halves token/quota usage and gives us the urgency
and action fields the priority control dashboard is built around.
"""
from __future__ import annotations

import json
import re

from . import ai_gemini
from .categorize import CATEGORIES

_PRIORITIES = ["urgent", "high", "medium", "low"]

_SYSTEM = (
    "You are an email triage engine for a priority control dashboard. "
    "Read the email and return ONLY a JSON object (no markdown, no prose) with keys:\n"
    '  "category": one of [' + ", ".join(CATEGORIES) + "]\n"
    '  "priority": one of [urgent, high, medium, low]\n'
    '  "summary": a 1-2 sentence summary\n'
    '  "action": the single concrete action the user should take, or null if none\n'
    '  "needs_action": true if the email requires the user to do something, else false\n\n'
    "Priority guidance: urgent = time-sensitive and important (deadlines, security, "
    "money at risk, interview/offer, an angry customer); high = important but not "
    "same-day; medium = useful FYI; low = newsletters, promotions, automated noise."
)


def _coerce(raw: str) -> dict:
    """Parse the model's JSON, tolerating code fences / stray text."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    text = m.group(0) if m else raw
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return data


async def analyze(subject: str, sender: str, body: str) -> dict:
    prompt = f"From: {sender}\nSubject: {subject}\n\n{(body or '')[:6000]}\n\nJSON:"
    try:
        raw = await ai_gemini.generate(
            prompt, system=_SYSTEM, temperature=0.1, max_output_tokens=400
        )
        data = _coerce(raw)
    except Exception:  # noqa: BLE001
        data = {}

    category = str(data.get("category", "")).lower().strip()
    if category not in CATEGORIES:
        category = "notification"
    priority = str(data.get("priority", "")).lower().strip()
    if priority not in _PRIORITIES:
        priority = "low"
    summary = (data.get("summary") or "").strip()
    action = data.get("action")
    action = action.strip() if isinstance(action, str) and action.strip().lower() not in ("", "null", "none") else None
    needs_action = bool(data.get("needs_action")) or action is not None

    return {
        "category": category,
        "priority": priority,
        "summary": summary,
        "action": action,
        "needs_action": needs_action,
    }
