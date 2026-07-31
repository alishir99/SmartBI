"""The standard dashboard — deterministic, no LLM anywhere in this file.

This is requirement 1 of the case: the user arrives at finished answers, having configured
nothing. It is also decision D10 in practice — the dashboard reads through the *same four MCP
tools* the agent uses, server-side. That is what makes MCP the application's data API rather
than a side-car for the model, and it is why the chat and the dashboard cannot disagree about
a number: there is only one implementation of "net sales".
"""

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

# The dashboard opens on the last 12 months against the same period a year earlier. The
# default is still the point — "BI without a BI department" means the first screen asks
# nothing — but the window is now switchable, for two reasons that showed up in use. A user
# comparing a figure here against a number from elsewhere could not tell which window they
# were looking at, and a 12-month total is the wrong lens for "how did last week go?".
#
# The trend grain follows the window rather than being a second control: 52 daily points are
# noise and 2 quarterly ones are not a trend. One choice, two adjustments — the user picks a
# period, not a period *and* a granularity.
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
    """Resolve a period key to its time_range and its presentation settings.

    Every key here is a real relative window in the semantic layer — `last_7_days` was added
    to `model.RELATIVE_RANGES` rather than approximated with a 30-day range, because a
    control labelled "Senaste veckan" that returns a month of data is the kind of quiet lie
    this whole codebase is built to avoid. Anything unknown falls back to the default rather
    than 400-ing: a stale bookmark should not blank someone's dashboard.
    """
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
    # year" is a comparison nobody asked for, and a delta chip against a window the user did
    # not choose is worse than no chip at all.
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
                "measures": ["net_sales_sek"],
                "dimensions": [settings["grain"]],
                "time_range": window,
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
            _call(mcp, supplier_id, "query_market_share", {"time_range": window}),
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
        kpis=_kpis(totals, share),
        cards=[
            _card(cached["trend"], "Försäljning per månad",
                  "senaste 12 månaderna · nettoförsäljning, exkl. moms"),
            _card(cached["top_products"], "Topp 10 produkter",
                  "senaste 12 månaderna · nettoförsäljning, exkl. moms"),
            _card(cached["by_region"], "Försäljning per län",
                  "senaste 12 månaderna · nettoförsäljning, exkl. moms"),
        ],
    )


async def _call(mcp: McpClient, supplier_id: int, tool: str, args: dict) -> dict:
    return await mcp.call(supplier_id, tool, args)


def _card(result, title: str, subtitle: str) -> AnswerCard:
    """A dashboard tile is the same AnswerCard the chat produces — one card type, two
    producers (§2). The narrative is empty because the chart is the answer here."""
    chart = render.propose_chart(result, title=title, subtitle=subtitle)
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


def _kpis(totals: dict, share: dict) -> list[Kpi]:
    """The four headline numbers. Deltas come from the tool's own compare_to columns — the
    API does not subtract anything, for the same reason the model does not."""
    kpis: list[Kpi] = []

    net = _first_number(totals, "net_sales_sek")
    if net is not None:
        kpis.append(Kpi(key="net_sales_sek", label="Försäljning", value=net, unit="SEK",
                        delta_pct=_first_number(totals, "net_sales_sek_delta_pct"),
                        delta_label="vs samma period förra året"))

    # Category share is weighted by own sales across subcategories rather than averaged:
    # an unweighted mean would let a tiny subcategory with a high share dominate the tile.
    rows = [r for r in (share.get("rows") or []) if not r.get("suppressed")]
    if rows:
        own = sum(float(r.get("own_net_sek") or 0) for r in rows)
        # The tool's grain is brand × subcategory, so a supplier with two brands in the same
        # subcategory gets that subcategory's total back twice. Summing the column naively
        # double-counted the denominator while own sales were counted once, understating the
        # demo tenant's share by nine points. Deduplicate on category_id first.
        category = sum({r.get("category_id"): float(r.get("category_net_sek") or 0)
                        for r in rows}.values())
        if category:
            best = min(rows, key=lambda r: r.get("rank") or 99)
            kpis.append(Kpi(
                key="category_share_pct", label="Andel av kategori",
                value=round(100 * own / category, 1), unit="%",
                rank_label=(f"#{best['rank']} av {best['n_brands']} varumärken "
                            f"i {best['subcategory']}")))

    units = _first_number(totals, "units")
    if units is not None:
        kpis.append(Kpi(key="units", label="Sålda enheter", value=units, unit="st",
                        delta_pct=_first_number(totals, "units_delta_pct"),
                        delta_label="vs samma period förra året"))

    avg_price = _first_number(totals, "avg_price_sek")
    if avg_price is not None:
        kpis.append(Kpi(key="avg_price_sek", label="Snittpris", value=avg_price, unit="SEK",
                        delta_pct=_first_number(totals, "avg_price_sek_delta_pct"),
                        delta_label="vs samma period förra året"))

    return kpis
