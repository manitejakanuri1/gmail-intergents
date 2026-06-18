"""Gmail API client: OAuth token exchange/refresh, message sync helpers,
and sending. Uses httpx directly so rate-limit and backoff behaviour is explicit.
"""
from __future__ import annotations

import asyncio
import base64
import time
from email.mime.text import MIMEText
from typing import Any

import httpx

from ..config import settings

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"


def build_consent_url(state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.google_scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{OAUTH_AUTH}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


class GmailClient:
    """Authenticated Gmail client with retry/backoff + simple rate limiting."""

    def __init__(self, access_token: str, min_interval: float = 0.1):
        self.access_token = access_token
        self._min_interval = min_interval  # ~10 req/s client-side throttle
        self._last_call = 0.0

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kw):
        """Single request with exponential backoff on 429 / 5xx."""
        headers = kw.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        for attempt in range(6):
            await self._throttle()
            resp = await client.request(method, f"{GMAIL_API}{path}", headers=headers, **kw)
            if resp.status_code in (429,) or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 32)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Gmail request failed after retries: {method} {path}")

    async def list_message_ids(
        self, client: httpx.AsyncClient, page_token: str | None = None, q: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        return await self._request(client, "GET", "/users/me/messages", params=params)

    async def get_message(self, client: httpx.AsyncClient, message_id: str) -> dict[str, Any]:
        return await self._request(
            client, "GET", f"/users/me/messages/{message_id}", params={"format": "full"}
        )

    async def list_labels(self, client: httpx.AsyncClient) -> dict[str, Any]:
        return await self._request(client, "GET", "/users/me/labels")

    async def history_list(
        self, client: httpx.AsyncClient, start_history_id: int, page_token: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        return await self._request(client, "GET", "/users/me/history", params=params)

    async def send_message(
        self, client: httpx.AsyncClient, raw_mime: str, thread_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"raw": raw_mime}
        if thread_id:
            body["threadId"] = thread_id
        return await self._request(client, "POST", "/users/me/messages/send", json=body)


def build_mime(
    *,
    to: str,
    subject: str,
    body: str,
    from_email: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Build a base64url-encoded MIME message for users.messages.send."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = from_email
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
