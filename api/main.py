"""FastAPI application.

Holds the MCP client and the result cache on `app.state` for the process lifetime, so a chat
turn reuses one warm connection pool instead of opening a session per tool call.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db
from .config import settings
from .mcp_client import McpClient
from .result_cache import ResultCache
from .routes import cards, chat, dashboard, result

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await db.init_pool()
    app.state.mcp = McpClient()
    app.state.cache = ResultCache()
    logger.info("api ready — mcp=%s model=%s", settings.mcp_url, settings.llm_model)
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
    """Reports what is actually wired up, including whether an LLM key is present — the most
    common reason a fresh checkout appears broken."""
    return {
        "status": "ok",
        "mcp_url": settings.mcp_url,
        "llm_model": settings.llm_model,
        "llm_configured": bool(settings.llm_api_key),
    }
