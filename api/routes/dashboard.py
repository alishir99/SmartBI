"""The standard dashboard — deterministic, no LLM anywhere in this file."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..agent import render
from ..deps import ScopedTenant, get_cache, get_mcp, get_supplier_scope
from ..mcp_client import McpClient
from ..models import AnswerCard, DashboardResponse, Kpi
from ..result_cache import ResultCache, from_tool_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["dashboard"])

# The dashboard opens on the last 12 months against the same period a year earlier.
DEFAULT_PERIOD = "last_12_months"

PERIODS: dict[str, dict] = {
    "last_7_days":     {"label": "Senaste veckan",     "grain": "day",     "compare": False},
    "last_30_days":    {"label": "Senaste 30 dagarna", "grain": "day",     "compare": False},
    "last_90_days":    {"label": "Senaste kvartalet",  "grain": "week",    "compare": False},
    "last_month":      {"label": "Förra månaden",      "grain": "day",     "compare": True},
    "ytd":             {"label": "Hittills i år",      "grain": "month",   "compare": True},
    "last_12_months":  {"label": "Senaste 12 mån",     "grain": "month",   "compare": True},
    "all_time":        {"label": "Hela perioden",      "grain": "quarter", "compare": False},
}


def _period_spec(period: str) -> tuple[dict, dict]:
    """Resolve a period key to its time_range and its presentation settings."""
    key = period if period in PERIODS else DEFAULT_PERIOD
    return {"relative": key}, PERIODS[key]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(period: str = Query(DEFAULT_PERIOD,
                                        description="Nyckel ur PERIODS; okänt värde faller "
                                                    "tillbaka på standardfönstret."),
                    tenant: ScopedTenant = Depends(get_supplier_scope),
                    mcp: McpClient = Depends(get_mcp),
                    cache: ResultCache = Depends(get_cache)) -> DashboardResponse:
    supplier_id = tenant.supplier_id
    assert supplier_id is not None  # get_supplier_scope guarantees this

    window, settings = _period_spec(period)
    # `compare_to` is dropped for windows with no honest counterpart: "the same 90 days last
    # year" is a comparison nobody asked for, and a delta chip against a window the user did not
    # choose is worse than no chip at all.
    totals_args: dict = {"measures": ["net_sales_sek", "units", "avg_price_sek"],
                         "time_range": window}
    if settings["compare"]:
        totals_args["compare_to"] = "same_period_last_year"

    try:
        # One MCP session, four queries, run concurrently — the tiles are independent and the
        # rollup makes each of them cheap.
        totals, trend, top_products, by_region, share = await asyncio.gather(
            _call(mcp, supplier_id, "query_sales", totals_args),
            _call(mcp, supplier_id, "query_sales", {
                # All three headline measures, so the KPI sparklines cost no extra query. The
                # trend card charts the first of them; `propose_chart` picks measures[0].
                "measures": ["net_sales_sek", "units", "avg_price_sek"],
                "dimensions": [settings["grain"]],
                "time_range": window,
                # Same rule as the KPI row: a comparison only where the window has an honest
                # counterpart. `propose_chart` overlays it on the trend line.
                **({"compare_to": "same_period_last_year"} if settings["compare"] else {}),
            }),
            _call(mcp, supplier_id, "query_sales", {
                "measures": ["net_sales_sek", "units"],
                "dimensions": ["product"],
                "time_range": window,
                "order_by": {"measure": "net_sales_sek", "dir": "desc"},
                "limit": 10,
            }),
            _call(mcp, supplier_id, "query_sales", {
                "measures": ["net_sales_sek"],
                "dimensions": ["region"],
                "time_range": window,
                "order_by": {"measure": "net_sales_sek", "dir": "desc"},
            }),
            _call(mcp, supplier_id, "query_market_share", {
                "time_range": window,
                **({"compare_to": "same_period_last_year"} if settings["compare"] else {}),
            }),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("dashboard failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Kunde inte hämta dashboarddata: {exc}") from exc

    payloads: dict[str, tuple[str, dict, dict]] = {
        "trend": ("query_sales", {}, trend),
        "top_products": ("query_sales", {}, top_products),
        "by_region": ("query_sales", {}, by_region),
    }
    cached = {
        name: cache.put(from_tool_result(supplier_id=supplier_id, tool=tool,
                                         tool_args=args, payload=payload))
        for name, (tool, args, payload) in payloads.items()
    }

    return DashboardResponse(
        kpis=_kpis(totals, share, trend),
        cards=[
            _card(cached["trend"], "Försäljning per månad"),
            _card(cached["top_products"], "Topp 10 produkter"),
            _card(cached["by_region"], "Försäljning per län"),
        ],
    )


async def _call(mcp: McpClient, supplier_id: int, tool: str, args: dict) -> dict:
    return await mcp.call(supplier_id, tool, args)


def _card(result, title: str) -> AnswerCard:
    """A dashboard tile is the same AnswerCard the chat produces — one card type, two producers
    (§2).

    No subtitle: the card falls back to the window in `provenance.time_range`, which is what the
    tool actually ran. A literal here goes stale the moment the user picks another period.
    """
    chart = render.propose_chart(result, title=title)
    return AnswerCard(
        status="ok",
        chart=chart,
        query_id=result.query_id,
        columns=render.to_columns(result),
        provenance=render.build_provenance(result),
    )


def _first_number(payload: dict, key: str) -> float | None:
    rows = payload.get("rows") or []
    if not rows:
        return None
    value = rows[0].get(key)
    return float(value) if value is not None else None


def _weighted_share(rows: list[dict], own_key: str, category_key: str) -> float | None:
    """Own sales over the category total, weighted across subcategories.

    An unweighted mean would let a tiny subcategory with a high share dominate the tile. The
    denominator is deduplicated by `category_id` because the tool's grain is brand ×
    subcategory: a supplier with two brands in one subcategory gets that total back twice.
    """
    # A window every row does not carry is not a window: mixing rows that have a comparison
    # with rows that do not would put two different periods in one figure.
    if any(row.get(own_key) is None or row.get(category_key) is None for row in rows):
        return None
    own = sum(float(row[own_key]) for row in rows)
    category = sum({row.get("category_id"): float(row[category_key])
                    for row in rows}.values())
    return round(100 * own / category, 1) if category else None


def _spark(trend: dict, key: str) -> list[float]:
    """The measure over the trend's own grain, oldest first.

    Two points are a line, not a shape, so anything shorter is dropped rather than drawn. A
    period that exists only in the comparison window carries no current value, and is a gap
    rather than a zero.
    """
    values = [float(row[key]) for row in (trend.get("rows") or [])
              if row.get(key) is not None]
    return values if len(values) >= 3 else []


def _kpis(totals: dict, share: dict, trend: dict | None = None) -> list[Kpi]:
    """The four headline numbers."""
    trend = trend or {}
    kpis: list[Kpi] = []

    net = _first_number(totals, "net_sales_sek")
    if net is not None:
        kpis.append(Kpi(key="net_sales_sek", label="Försäljning", value=net, unit="SEK",
                        delta_pct=_first_number(totals, "net_sales_sek_delta_pct"),
                        delta_label="vs samma period förra året",
                        spark=_spark(trend, "net_sales_sek")))

    rows = [r for r in (share.get("rows") or []) if not r.get("suppressed")]
    if rows:
        current = _weighted_share(rows, "own_net_sek", "category_net_sek")
        if current is not None:
            best = min(rows, key=lambda r: r.get("rank") or 99)
            previous = _weighted_share(rows, "own_net_sek_compare",
                                       "category_net_sek_compare")
            kpis.append(Kpi(
                key="category_share_pct", label="Andel av kategori",
                value=current, unit="%",
                # Percentage points: the frontend renders a '%' KPI's delta as p.e.
                delta_pct=None if previous is None else round(current - previous, 1),
                delta_label="vs samma period förra året",
                # No sparkline: query_market_share aggregates over the whole window and has no
                # month dimension, so there is no series to draw without a new tool shape.
                rank_label=(f"#{best['rank']} av {best['n_brands']} varumärken "
                            f"i {best['subcategory']}")))

    units = _first_number(totals, "units")
    if units is not None:
        kpis.append(Kpi(key="units", label="Sålda enheter", value=units, unit="st",
                        delta_pct=_first_number(totals, "units_delta_pct"),
                        delta_label="vs samma period förra året",
                        spark=_spark(trend, "units")))

    avg_price = _first_number(totals, "avg_price_sek")
    if avg_price is not None:
        kpis.append(Kpi(key="avg_price_sek", label="Snittpris", value=avg_price, unit="SEK",
                        delta_pct=_first_number(totals, "avg_price_sek_delta_pct"),
                        delta_label="vs samma period förra året",
                        spark=_spark(trend, "avg_price_sek")))

    return kpis
