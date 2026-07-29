"""Saved views ("Mina vyer") and share links.

A saved card persists the **ChartSpec plus the tool arguments**, never a screenshot and never
the rows. So opening a saved view re-runs the query live against fresh data — which is the
difference between a saved view and an exported image (§10).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import db
from ..agent import render
from ..auth import create_share_token
from ..config import settings
from ..deps import TenantContext, get_cache, get_mcp, get_supplier_scope
from ..mcp_client import McpClient
from ..models import AnswerCard, SaveCardRequest, ShareRequest, ShareResponse
from ..result_cache import ResultCache, from_tool_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cards"])


@router.get("/cards", response_model=list[AnswerCard])
async def get_cards(tenant: TenantContext = Depends(get_supplier_scope),
                    mcp: McpClient = Depends(get_mcp),
                    cache: ResultCache = Depends(get_cache)) -> list[AnswerCard]:
    """Re-run every saved card so the numbers are current, not as-of-save."""
    cards: list[AnswerCard] = []
    for row in await db.list_cards(int(tenant.supplier_id)):
        try:
            payload = await mcp.call(int(tenant.supplier_id), row["tool_name"],
                                     row["tool_args"])
        except Exception:  # noqa: BLE001 — one broken saved view must not hide the others
            logger.warning("could not refresh card %s", row["card_id"], exc_info=True)
            cards.append(AnswerCard(
                card_id=str(row["card_id"]), status="cannot_answer",
                narrative=f"Kunde inte uppdatera '{row['title']}' mot aktuell data."))
            continue

        result = cache.put(from_tool_result(
            supplier_id=int(tenant.supplier_id), tool=row["tool_name"],
            tool_args=row["tool_args"], payload=payload))
        chart = render.propose_chart(result, title=row["title"])
        if row.get("chart_spec"):
            # The saved spec is re-validated against today's result: a column that existed
            # when the card was saved may not exist now.
            try:
                saved = AnswerCard.model_validate(
                    {"chart": row["chart_spec"], "status": "ok"}).chart
                if saved is not None:
                    chart, _ = render.validate_chart(saved, result)
            except Exception:  # noqa: BLE001
                pass

        cards.append(AnswerCard(
            card_id=str(row["card_id"]), status="ok", chart=chart,
            query_id=result.query_id, columns=render.to_columns(result),
            provenance=render.build_provenance(result)))
    return cards


@router.post("/cards", response_model=AnswerCard, status_code=status.HTTP_201_CREATED)
async def save_card(body: SaveCardRequest,
                    tenant: TenantContext = Depends(get_supplier_scope)) -> AnswerCard:
    card_id = await db.insert_card(
        user_id=tenant.user_id, supplier_id=int(tenant.supplier_id), title=body.title,
        chart_spec=body.chart.model_dump(), tool_name=body.tool_name,
        tool_args=body.tool_args)
    return AnswerCard(card_id=str(card_id), status="ok", chart=body.chart)


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_card(card_id: int,
                      tenant: TenantContext = Depends(get_supplier_scope)) -> Response:
    if not await db.delete_card(card_id, int(tenant.supplier_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt card_id")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/share", response_model=ShareResponse)
async def share(body: ShareRequest,
                tenant: TenantContext = Depends(get_supplier_scope)) -> ShareResponse:
    """Signed, expiring, read-only link.

    Snapshot is the default. A live link re-executes the query later, and it has to do so
    under the *original* supplier's scope rather than the viewer's — getting that backwards is
    a cross-tenant data leak, so "live" is an explicit opt-in and the token carries the scope
    it must run under.

    The **reading end is deferred**: there is no `/delad/{token}` route yet, so this URL does
    not resolve to a page. The frontend control is hidden accordingly (see SHARE_UI_ENABLED
    in web/src/components/CardActions.tsx) rather than offering a link that goes nowhere.
    What remains is the part worth reviewing — the scope-carrying token — and the missing
    piece is a page that verifies it and renders the card under the scope it names.
    """
    card = await db.get_card(body.card_id, int(tenant.supplier_id))
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt card_id")

    token, expires_at = create_share_token(
        card_id=str(body.card_id), supplier_id=int(tenant.supplier_id), mode=body.mode)
    return ShareResponse(
        url=f"{settings.public_web_url}/delad/{token}",
        expires_at=expires_at.isoformat(),
        mode=body.mode,
    )
