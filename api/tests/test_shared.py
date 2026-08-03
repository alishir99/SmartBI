"""The one route with no session behind it, so the token is the whole boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from api import db
from api.auth import create_access_token, create_share_token
from api.config import settings
from api.result_cache import ResultCache
from api.routes import shared as shared_route

CARD_ROW = {
    "card_id": 7,
    "title": "Försäljning per månad",
    "chart_spec": None,
    "tool_name": "query_sales",
    "tool_args": {"measures": ["net_sales_sek"], "dimensions": ["month"]},
}

PAYLOAD = {
    "rows": [{"month": "2026-01-01", "net_sales_sek": 100.0},
             {"month": "2026-02-01", "net_sales_sek": 120.0}],
    "row_count": 2,
    "columns": [{"key": "month", "type": "date", "label": "Månad"},
                {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}],
    "meta": {"tool": "query_sales", "source": "mv_sales_daily (rollup)",
             "scope": "supplier:abcd",
             "time_range": {"from": "2026-01-01", "to": "2026-02-28"},
             "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
             "executed_at": "2026-08-01T10:00:00Z"},
}


class FakeMcp:
    def __init__(self):
        self.calls: list[tuple[int, str, dict]] = []

    async def call(self, supplier_id, tool, args):
        self.calls.append((supplier_id, tool, args))
        return PAYLOAD


@pytest.fixture
def stubbed(monkeypatch):
    """The card row and the supplier name, without a database."""
    async def get_card(card_id, supplier_id):
        return dict(CARD_ROW) if (card_id, supplier_id) == (7, 1) else None

    async def supplier_name(supplier_id):
        return "Nordström Audio AB"

    monkeypatch.setattr(db, "get_card", get_card)
    monkeypatch.setattr(db, "supplier_name", supplier_name)


async def resolve(token: str, mcp: FakeMcp | None = None):
    return await shared_route.shared(token, mcp=mcp or FakeMcp(), cache=ResultCache())


@pytest.mark.asyncio
async def test_a_valid_link_resolves_with_its_rows_inline(stubbed):
    token, _ = create_share_token(card_id="7", supplier_id=1, mode="live")
    view = await resolve(token)

    assert view.shared_by == "Nordström Audio AB"
    assert view.card.chart is not None
    # The reader has no session, so /api/result would 404 for them: the rows have to travel
    # with the card or the page has a chart and nothing to draw.
    assert view.card.query_id is None
    # And no card_id, or the card offers a share button and a delete button that can only 401.
    assert view.card.card_id is None
    assert len(view.result.rows) == 2


@pytest.mark.asyncio
async def test_the_query_runs_under_the_sharing_supplier(stubbed):
    """The scope is in the token, not in the request. Whoever opens the link, the query runs
    as the supplier who created it - and can therefore never widen."""
    mcp = FakeMcp()
    token, _ = create_share_token(card_id="7", supplier_id=1, mode="live")
    await resolve(token, mcp)

    assert [supplier for supplier, _, _ in mcp.calls] == [1]


@pytest.mark.asyncio
async def test_a_session_token_is_not_a_share_token(stubbed):
    """Both are signed with the same key. Without the type check, any logged-in user's own
    token would read any card_id they cared to name - including another tenant's."""
    session = create_access_token({"user_id": 5, "supplier_id": 1, "role": "supplier_admin"})
    with pytest.raises(HTTPException) as raised:
        await resolve(session)
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_link_is_gone(stubbed):
    expired = jwt.encode(
        {"typ": "share", "card_id": "7", "supplier_id": 1, "mode": "live",
         "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())},
        settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as raised:
        await resolve(expired)
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_a_token_signed_with_another_key_is_gone(stubbed):
    forged = jwt.encode(
        {"typ": "share", "card_id": "7", "supplier_id": 1, "mode": "live",
         "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
        "not-the-key-this-api-signs-with-and-long-enough", algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as raised:
        await resolve(forged)
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_a_card_belonging_to_another_supplier_is_gone(stubbed):
    """The token names both, and they have to agree - a signed card_id under the wrong
    supplier_id must not resolve."""
    token, _ = create_share_token(card_id="7", supplier_id=2, mode="live")
    with pytest.raises(HTTPException) as raised:
        await resolve(token)
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_every_failure_says_the_same_thing(stubbed):
    """Distinguishing "expired" from "never existed" tells whoever is guessing which guess got
    closer."""
    session = create_access_token({"user_id": 5, "supplier_id": 1, "role": "supplier_admin"})
    missing, _ = create_share_token(card_id="404", supplier_id=1, mode="live")

    messages = set()
    for token in (session, missing, "not-a-token-at-all"):
        with pytest.raises(HTTPException) as raised:
            await resolve(token)
        messages.add(raised.value.detail)
    assert len(messages) == 1
