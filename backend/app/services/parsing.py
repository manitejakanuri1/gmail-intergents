"""Helpers to turn a raw Gmail message payload into our normalized email row."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def _decode_b64(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def html_to_text(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _walk_parts(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (plain_text, html) by walking the MIME tree."""
    plain, html = "", ""
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")
    if mime == "text/plain" and body_data:
        plain += _decode_b64(body_data)
    elif mime == "text/html" and body_data:
        html += _decode_b64(body_data)
    for part in payload.get("parts", []) or []:
        p, h = _walk_parts(part)
        plain += p
        html += h
    return plain, html


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _split_address(value: str) -> tuple[str, str]:
    """Parse 'Jane Doe <jane@x.com>' -> ('Jane Doe', 'jane@x.com')."""
    m = re.match(r"\s*(?:\"?([^\"<]*)\"?)?\s*<?([^<>\s]+@[^<>\s]+)>?", value)
    if m:
        return (m.group(1) or "").strip(), (m.group(2) or "").strip()
    return "", value.strip()


def _emails(value: str) -> list[str]:
    return [_split_address(p)[1] for p in value.split(",") if "@" in p]


def parse_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Gmail `users.messages.get(format=full)` response."""
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    plain, html = _walk_parts(payload)
    if not plain and html:
        plain = html_to_text(html)

    from_name, from_email = _split_address(_header(headers, "From"))
    internal_ms = int(msg.get("internalDate", "0"))
    internal_dt = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc) if internal_ms else None

    return {
        "gmail_message_id": msg["id"],
        "gmail_thread_id": msg["threadId"],
        "rfc822_message_id": _header(headers, "Message-ID"),
        "from_name": from_name,
        "from_email": from_email,
        "to_emails": _emails(_header(headers, "To")),
        "cc_emails": _emails(_header(headers, "Cc")),
        "subject": _header(headers, "Subject"),
        "snippet": msg.get("snippet", ""),
        "body_text": plain.strip(),
        "body_html": html.strip(),
        "internal_date": internal_dt,
        "is_unread": "UNREAD" in (msg.get("labelIds") or []),
        "label_ids": msg.get("labelIds") or [],
    }


def chunk_text(text: str, *, size: int = 1800, overlap: int = 200) -> list[str]:
    """Character-based chunking (~500 tokens) with overlap for embeddings."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
