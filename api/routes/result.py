"""GET /api/result/{query_id} — where charts actually get their numbers.

This endpoint is the other half of the grounding claim. The model saw a 25-row preview; the
chart is drawn from here, from the full cached result set. So the values on screen provably
never passed through the language model.

Also the CSV export, since it is the same data with a different content type.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..deps import TenantContext, get_cache, get_supplier_scope
from ..models import ResultPage
from ..result_cache import ResultCache

router = APIRouter(prefix="/api", tags=["result"])

MAX_PAGE = 5_000


def _lookup(query_id: str, tenant: TenantContext, cache: ResultCache):
    result = cache.get(query_id, int(tenant.supplier_id))
    if result is None:
        # 404, not 403, and deliberately so: a 403 would confirm that this query_id exists and
        # belongs to someone else. An attacker probing ids learns nothing from a 404.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Okänt query_id")
    return result


@router.get("/result/{query_id}", response_model=ResultPage)
async def get_result(query_id: str,
                     offset: int = Query(0, ge=0),
                     limit: int = Query(1000, ge=1, le=MAX_PAGE),
                     tenant: TenantContext = Depends(get_supplier_scope),
                     cache: ResultCache = Depends(get_cache)) -> ResultPage:
    result = _lookup(query_id, tenant, cache)
    page = result.rows[offset:offset + limit]
    return ResultPage(
        query_id=result.query_id,
        columns=[{"key": c["key"], "type": c.get("type", "text"),
                  "label": c.get("label", c["key"]), "unit": c.get("unit")}
                 for c in result.columns],
        rows=page,
        row_count=result.row_count,
        truncated=offset + len(page) < len(result.rows),
    )


@router.get("/export/{query_id}.csv")
async def export_csv(query_id: str,
                     tenant: TenantContext = Depends(get_supplier_scope),
                     cache: ResultCache = Depends(get_cache)) -> StreamingResponse:
    result = _lookup(query_id, tenant, cache)
    keys = [c["key"] for c in result.columns]

    buffer = io.StringIO()
    # Semicolon delimiter and comma decimals: what Excel in a sv-SE locale expects. A
    # comma-delimited file with dot decimals opens as one column per row for a Swedish user,
    # which makes "export" useless in practice.
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([c.get("label", c["key"]) for c in result.columns])
    for row in result.rows:
        writer.writerow([_sv(row.get(key)) for key in keys])

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
