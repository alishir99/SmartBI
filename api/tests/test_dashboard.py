"""Tests for the deterministic dashboard KPI assembly (§2, requirement 1)."""

from __future__ import annotations

from api.result_cache import CachedResult
from api.routes.dashboard import BASES, DEFAULT_BASIS, PERIODS, _card, _kpis

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


# --------------------------------------------------------------- the comparison basis

def test_every_basis_but_none_is_a_compare_to_the_compiler_implements():
    """A basis the compiler does not know would fail the whole dashboard, not one tile."""
    assert set(BASES) - {"none"} == {"previous_period", "same_period_last_year"}


def test_every_tile_names_the_basis_it_was_measured_on():
    """One control, one meaning: no two deltas on screen may carry different labels."""
    share = {"rows": [compared(share_row("Bruksbo", 10, own=300.0, category=1000.0),
                               own=250.0, category=1000.0)]}

    kpis = _kpis(TOTALS, share, TREND, BASES["previous_period"])

    assert {k.delta_label for k in kpis} == {"vs föregående period"}


def test_no_comparison_leaves_every_tile_without_a_label():
    kpis = _kpis(TOTALS, NO_SHARE, TREND, BASES["none"])

    assert all(k.delta_label is None for k in kpis)


def test_the_default_basis_is_one_of_the_offered_bases():
    assert DEFAULT_BASIS in BASES
    # Every period is now offered every basis; the gate that dropped the comparison on some
    # windows was there because the user had not chosen. Now they choose.
    assert all("compare" not in settings for settings in PERIODS.values())


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
