"""GET /api/result/{query_id} — where charts actually get their numbers."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..agent.render import presentable_row, to_columns
from ..deps import ScopedTenant, get_cache, get_supplier_scope
from ..models import ResultPage
from ..result_cache import ResultCache

router = APIRouter(prefix="/api", tags=["result"])

MAX_PAGE = 5_000


def _lookup(query_id: str, tenant: ScopedTenant, cache: ResultCache):
    result = cache.get(query_id, tenant.supplier_id)
    if result is None:
        # 404, not 403, and deliberately so: a 403 would confirm that this query_id exists and
        # belongs to someone else.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt query_id")
    return result


@router.get("/result/{query_id}", response_model=ResultPage)
async def get_result(query_id: str,
                     offset: int = Query(0, ge=0),
                     limit: int = Query(1000, ge=1, le=MAX_PAGE),
                     tenant: ScopedTenant = Depends(get_supplier_scope),
                     cache: ResultCache = Depends(get_cache)) -> ResultPage:
    result = _lookup(query_id, tenant, cache)
    page = result.rows[offset:offset + limit]
    return ResultPage(
        query_id=result.query_id,
        # `to_columns`, not a second copy of it: this is where the chart reads its legend, so a
        # label built differently here is a label that disagrees with the card's own table.
        columns=to_columns(result),
        rows=[presentable_row(row) for row in page],
        row_count=result.row_count,
        truncated=offset + len(page) < len(result.rows),
    )


@router.get("/export/{query_id}.csv")
async def export_csv(query_id: str,
                     tenant: ScopedTenant = Depends(get_supplier_scope),
                     cache: ResultCache = Depends(get_cache)) -> StreamingResponse:
    result = _lookup(query_id, tenant, cache)
    # An export is the most likely thing to be forwarded to someone who never saw the app, so it
    # is the worst place for internal columns, and the worst place for a header that says
    # "(jämförelse)" without saying which period. Same columns as the table view.
    columns = to_columns(result)

    buffer = io.StringIO()
    # Semicolon delimiter and comma decimals: what Excel in a sv-SE locale expects.
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([c.label for c in columns])
    for row in result.rows:
        writer.writerow([_sv(row.get(c.key)) for c in columns])

    filename = f"solvigo-{result.tool}-{query_id}.csv"
    return StreamingResponse(
        # BOM so Excel detects UTF-8 and renders å, ä and ö correctly.
        iter(["﻿" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _sv(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")
    return str(value)
