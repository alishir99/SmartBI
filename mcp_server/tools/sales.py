"""query_sales - the workhorse tool."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from .. import db
from ..config import settings
from ..semantic.compiler import compile_query
from ..tenant import TenantContext


def _jsonable(value):
    if isinstance(value, Decimal):
        # NUMERIC arrives as Decimal.
        return float(round(value, 2))
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def scope_label(supplier_id: int) -> str:
    """A stable, non-reversible label for the audit trail and the source chip."""
    digest = hashlib.sha256(f"supplier:{supplier_id}".encode()).hexdigest()
    return f"supplier:{digest[:8]}"


async def query_sales(tenant: TenantContext, spec: dict) -> dict:
    coverage = await db.coverage()
    compiled = compile_query(spec, coverage)

    async with db.tenant_connection(tenant.supplier_id) as connection:
        records = await connection.fetch(compiled.sql, *compiled.params)

    rows = [{key: _jsonable(value) for key, value in record.items()} for record in records]
    limit = spec.get("limit")

    return {
        "query_id": f"q_{uuid4().hex[:16]}",
        "columns": compiled.columns,
        "rows": rows,
        "row_count": len(rows),
        "meta": {
            "tool": "query_sales",
            "source": "mv_sales_daily (rollup)" if compiled.source == "rollup"
                      else "fact_sales_line",
            "scope": scope_label(tenant.supplier_id),
            "currency": settings.app_currency,
            "vat": settings.vat_code,
            "time_range": {"from": compiled.time_range[0].isoformat(),
                           "to": compiled.time_range[1].isoformat()},
            "compare_range": ({"from": compiled.compare_range[0].isoformat(),
                               "to": compiled.compare_range[1].isoformat()}
                              if compiled.compare_range else None),
            "coverage": {"from": coverage[0].isoformat(), "to": coverage[1].isoformat()},
            "filters_applied": {k: v for k, v in (spec.get("filters") or {}).items() if v},
            "measures": list(spec.get("measures") or []),
            "dimensions": list(spec.get("dimensions") or []),
            # True when the caller's own limit cut the result, so the model can say "topp 10"
            # rather than implying it saw everything.
            "truncated": limit is not None and len(rows) >= int(limit),
            "executed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
