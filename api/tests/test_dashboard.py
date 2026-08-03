"""Tests for the deterministic dashboard KPI assembly (§2, requirement 1)."""

from __future__ import annotations

from api.result_cache import CachedResult, ResultCache
from api.routes.dashboard import (
    COMPARE_TO,
    MA_WINDOW,
    MOVERS_LIMIT,
    PERIODS,
    _card,
    _kpis,
    _movers_card,
    _trend_card,
    add_moving_average,
    campaign_markers,
    comparison_is_covered,
)

TOTALS = {"rows": [{"net_sales_sek": 1_000_000.0, "units": 500, "avg_price_sek": 2000.0,
                    "net_sales_sek_delta_pct": 12.5, "units_delta_pct": 3.0,
                    "avg_price_sek_delta_pct": 9.2}]}

NO_SHARE: dict = {"rows": []}


def share_row(brand: str, category_id: int, own: float, category: float, **kwargs) -> dict:
    return {"brand": brand, "subcategory": f"kategori-{category_id}",
            "category_id": category_id, "own_net_sek": own, "own_units": 100,
            "category_net_sek": category, "n_brands": kwargs.get("n_brands", 8),
            "rank": kwargs.get("rank", 3), "suppressed": kwargs.get("suppressed", False),
            "share_pct": round(100 * own / category, 2)}


def share_kpi(kpis):
    return next((k for k in kpis if k.key == "category_share_pct"), None)


# ------------------------------------------------------------------ category-share weighting

def test_two_brands_in_one_subcategory_count_the_category_total_once():
    """The D3 regression: same category_id twice must not double the denominator."""
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0),
                      share_row("Nordvik", 10, own=200.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    # 500 own / 1000 category = 50 %, not 500 / 2000 = 25 %.
    assert kpi is not None
    assert kpi.value == 50.0


def test_distinct_subcategories_each_contribute_their_own_total():
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0),
                      share_row("Bruksbo", 20, own=100.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.value == 20.0


def test_the_mixed_case_dedupes_per_category_not_globally():
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0),
                      share_row("Nordvik", 10, own=200.0, category=1000.0),
                      share_row("Bruksbo", 20, own=250.0, category=2000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    # own 750 over a denominator of 1000 + 2000.
    assert kpi.value == 25.0


def test_suppressed_rows_are_excluded_from_both_sides():
    """A k-anonymity-suppressed row has no category_net_sek; it must not reach either sum."""
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0),
                      {"brand": "Nordvik", "subcategory": "smal", "category_id": 99,
                       "own_net_sek": 5000.0, "own_units": 2, "n_brands": 2,
                       "suppressed": True, "reason": "för få varumärken"}]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.value == 30.0


def test_the_rank_label_names_the_strongest_subcategory():
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0, rank=4),
                      share_row("Bruksbo", 20, own=100.0, category=1000.0, rank=1,
                                n_brands=12)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.rank_label == "#1 av 12 varumärken i kategori-20"


def test_a_zero_category_total_drops_the_tile_rather_than_dividing_by_zero():
    share = {"rows": [share_row("Bruksbo", 10, own=0.0, category=1.0) | {"category_net_sek": 0}]}

    assert share_kpi(_kpis(TOTALS, share)) is None


def test_no_share_rows_drops_the_tile():
    assert share_kpi(_kpis(TOTALS, NO_SHARE)) is None


# ------------------------------------------------------------- the share tile's comparison

def compared(row: dict, own: float, category: float) -> dict:
    return row | {"own_net_sek_compare": own, "category_net_sek_compare": category}


def test_the_share_tile_moves_in_percentage_points():
    """The one number a supplier most needs to see move, and the one that could not."""
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=250.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.value == 30.0
    # 30,0 − 25,0. The tile's unit is '%', which the frontend renders as p.e.
    assert kpi.delta_pct == 5.0
    assert kpi.unit == "%"


def test_the_comparison_denominator_is_deduplicated_too():
    """D3 again: without this the two windows disagree by roughly nine points."""
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=200.0, category=1000.0),
                      compared(share_row("Nordvik", 10, own=200.0, category=1000.0),
                               own=200.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    # 400 / 1000 = 40 %, not 400 / 2000 = 20 %; current is 500 / 1000 = 50 %.
    assert kpi.value == 50.0
    assert kpi.delta_pct == 10.0


def test_a_partially_compared_result_shows_no_delta_rather_than_a_mixed_one():
    """Summing rows that carry a comparison with rows that do not puts two periods in one
    figure — no delta is the honest answer."""
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=250.0, category=1000.0),
                      share_row("Bruksbo", 20, own=100.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.value == 20.0
    assert kpi.delta_pct is None


def test_a_window_with_no_comparison_keeps_the_tile():
    """`all_time` has no honest counterpart; the share still has to be shown."""
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0)]}

    kpi = share_kpi(_kpis(TOTALS, share))

    assert kpi.value == 30.0
    assert kpi.delta_pct is None


# ------------------------------------------------------------------------ the other tiles

def test_the_remaining_kpis_pass_through_the_tools_own_deltas():
    kpis = {k.key: k for k in _kpis(TOTALS, NO_SHARE)}

    assert [k for k in kpis] == ["net_sales_sek", "units", "avg_price_sek"]
    assert kpis["net_sales_sek"].value == 1_000_000.0
    assert kpis["net_sales_sek"].delta_pct == 12.5
    assert kpis["units"].unit == "st"
    assert kpis["avg_price_sek"].delta_pct == 9.2


def test_a_missing_measure_drops_only_its_own_tile():
    totals = {"rows": [{"net_sales_sek": 42.0}]}

    kpis = _kpis(totals, NO_SHARE)

    assert [k.key for k in kpis] == ["net_sales_sek"]


def test_an_empty_totals_payload_yields_no_kpis():
    assert _kpis({"rows": []}, NO_SHARE) == []


# --------------------------------------------------------------------------- sparklines

TREND = {"rows": [{"month": "2026-01-01", "net_sales_sek": 10.0, "units": 1,
                   "avg_price_sek": 10.0},
                  {"month": "2026-02-01", "net_sales_sek": 30.0, "units": 3,
                   "avg_price_sek": 10.0},
                  {"month": "2026-03-01", "net_sales_sek": 20.0, "units": 2,
                   "avg_price_sek": 10.0}]}


def test_each_measure_gets_its_own_series_in_row_order():
    kpis = {k.key: k for k in _kpis(TOTALS, NO_SHARE, TREND)}

    assert kpis["net_sales_sek"].spark == [10.0, 30.0, 20.0]
    assert kpis["units"].spark == [1.0, 3.0, 2.0]


def test_a_period_missing_from_the_current_window_is_a_gap_not_a_zero():
    """Under compare_to the outer join yields rows that exist only in the earlier window."""
    trend = {"rows": TREND["rows"] + [{"month": None, "net_sales_sek": None, "units": None}]}

    kpis = {k.key: k for k in _kpis(TOTALS, NO_SHARE, trend)}

    assert kpis["net_sales_sek"].spark == [10.0, 30.0, 20.0]


def test_two_points_are_a_line_not_a_shape_and_are_dropped():
    trend = {"rows": TREND["rows"][:2]}

    assert _kpis(TOTALS, NO_SHARE, trend)[0].spark == []


def test_no_trend_leaves_every_tile_without_a_sparkline():
    assert all(k.spark == [] for k in _kpis(TOTALS, NO_SHARE))


def test_the_share_tile_carries_no_sparkline():
    """query_market_share has no month dimension, so there is no series to draw."""
    share = {"rows": [share_row("Bruksbo", 10, own=300.0, category=1000.0)]}

    assert share_kpi(_kpis(TOTALS, share, TREND)).spark == []


# --------------------------------------------------------------- the comparison window

def test_the_comparison_is_one_the_compiler_implements():
    """A `compare_to` the compiler does not know would fail the whole dashboard, not one tile."""
    assert COMPARE_TO == "previous_period"


def test_every_tile_names_the_window_it_was_measured_on():
    """One window, one comparison: no two deltas on screen may carry different labels."""
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=250.0, category=1000.0)]}

    kpis = _kpis(TOTALS, share, TREND)

    assert {k.delta_label for k in kpis} == {"vs föregående period"}


COVERAGE = {"from": "2024-07-01", "to": "2026-06-30"}


def totals(compare_from: str | None) -> dict:
    meta = {"coverage": COVERAGE,
            **({"compare_range": {"from": compare_from, "to": "2025-06-30"}}
               if compare_from else {})}
    return {**TOTALS, "meta": meta}


def test_a_comparison_window_the_data_does_not_reach_shows_no_delta():
    """`all_time` vs last year reaches a year before the warehouse begins, and the tile read
    +113 % for a business that did not double."""
    kpis = _kpis(totals("2023-07-01"), NO_SHARE, TREND)

    assert all(k.delta_pct is None for k in kpis)
    assert all(k.delta_label is None for k in kpis)


def test_a_covered_comparison_window_keeps_its_deltas():
    assert _kpis(totals("2024-07-01"), NO_SHARE, TREND)[0].delta_pct == 12.5


def test_the_share_tile_follows_the_same_coverage_rule():
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=250.0, category=1000.0)]}

    assert share_kpi(_kpis(totals("2023-07-01"), share, TREND)).delta_pct is None
    assert share_kpi(_kpis(totals("2024-07-01"), share, TREND)).delta_pct == 5.0


def test_no_comparison_at_all_is_not_an_uncovered_one():
    """A tool result with no compare_range asked for no window, so nothing is outside coverage."""
    assert comparison_is_covered(totals(None)) is True


def test_the_chart_drops_the_overlay_when_the_tiles_drop_the_delta():
    """One window, one comparison: no mixed state on screen."""
    result = trend_result(MONTHS)
    result.columns.append({"key": "net_sales_sek_compare", "type": "number",
                           "label": "Netto (jämförelse)", "unit": "SEK"})
    for row in result.rows:
        row["net_sales_sek_compare"] = 0.5

    def y(overlay: bool) -> list[str]:
        return _trend_card(result, "Trend", average=None, markers=[], overlay=overlay).chart.y

    assert y(True) == ["net_sales_sek", "net_sales_sek_compare"]
    assert y(False) == ["net_sales_sek"]


def test_every_period_carries_the_grain_and_the_noun_its_title_is_built_from():
    """The trend card's title follows the filter — a literal 'per månad' goes stale on day 1."""
    assert all({"grain", "noun", "label"} <= set(settings) for settings in PERIODS.values())


# ------------------------------------------------------------------ the moving average

def series(values: list[float | None]) -> dict:
    return {"columns": [{"key": "month", "type": "date", "label": "Månad"},
                        {"key": "net_sales_sek", "type": "number", "label": "Netto",
                         "unit": "SEK"}],
            "rows": [{"month": f"2026-{index + 1:02d}-01", "net_sales_sek": value}
                     for index, value in enumerate(values)]}


def test_the_average_is_the_trailing_mean_over_the_window():
    payload = series([10.0, 20.0, 30.0, 40.0])

    key = add_moving_average(payload, "net_sales_sek")

    assert key == "net_sales_sek_ma"
    # The first MA_WINDOW - 1 buckets have no full window behind them.
    assert [row[key] for row in payload["rows"]] == [None, None, 20.0, 30.0]


def test_a_gap_in_the_window_yields_no_average_rather_than_a_wrong_one():
    payload = series([10.0, None, 30.0, 40.0])

    key = add_moving_average(payload, "net_sales_sek")

    assert [row[key] for row in payload["rows"]] == [None, None, None, None]


def test_a_series_too_short_to_average_gets_no_column():
    payload = series([10.0] * MA_WINDOW)

    assert add_moving_average(payload, "net_sales_sek") is None
    assert [c["key"] for c in payload["columns"]] == ["month", "net_sales_sek"]


def test_the_buckets_are_put_in_time_order_first():
    """The rows also feed the sparklines, which read them oldest first."""
    payload = series([10.0, 20.0, 30.0, 40.0])
    payload["rows"].reverse()

    add_moving_average(payload, "net_sales_sek")

    assert [row["month"] for row in payload["rows"]] == sorted(
        row["month"] for row in payload["rows"])


def test_the_average_shares_the_measures_unit_so_it_can_share_the_axis():
    payload = series([10.0, 20.0, 30.0, 40.0])

    key = add_moving_average(payload, "net_sales_sek")

    assert payload["columns"][-1] == {"key": key, "type": "number",
                                      "label": f"Glidande medel ({MA_WINDOW} perioder)",
                                      "unit": "SEK"}


def test_the_trend_card_draws_bars_with_the_average_on_the_same_axis():
    card = _trend_card(trend_result(MONTHS), "Försäljning per månad",
                       average="net_sales_sek_ma", markers=[], overlay=True)

    assert card.chart.type == "bar"
    assert card.chart.x == "month"
    assert card.chart.y == ["net_sales_sek", "net_sales_sek_ma"]


# --------------------------------------------------------------- campaign annotations

MONTHS = ["2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01"]

# Black Week and Mellandagsrea, as dim_date carries them: days, and an id with no name.
CAPABILITIES = {"time": {"campaigns": [
    {"campaign_id": 1, "from": "2025-11-21", "to": "2025-11-30"},
    {"campaign_id": 2, "from": "2025-12-26", "to": "2025-12-31"},
]}}


def trend_result(values: list[str], until: str = "2026-01-31") -> CachedResult:
    return CachedResult(
        query_id="q_1", supplier_id=1, tool="query_sales", tool_args={},
        columns=[{"key": "month", "type": "date", "label": "Månad"},
                 {"key": "net_sales_sek", "type": "number", "label": "Netto"}],
        rows=[{"month": value, "net_sales_sek": 1.0} for value in values],
        row_count=len(values), truncated=False,
        meta={"tool": "query_sales", "source": "mv_sales_daily", "scope": "supplier:abcd",
              "time_range": {"from": values[0], "to": until},
              "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
              "executed_at": "2026-08-01T10:00:00Z"})


def test_a_campaign_inside_a_month_marks_that_month():
    """November spikes every year and nothing on screen said why."""
    assert campaign_markers(trend_result(MONTHS), CAPABILITIES) == ["2025-11-01", "2025-12-01"]


def test_a_month_with_no_campaign_is_left_alone():
    october = trend_result(["2025-10-01"], until="2025-10-31")

    assert campaign_markers(october, CAPABILITIES) == []


def test_the_bucket_is_read_from_the_data_not_assumed_to_be_a_month():
    """Days, weeks, months and quarters all label the bucket with its first day, so the next
    bucket's own value is what bounds this one — no branch per grain."""
    quarters = ["2025-07-01", "2025-10-01", "2026-01-01"]

    # Both campaigns fall inside Q4, and neither is in Q3 or Q1.
    assert campaign_markers(trend_result(quarters), CAPABILITIES) == ["2025-10-01"]


def test_the_last_bucket_runs_to_the_end_of_the_window_the_tool_ran():
    """Its span has no next value to bound it, so `meta.time_range.to` does."""
    november = trend_result(["2025-11-01"], until="2025-11-30")

    assert campaign_markers(november, CAPABILITIES) == ["2025-11-01"]


def test_no_campaigns_in_the_calendar_means_no_markers():
    assert campaign_markers(trend_result(MONTHS), {"time": {"campaigns": []}}) == []
    assert campaign_markers(trend_result(MONTHS), {}) == []


def test_a_chart_with_no_date_axis_is_never_annotated():
    result = CachedResult(
        query_id="q_1", supplier_id=1, tool="query_sales", tool_args={},
        columns=[{"key": "product", "type": "text", "label": "Produkt"}],
        rows=[{"product": "A"}], row_count=1, truncated=False,
        meta={"time_range": {"from": "2025-11-01", "to": "2025-11-30"}})

    assert campaign_markers(result, CAPABILITIES) == []


def test_the_marked_card_says_what_the_lines_mean():
    """A line nobody can read is decoration."""
    card = _trend_card(trend_result(MONTHS), "Försäljning per månad", average=None,
                       markers=campaign_markers(trend_result(MONTHS), CAPABILITIES),
                       overlay=True)

    assert card.chart.markers == ["2025-11-01", "2025-12-01"]
    assert card.chart.marker_label is not None
    assert "kampanj" in card.chart.marker_label.lower()


def test_an_unmarked_card_carries_no_label():
    card = _trend_card(trend_result(["2025-10-01"]), "Försäljning per månad", average=None,
                       markers=[], overlay=True)

    assert card.chart.markers == []
    assert card.chart.marker_label is None


# ------------------------------------------------------------------------ the movers page

MOVERS_PAYLOAD = {
    "rows": [{"product": "Nordström TV N100", "net_sales_sek": 300.0,
              "net_sales_sek_compare": 100.0, "net_sales_sek_delta": 200.0,
              "net_sales_sek_delta_pct": 200.0},
             {"product": "Nordström Soundbar S5", "net_sales_sek": 110.0,
              "net_sales_sek_compare": 100.0, "net_sales_sek_delta": 10.0,
              "net_sales_sek_delta_pct": 10.0}],
    "row_count": 2,
    "columns": [{"key": "product", "type": "text", "label": "Produkt"},
                {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"},
                {"key": "net_sales_sek_compare", "type": "number",
                 "label": "Netto (jämförelse)", "unit": "SEK"},
                {"key": "net_sales_sek_delta", "type": "number",
                 "label": "Netto (förändring)", "unit": "SEK"},
                {"key": "net_sales_sek_delta_pct", "type": "number",
                 "label": "Netto (förändring i %)", "unit": "%"}],
    "meta": {"tool": "query_sales", "source": "mv_sales_daily (rollup)",
             "scope": "supplier:abcd",
             "time_range": {"from": "2025-07-01", "to": "2026-06-30"},
             "compare_range": {"from": "2024-07-01", "to": "2025-06-30"},
             "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
             "executed_at": "2026-08-01T10:00:00Z"},
}


MOVERS_ARGS = {"measures": ["net_sales_sek"], "dimensions": ["product"],
               "order_by": {"field": "net_sales_sek_delta", "dir": "desc"}}


def movers_card(direction: str = "desc"):
    return _movers_card(ResultCache(), 1, MOVERS_PAYLOAD, "Största uppgångar", direction,
                        MOVERS_ARGS)


def test_the_card_carries_the_arguments_that_produced_it():
    """A card is saved and shared as tool + arguments, not as a picture. Caching it with `{}`
    meant everything pinned from the dashboard came back as "Kunde inte uppdatera …"."""
    assert movers_card().provenance is not None
    assert movers_card().provenance.tool_args == MOVERS_ARGS


def test_the_change_is_the_axis_on_this_card_and_only_this_card():
    """Everywhere else a delta is kept off the value axis; here it is the only measure — and it
    is the change in kronor, because a percentage from an arbitrary base draws one bar and nine
    invisible ones."""
    card = movers_card()

    assert card.chart is not None
    assert card.chart.y == ["net_sales_sek_delta"]
    assert card.chart.x == "product"
    assert card.chart.limit == MOVERS_LIMIT


def test_the_direction_reaches_the_chart_so_fallers_lead_with_the_worst():
    assert movers_card("asc").chart.sort == "asc"
    assert movers_card("desc").chart.sort == "desc"


def test_the_card_says_the_percentage_can_come_from_a_small_base():
    """No invented threshold — what counts as too small is the reader's call, so say so."""
    caveats = " ".join(movers_card().caveats)

    assert "procent" in caveats
    assert "Tabell" in caveats, "and point at where the kronor are"


def test_the_kronor_are_still_readable_behind_the_percentage():
    keys = [c.key for c in movers_card().columns]

    assert "net_sales_sek" in keys
    assert "net_sales_sek_compare" in keys


# ------------------------------------------------------------------------- the tiles

def test_a_tile_carries_no_hardcoded_period_subtitle():
    """The subtitle must come from the window the tool ran, which the card derives from
    provenance. A literal here read 'senaste 12 månaderna' under every period filter."""
    result = CachedResult(
        query_id="q_1", supplier_id=1, tool="query_sales", tool_args={},
        columns=[{"key": "month", "type": "date", "label": "Månad"},
                 {"key": "net_sales_sek", "type": "number", "label": "Netto"}],
        rows=[{"month": "2024-07-01", "net_sales_sek": 1.0},
              {"month": "2024-08-01", "net_sales_sek": 2.0}],
        row_count=2, truncated=False,
        meta={"tool": "query_sales", "source": "mv_sales_daily", "scope": "supplier:abcd",
              "time_range": {"from": "2024-07-01", "to": "2026-04-30"},
              "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
              "executed_at": "2026-08-01T10:00:00Z"})

    card = _card(result, "Försäljning per månad")

    assert card.chart is not None
    assert card.chart.subtitle is None
    assert card.provenance is not None
    assert card.provenance.time_range.to == "2026-04-30"
