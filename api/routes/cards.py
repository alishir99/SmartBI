"""Saved views ("Mina vyer") and share links."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import db
from ..agent import render
from ..auth import create_share_token
from ..config import settings
from ..deps import ScopedTenant, get_cache, get_mcp, get_supplier_scope
from ..mcp_client import McpClient
from ..models import (
    ALLOWED_CARD_TOOLS,
    AnswerCard,
    SaveCardRequest,
    ShareRequest,
    ShareResponse,
)
from ..result_cache import ResultCache, from_tool_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cards"])


# One GET here used to fan out into one MCP round-trip per saved card, serially and without a
# ceiling: 200 saved views meant 200 queries on one request, and a client could hold the
# database busy for minutes with a single authenticated GET.
MAX_REFRESHED_CARDS = 12
REFRESH_CONCURRENCY = 4

# Reads were capped; writes were not, so one authenticated client could grow a tenant's card
# table without limit. Well above what a supplier pins by hand, and below "unbounded".
MAX_SAVED_CARDS = 200


@router.get("/cards", response_model=list[AnswerCard])
async def get_cards(tenant: ScopedTenant = Depends(get_supplier_scope),
                    mcp: McpClient = Depends(get_mcp),
                    cache: ResultCache = Depends(get_cache)) -> list[AnswerCard]:
    """Re-run the most recent saved cards so the numbers are current, not as-of-save."""
    rows = await db.list_cards(tenant.supplier_id, MAX_REFRESHED_CARDS)
    limit = asyncio.Semaphore(REFRESH_CONCURRENCY)

    async def refresh(row: dict) -> AnswerCard:
        async with limit:
            return await _refresh_card(row, tenant.supplier_id, mcp, cache)

    # `gather` preserves order, so the newest-first ordering from the query survives.
    return list(await asyncio.gather(*(refresh(row) for row in rows)))


async def _refresh_card(row: dict, supplier_id: int, mcp: McpClient,
                        cache: ResultCache) -> AnswerCard:
    if row["tool_name"] not in ALLOWED_CARD_TOOLS:
        # Belt and braces against rows that predate the allowlist on SaveCardRequest, or that
        # arrived by any path other than POST /api/cards.
        logger.warning("saved card %s names unknown tool %r", row["card_id"], row["tool_name"])
        return AnswerCard(
            card_id=str(row["card_id"]), status="cannot_answer",
            narrative=f"'{row['title']}' använder ett verktyg som inte finns längre.")

    try:
        payload = await mcp.call(supplier_id, row["tool_name"], row["tool_args"])
    except Exception:  # noqa: BLE001 — one broken saved view must not hide the others
        logger.warning("could not refresh card %s", row["card_id"], exc_info=True)
        return AnswerCard(
            card_id=str(row["card_id"]), status="cannot_answer",
            narrative=f"Kunde inte uppdatera '{row['title']}' mot aktuell data.")

    result = cache.put(from_tool_result(
        supplier_id=supplier_id, tool=row["tool_name"],
        tool_args=row["tool_args"], payload=payload))
    chart = render.propose_chart(result, title=row["title"])
    if row.get("chart_spec"):
        # The saved spec is re-validated against today's result: a column that existed when the
        # card was saved may not exist now.
        try:
            saved = AnswerCard.model_validate(
                {"chart": row["chart_spec"], "status": "ok"}).chart
            if saved is not None:
                chart, _ = render.validate_chart(saved, result)
        except Exception:  # noqa: BLE001
            pass

    return AnswerCard(
        card_id=str(row["card_id"]), status="ok", chart=chart,
        query_id=result.query_id, columns=render.to_columns(result),
        provenance=render.build_provenance(result))


@router.post("/cards", response_model=AnswerCard, status_code=status.HTTP_201_CREATED)
async def save_card(body: SaveCardRequest,
                    tenant: ScopedTenant = Depends(get_supplier_scope)) -> AnswerCard:
    if await db.count_cards(tenant.supplier_id) >= MAX_SAVED_CARDS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Max {MAX_SAVED_CARDS} sparade vyer per leverantör. Ta bort en först.")
    card_id = await db.insert_card(
        user_id=tenant.user_id, supplier_id=tenant.supplier_id, title=body.title,
        chart_spec=body.chart.model_dump(), tool_name=body.tool_name,
        tool_args=body.tool_args)
    return AnswerCard(card_id=str(card_id), status="ok", chart=body.chart)


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_card(card_id: int,
                      tenant: ScopedTenant = Depends(get_supplier_scope)) -> Response:
    if not await db.delete_card(card_id, tenant.supplier_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt card_id")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/share", response_model=ShareResponse)
async def share(body: ShareRequest,
                tenant: ScopedTenant = Depends(get_supplier_scope)) -> ShareResponse:
    """Signed, expiring, read-only link."""
    # int(): card_id crosses the wire as a string but the column is a bigint, and asyncpg does
    # not coerce.
    card = await db.get_card(int(body.card_id), tenant.supplier_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt card_id")

    token, expires_at = create_share_token(
        card_id=str(body.card_id), supplier_id=tenant.supplier_id, mode=body.mode)
    # The contract is {url, expires_at}; `mode` was being passed and silently dropped, since the
    # model does not declare it.
    return ShareResponse(
        url=f"{settings.public_web_url}/delad/{token}",
        expires_at=expires_at.isoformat(),
    )
