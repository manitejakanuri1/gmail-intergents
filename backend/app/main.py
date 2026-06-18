"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import close_pool, get_pool
from .routers import auth, categories, chat, compose, emails, sync, threads


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect eagerly, but don't hard-crash the API if infra isn't up yet —
    # this lets you boot the server and inspect /docs before wiring DB/Redis.
    app.state.arq = None
    try:
        await get_pool()
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] Postgres not reachable yet: {exc}")
    try:
        app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] Redis not reachable yet: {exc}")
    yield
    if app.state.arq is not None:
        await app.state.arq.close()
    await close_pool()


app = FastAPI(title="Gmail Intelligence Platform API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(emails.router)
app.include_router(threads.router)
app.include_router(categories.router)
app.include_router(compose.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
