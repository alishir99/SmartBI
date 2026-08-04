"""The standard dashboard - deterministic, no LLM anywhere in this file."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..agent import render
from ..config import settings
from ..deps import ScopedTenant, get_cache, get_mcp, get_supplier_scope
from ..i18n import tr
from ..mcp_client import McpClient
from ..models import AnswerCard, ChartSpec, DashboardResponse, Kpi, MoversResponse
from ..result_cache import ResultCache, from_tool_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["dashboard"])

# The dashboard opens on the last 12 months against the same period a year earlier.
DEFAULT_PERIOD = "last_12_months"

# The trend card is titled with the noun its buckets are, so the grain is the only thing
# stored: the label and the noun are both `grain.<key>` in api/i18n.py. The client owns the
# filter chips and never read the label from here.
PERIODS: dict[str, dict] = {
    "last_7_days":     {"grain": "day"},
    "last_30_days":    {"grain": "day"},
    "last_90_days":    {"grain": "week"},
    "last_month":      {"grain": "day"},
    "ytd":             {"grain": "month"},
    "last_12_months":  {"grain": "month"},
    "all_time":        {"grain": "quarter"},
}

# The comparison follows the filter: whatever window is selected, the deltas and the overlay are
# measured against the window immediately before it. That used to be a control the user set, but
# a comparison basis that can disagree with the period filter is a second thing to keep in your
# head for no gain - every delta on screen is now "vs the period before this one", always.
COMPARE_TO = "previous_period"


def _period_spec(period: str) -> tuple[dict, dict]:
    """Resolve a period key to its time_range and its presentation settings."""
    key = period if period in PERIODS else DEFAULT_PERIOD
    return {"relative": key}, PERIODS[key]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(period: str = Query(DEFAULT_PERIOD,
                                        description="Nyckel ur PERIODS; okänt värde faller "
                                                    "tillbaka på standardfönstret."),
                    lang: str | None = Query(None, description="Svarsspråk; se /api/config."),
                    tenant: ScopedTenant = Depends(get_supplier_scope),
                    mcp: McpClient = Depends(get_mcp),
                    cache: ResultCache = Depends(get_cache)) -> DashboardResponse:
    supplier_id = tenant.supplier_id
    assert supplier_id is not None  # get_supplier_scope guarantees this

    window, period_settings = _period_spec(period)
    # One window, one comparison: the same `compare_to` reaches the KPI deltas, the trend
    # overlay and the share tile, so no two numbers on screen are measured against different
    # periods.
    compare: dict = {"compare_to": COMPARE_TO}

    totals_args: dict = {"measures": ["net_sales_sek", "units", "avg_price_sek"],
                         "time_range": window, **compare}

    # Named, because they are cached with the result and are what a saved or shared card
    # re-runs. Passing `{}` here meant every card pinned from the dashboard came back as
    # "Kunde inte uppdatera …" the next time it was opened.
    trend_args: dict = {
        # All three headline measures, so the KPI sparklines cost no extra query. The trend
        # card charts the first of them; `propose_chart` picks measures[0].
        "measures": ["net_sales_sek", "units", "avg_price_sek"],
        "dimensions": [period_settings["grain"]],
        "time_range": window,
        # `propose_chart` overlays this on the trend line.
        **compare,
    }
    top_products_args: dict = {
        "measures": ["net_sales_sek", "units"],
        "dimensions": ["product"],
        "time_range": window,
        "order_by": {"measure": "net_sales_sek", "dir": "desc"},
        "limit": 10,
    }
    by_region_args: dict = {
        "measures": ["net_sales_sek"],
        "dimensions": ["region"],
        "time_range": window,
        "order_by": {"measure": "net_sales_sek", "dir": "desc"},
    }

    try:
        # One MCP session, four queries, run concurrently - the tiles are independent and the
        # rollup makes each of them cheap.
        totals, trend, top_products, by_region, share, capabilities = await asyncio.gather(
            _call(mcp, supplier_id, "query_sales", totals_args),
            _call(mcp, supplier_id, "query_sales", trend_args),
            _call(mcp, supplier_id, "query_sales", top_products_args),
            _call(mcp, supplier_id, "query_sales", by_region_args),
            _call(mcp, supplier_id, "query_market_share", {"time_range": window, **compare}),
            # Calendar only - a dimension read, not a trip to the fact table.
            _call(mcp, supplier_id, "get_capabilities", {}),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("dashboard failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            tr("dash.error", error=exc)) from exc

    # Before caching, so the average is part of the frozen result the chart, the table view and
    # the CSV export all read.
    average = add_moving_average(trend, "net_sales_sek")

    payloads: dict[str, tuple[str, dict, dict]] = {
        "trend": ("query_sales", trend_args, trend),
        "top_products": ("query_sales", top_products_args, top_products),
        "by_region": ("query_sales", by_region_args, by_region),
    }
    cached = {
        name: cache.put(from_tool_result(supplier_id=supplier_id, tool=tool,
                                         tool_args=args, payload=payload))
        for name, (tool, args, payload) in payloads.items()
    }

    return DashboardResponse(
        kpis=_kpis(totals, share, trend),
        cards=[
            _trend_card(cached["trend"],
                        tr("dash.trend", noun=tr(f"grain.{period_settings['grain']}")),
                        average=average,
                        markers=campaign_markers(cached["trend"], capabilities),
                        # One window, one comparison: if the tiles cannot honestly show it, the
                        # chart must not draw it either.
                        overlay=comparison_is_covered(totals)),
            _card(cached["top_products"], tr("dash.top_products")),
            _card(cached["by_region"], tr("dash.by_region")),
        ],
    )


@router.get("/regions")
async def regions(tenant: ScopedTenant = Depends(get_supplier_scope),
                  mcp: McpClient = Depends(get_mcp)) -> list[dict]:
    """Every region in the warehouse with its centroid, so the map can be drawn for any market.

    The client used to carry a table of Sweden's 21 counties and their coordinates, which was
    wrong for every other country and unfixable without redrawing one. These come off
    `dim_store`, which means a warehouse with no geocoded stores honestly returns nothing and
    the client hides its map tab rather than inventing positions.
    """
    supplier_id = tenant.supplier_id
    assert supplier_id is not None
    try:
        capabilities = await _call(mcp, supplier_id, "get_capabilities", {})
    except Exception as exc:  # noqa: BLE001
        logger.exception("regions failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            tr("dash.error", error=exc)) from exc
    return [region for region in (capabilities.get("regions") or [])
            if region.get("lat") is not None and region.get("lon") is not None]


MOVERS_LIMIT = 10

# Ranked on kronor, not on percent. A percentage ranking put one product that went from 400 kr
# to 6 000 kr at +1 400 % on the axis and left the other nine bars invisible beside it - a chart
# whose caveat explained why it could not be read. The percentage is still on the card, in the
# table view, where it says something about the product rather than about the axis.
def _movers_caveat() -> str:
    return tr("dash.movers_caveat", currency=settings.app_currency)


@router.get("/movers", response_model=MoversResponse)
async def movers(period: str = Query(DEFAULT_PERIOD),
                 lang: str | None = Query(None),
                 tenant: ScopedTenant = Depends(get_supplier_scope),
                 mcp: McpClient = Depends(get_mcp),
                 cache: ResultCache = Depends(get_cache)) -> MoversResponse:
    """Biggest risers and biggest fallers - the question a supplier opens a product page to ask.

    Answerable only since the compiler learned to sort on the derived `_delta_pct` column; "vilka
    produkter tappar mest" could not be expressed before that.
    """
    supplier_id = tenant.supplier_id
    assert supplier_id is not None

    window, _period = _period_spec(period)

    def args(direction: str) -> dict:
        return {
            "measures": ["net_sales_sek"],
            "dimensions": ["product"],
            "time_range": window,
            "compare_to": COMPARE_TO,
            "order_by": {"field": "net_sales_sek_delta", "dir": direction},
            "limit": MOVERS_LIMIT,
        }

    try:
        risers, fallers = await asyncio.gather(
            _call(mcp, supplier_id, "query_sales", args("desc")),
            _call(mcp, supplier_id, "query_sales", args("asc")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("movers failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            tr("dash.movers_error", error=exc)) from exc

    return MoversResponse(cards=[
        _movers_card(cache, supplier_id, risers, tr("dash.movers_up"), "desc", args("desc")),
        _movers_card(cache, supplier_id, fallers, tr("dash.movers_down"), "asc", args("asc")),
    ])


def _movers_card(cache: ResultCache, supplier_id: int, payload: dict, title: str,
                 direction: str, tool_args: dict) -> AnswerCard:
    """The one card `propose_chart` cannot pick: the change *is* the measure here.

    Everywhere else a delta column is kept off the value axis, because a change next to a level
    doubles the bars. On this card the change is the only thing asked about, so it has the axis
    to itself - in kronor, which is a readable axis, unlike a percentage from an arbitrary base.
    """
    result = cache.put(from_tool_result(supplier_id=supplier_id, tool="query_sales",
                                        tool_args=tool_args, payload=payload))
    return AnswerCard(
        status="ok",
        chart=ChartSpec(type="bar", x="product", y=["net_sales_sek_delta"],
                        sort=cast(Literal["asc", "desc"], direction),
                        limit=MOVERS_LIMIT, title=title),
        caveats=[_movers_caveat()],
        query_id=result.query_id,
        columns=render.to_columns(result),
        provenance=render.build_provenance(result),
    )


async def _call(mcp: McpClient, supplier_id: int, tool: str, args: dict) -> dict:
    return await mcp.call(supplier_id, tool, args)


# Three buckets: long enough to take the spike out of a single month, short enough that a real
# turn still shows up inside a twelve-point window.
MA_WINDOW = 3


def _date_axis(columns: list[dict]) -> str | None:
    """The time axis - the date column that is not the comparison window's echo."""
    return next((c["key"] for c in columns
                 if c.get("type") == "date" and not c["key"].endswith("_compare")), None)


def add_moving_average(payload: dict, measure: str) -> str | None:
    """Add a trailing `MA_WINDOW`-bucket mean of `measure` to a time series, in place.

    A bar per period says what each period did; the line says which way the run of them is
    going, which is what a spiky monthly series makes hard to read by eye. Returns the new
    column's key, or None when the series is too short for an average to say anything.
    """
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    axis = _date_axis(columns)
    if axis is None or len(rows) <= MA_WINDOW:
        return None

    # The average is only an average if the buckets are in time order, and the sparklines read
    # the same rows expecting oldest first.
    rows.sort(key=lambda row: str(row.get(axis) or ""))
    key = f"{measure}_ma"
    values = [row.get(measure) for row in rows]
    for index, row in enumerate(rows):
        window = values[max(0, index - MA_WINDOW + 1):index + 1]
        # A short or gappy window would draw a line that is not the average it claims to be.
        row[key] = (round(sum(window) / MA_WINDOW, 2)
                    if len(window) == MA_WINDOW and None not in window else None)

    unit = next((c.get("unit") for c in columns if c.get("key") == measure), None)
    columns.append({"key": key, "type": "number",
                    "label": tr("dash.moving_average", window=MA_WINDOW), "unit": unit})
    payload["columns"] = columns
    return key


def _trend_card(result, title: str, average: str | None, markers: list[str],
                overlay: bool) -> AnswerCard:
    """Both windows as bars, with the moving average as the only line over them.

    `propose_chart` draws two lines here, which reads as two trends running side by side. Bars
    read as what this actually is - the same buckets, one window apart - and leaving the line
    to the average makes it the shape the eye follows.
    """
    measure, compare = "net_sales_sek", "net_sales_sek_compare"
    y = [measure]
    if overlay and any(c["key"] == compare for c in result.columns):
        y.append(compare)
    if average:
        y.append(average)
    return AnswerCard(
        status="ok",
        chart=ChartSpec(type="bar", x=_date_axis(result.columns), y=y, title=title,
                        markers=markers,
                        marker_label=tr("dash.campaign_markers") if markers else None),
        query_id=result.query_id,
        columns=render.to_columns(result),
        provenance=render.build_provenance(result),
    )


def campaign_markers(result, capabilities: dict) -> list[str]:
    """Which x values on this chart fall inside a campaign window.

    November spikes every year and nothing on screen said why. The warehouse stores the
    campaign's days but not its name, so a marker can say *that* a campaign ran and never what
    it was called - which is still the difference between an unexplained spike and an
    explained one.
    """
    windows = ((capabilities.get("time") or {}).get("campaigns") or [])
    if not windows:
        return []

    axis = _date_axis(result.columns)
    if axis is None:
        return []

    ranges = [(w["from"], w["to"]) for w in windows if w.get("from") and w.get("to")]
    values = sorted(str(row[axis]) for row in result.rows if row.get(axis))
    if not ranges or not values:
        return []

    # Every grain - day, week, month, quarter - labels its bucket with the bucket's first day,
    # so a bucket runs until the next one begins. That makes this grain-agnostic: no branch per
    # grain, and a campaign starting mid-month still lands in that month.
    last = str((result.meta or {}).get("time_range", {}).get("to") or values[-1][:10])
    marked = []
    for index, value in enumerate(values):
        starts = value[:10]
        ends = _day_before(values[index + 1][:10]) if index + 1 < len(values) else last
        if any(window_from <= ends and window_to >= starts for window_from, window_to in ranges):
            marked.append(value)
    return marked


def _day_before(iso: str) -> str:
    try:
        return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()
    except ValueError:
        return iso


def _card(result, title: str) -> AnswerCard:
    """A dashboard tile is the same AnswerCard the chat produces - one card type, two producers
    (§2).

    No subtitle: the card falls back to the window in `provenance.time_range`, which is what the
    tool actually ran. A literal here goes stale the moment the user picks another period.
    """
    return AnswerCard(
        status="ok",
        chart=render.propose_chart(result, title=title),
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


def comparison_is_covered(totals: dict) -> bool:
    """Is the comparison window actually inside the data?

    The period before `all_time` is entirely before the warehouse begins, so the comparison is
    empty or half-missing and the tile reads +113 % for a business that did not double. Nothing
    on screen shows that the window falls off the end of the data, so this one is ours to catch.
    """
    meta = totals.get("meta") or {}
    compare = meta.get("compare_range") or {}
    coverage = meta.get("coverage") or {}
    if not compare.get("from") or not coverage.get("from"):
        # No comparison was asked for, or no coverage to check it against.
        return True
    return str(compare["from"]) >= str(coverage["from"])


def _kpis(totals: dict, share: dict, trend: dict | None = None,
          delta_label: str | None = None) -> list[Kpi]:
    """The four headline numbers. `delta_label` names the window every delta is measured on."""
    trend = trend or {}
    delta_label = tr("dash.delta_label") if delta_label is None else delta_label
    kpis: list[Kpi] = []

    # A delta measured against a window the data does not cover is worse than no delta: it is
    # a number, so it will be read as one.
    covered = comparison_is_covered(totals)
    delta_label = delta_label if covered else None

    def delta(key: str) -> float | None:
        return _first_number(totals, key) if covered else None

    net = _first_number(totals, "net_sales_sek")
    if net is not None:
        kpis.append(Kpi(key="net_sales_sek", label=tr("kpi.net_sales"), value=net,
                        unit=settings.app_currency,
                        delta_pct=delta("net_sales_sek_delta_pct"),
                        delta_label=delta_label,
                        spark=_spark(trend, "net_sales_sek")))

    rows = [r for r in (share.get("rows") or []) if not r.get("suppressed")]
    if rows:
        current = _weighted_share(rows, "own_net_sek", "category_net_sek")
        if current is not None:
            best = min(rows, key=lambda r: r.get("rank") or 99)
            previous = _weighted_share(rows, "own_net_sek_compare",
                                       "category_net_sek_compare") if covered else None
            kpis.append(Kpi(
                key="category_share_pct", label=tr("kpi.category_share"),
                value=current, unit="%",
                # Percentage points: the frontend renders a '%' KPI's delta as p.e.
                delta_pct=None if previous is None else round(current - previous, 1),
                delta_label=delta_label,
                # No sparkline: query_market_share aggregates over the whole window and has no
                # month dimension, so there is no series to draw without a new tool shape.
                rank_label=tr("kpi.rank", rank=best["rank"], total=best["n_brands"],
                             subcategory=best["subcategory"])))

    units = _first_number(totals, "units")
    if units is not None:
        kpis.append(Kpi(key="units", label=tr("kpi.units"), value=units, unit="st",
                        delta_pct=delta("units_delta_pct"),
                        delta_label=delta_label,
                        spark=_spark(trend, "units")))

    avg_price = _first_number(totals, "avg_price_sek")
    if avg_price is not None:
        kpis.append(Kpi(key="avg_price_sek", label=tr("kpi.avg_price"), value=avg_price,
                        unit=settings.app_currency,
                        delta_pct=delta("avg_price_sek_delta_pct"),
                        delta_label=delta_label,
                        spark=_spark(trend, "avg_price_sek")))

    return kpis
