"""GET /api/shared/{token} - the read side of a share link.

The only route in the API with no session behind it. Everything it is allowed to read comes
from the token: which card, and whose scope to run it under. A reader cannot widen either,
because both are signed, and the query runs under the *sharing* supplier's scope whoever opens
the link - which is the whole reason the scope is in the token rather than in the request.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, status

from .. import db
from ..agent import render
from ..auth import decode_access_token
from ..deps import get_cache, get_mcp
from ..i18n import tr
from ..mcp_client import McpClient
from ..models import ALLOWED_CARD_TOOLS, AnswerCard, ResultPage, SharedView
from ..result_cache import ResultCache, from_tool_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["shared"])

# One message for every way a link can fail to resolve. A reader cannot act on the difference
# between "expired", "tampered with" and "the card was deleted", and telling them which it was
# tells whoever is guessing tokens which guess got closer.
_GONE = "Länken är ogiltig eller har gått ut."

# The page has no pagination and no export, so this is the whole payload - well above any saved
# card's chart, and below anything that hurts to serialise.
MAX_SHARED_ROWS = 2_000


@router.get("/shared/{token}", response_model=SharedView)
async def shared(token: str,
                 mcp: McpClient = Depends(get_mcp),
                 cache: ResultCache = Depends(get_cache)) -> SharedView:
    claims = _claims(token)
    supplier_id = claims["supplier_id"]

    row = await db.get_card(int(claims["card_id"]), supplier_id)
    if row is None or row["tool_name"] not in ALLOWED_CARD_TOOLS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE)

    try:
        payload = await mcp.call(supplier_id, row["tool_name"], row["tool_args"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not resolve shared card %s", row["card_id"], exc_info=True)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            "Kunde inte hämta vyn mot aktuell data.") from exc

    result = cache.put(from_tool_result(
        supplier_id=supplier_id, tool=row["tool_name"],
        tool_args=row["tool_args"], payload=payload))

    chart = render.propose_chart(result, title=row["title"])
    if row.get("chart_spec"):
        # The saved spec is re-validated against today's result, exactly as a refresh does: a
        # column that existed when the card was saved may not exist now.
        try:
            saved = AnswerCard.model_validate(
                {"chart": row["chart_spec"], "status": "ok"}).chart
            if saved is not None:
                chart, _ = render.validate_chart(saved, result)
        except Exception:  # noqa: BLE001
            pass

    columns = render.to_columns(result)
    return SharedView(
        card=AnswerCard(
            # Neither id reaches the reader. `query_id` because /api/result is scoped to a
            # logged-in tenant and would 404 for them - the rows travel inline instead - and
            # `card_id` because every control keyed to it (share, delete) is an authenticated
            # call this page cannot make, and a button that 401s is worse than no button.
            card_id=None, status="ok", chart=chart,
            query_id=None, columns=columns,
            provenance=render.build_provenance(result)),
        result=ResultPage(
            query_id=result.query_id,
            columns=columns,
            rows=[render.presentable_row(r) for r in result.rows[:MAX_SHARED_ROWS]],
            row_count=result.row_count,
            truncated=len(result.rows) > MAX_SHARED_ROWS,
        ),
        shared_by=await db.supplier_name(supplier_id) or tr("unknown.supplier"),
        expires_at=datetime.fromtimestamp(claims["exp"], UTC).isoformat(),
        # ponytail: `snapshot` links resolve live too. Freezing the rows means storing them,
        # which is a table and a retention rule rather than a flag; the mode rides in the token
        # so the read side can start honouring it without reissuing any link.
        mode="live",
    )


def _claims(token: str) -> dict:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE) from None

    # A session token is signed with the same key, so the type has to be checked: without it,
    # anyone's own access token would read any card_id they cared to name.
    if (claims.get("typ") != "share"
            or not isinstance(claims.get("supplier_id"), int)
            or not str(claims.get("card_id", "")).isdigit()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE)
    return claims
