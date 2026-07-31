"""FastAPI application."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, logs
from .config import settings
from .mcp_client import McpClient
from .result_cache import ResultCache
from .routes import cards, chat, dashboard, result

logs.configure()
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Before anything else, and before the port is listening: an unconfigured deployment must
    # not reach the point of answering a request.
    settings.assert_secrets_rotated()
    await db.init_pool()
    app.state.mcp = McpClient()
    app.state.cache = ResultCache()
    logger.info("api ready", extra={"event": "startup", "mcp_url": settings.mcp_url,
                                    "model": settings.llm_model,
                                    "env": settings.solvigo_env})
    try:
        yield
    finally:
        await db.close_pool()


app = FastAPI(
    title="Solvigo Insights API",
    description="AI-native försäljningsdashboard. All data läses genom MCP-servern.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # An allowlist, not "*": the API is called with a bearer token, and a wildcard origin on a
    # credentialed API is how a malicious page reads a logged-in user's data.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """One id per request, echoed back and attached to every log line underneath it.

    Honours an inbound `X-Request-Id` so a trace survives a proxy; mints one otherwise. This
    is what turns a pile of lines into a story you can follow.
    """
    request_id = request.headers.get("X-Request-Id") or logs.new_turn_id()
    logs.bind(request_id=request_id, path=request.url.path, method=request.method)
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled", extra={
            "event": "http.error", "ms": int((time.monotonic() - started) * 1000)})
        raise
    # Health checks run every few seconds and would otherwise be the bulk of the log.
    if request.url.path != "/health":
        logger.info("", extra={"event": "http.request", "status": response.status_code,
                               "ms": int((time.monotonic() - started) * 1000)})
    response.headers["X-Request-Id"] = request_id
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    return response


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(result.router)
app.include_router(cards.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Reports what is actually wired up, including whether an LLM key is present — the most common
    reason a fresh checkout appears broken."""
    return {
        "status": "ok",
        "mcp_url": settings.mcp_url,
        "llm_model": settings.llm_model,
        "llm_configured": bool(settings.llm_api_key),
    }
