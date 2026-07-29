"""Tests for the semantic compiler.

These run without a database: they assert on source selection, parameterisation, the
generated SQL's shape, and that every rejection path rejects. Numeric correctness against
real rows is the job of the golden-question eval (§13.2), not of these tests.
"""

from datetime import date

import pytest
import sqlglot

from mcp_server.semantic.compiler import (
    SpecError,
    compile_query,
    resolve_time_range,
    shift_range,
)
from mcp_server.semantic.model import FACT, MAX_ROWS, ROLLUP

COVERAGE = (date(2024, 7, 1), date(2026, 6, 30))


def compile_ok(spec: dict):
    compiled = compile_query(spec, COVERAGE)
    # Every query this compiler emits must be valid Postgres. Parsing here means a broken
    # code path fails in CI rather than in front of the graders.
    sqlglot.parse_one(compiled.sql, read="postgres")
    return compiled


# ------------------------------------------------------------------ source choice


def test_simple_query_uses_the_rollup():
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["month"]})
    assert compiled.source == ROLLUP
    assert "v_sales_daily" in compiled.sql


def test_store_dimension_forces_the_fact_table():
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["store"]})
    assert compiled.source == FACT
    assert "fact_sales_line" in compiled.sql
    assert "dim_store" in compiled.sql


def test_orders_measure_forces_the_fact_table():
    """orders is fact-only on purpose: summing the rollup's n_orders double counts."""
    compiled = compile_ok({"measures": ["orders"], "dimensions": ["month"]})
    assert compiled.source == FACT
    assert "COUNT(DISTINCT f.order_id)" in compiled.sql


def test_store_filter_forces_the_fact_table():
    compiled = compile_ok({"measures": ["net_sales_sek"], "filters": {"store_ids": [1, 2]}})
    assert compiled.source == FACT


def test_region_dimension_stays_on_the_rollup():
    compiled = compile_ok({"measures": ["units"], "dimensions": ["region"]})
    assert compiled.source == ROLLUP
    assert "s.region" in compiled.sql


# --------------------------------------------------------------- parameterisation


def test_filter_values_are_bound_never_inlined():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "filters": {"region": ["Stockholms län"], "product_ids": [7, 9]},
    })
    assert "Stockholms län" not in compiled.sql
    assert ["Stockholms län"] in compiled.params
    assert [7, 9] in compiled.params


def test_injection_attempt_becomes_a_parameter_not_sql():
    hostile = "Stockholm'; DROP TABLE fact_sales_line; --"
    compiled = compile_ok({"measures": ["units"], "filters": {"region": [hostile]}})
    assert "DROP TABLE" not in compiled.sql
    assert hostile in compiled.params[-1]


def test_dates_are_bound_parameters():
    compiled = compile_ok({
        "measures": ["units"],
        "time_range": {"from": "2026-01-01", "to": "2026-03-31"},
    })
    assert date(2026, 1, 1) in compiled.params
    assert date(2026, 3, 31) in compiled.params


# -------------------------------------------------------------------- rejections


@pytest.mark.parametrize("spec", [
    {"measures": []},
    {"measures": ["margin_sek"]},
    {"measures": ["net_sales_sek"], "dimensions": ["salesperson"]},
    {"measures": ["net_sales_sek"], "dimensions": ["month", "month"]},
    {"measures": ["net_sales_sek"], "filters": {"supplier_id": 3}},
    {"measures": ["net_sales_sek"], "filters": {"channel": ["telefon"]}},
    {"measures": ["net_sales_sek"], "limit": 0},
    {"measures": ["net_sales_sek"], "time_range": {"from": "2026-06-01", "to": "2026-01-01"}},
    {"measures": ["net_sales_sek"], "time_range": "sedan_urminnes_tider"},
    {"measures": ["net_sales_sek"], "compare_to": "next_year"},
    {"measures": ["net_sales_sek"], "order_by": {"measure": "units"}},
    {"measures": ["net_sales_sek"], "order_by": {"dimension": "region"}},
])
def test_bad_specs_are_rejected(spec):
    with pytest.raises(SpecError):
        compile_query(spec, COVERAGE)


def test_supplier_id_is_not_an_expressible_filter():
    """The load-bearing isolation test: the caller cannot even name another tenant."""
    with pytest.raises(SpecError, match="okända filter"):
        compile_query({"measures": ["net_sales_sek"], "filters": {"supplier_id": 99}},
                      COVERAGE)


def test_no_supplier_predicate_is_emitted():
    """Scope comes from the connection, so it must not appear in the SQL at all."""
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["month"]})
    assert "supplier_id" not in compiled.sql


# ------------------------------------------------------------------- time ranges


def test_relative_range_anchors_on_the_data_not_today():
    assert resolve_time_range({"time_range": "last_12_months"}, COVERAGE) == (
        date(2025, 7, 1), date(2026, 6, 30))


def test_missing_range_defaults_to_last_twelve_months():
    assert resolve_time_range({}, COVERAGE) == (date(2025, 7, 1), date(2026, 6, 30))


def test_last_month_is_the_previous_whole_month():
    assert resolve_time_range({"time_range": "last_month"}, COVERAGE) == (
        date(2026, 5, 1), date(2026, 5, 31))


def test_relative_range_is_clamped_to_coverage():
    start, end = resolve_time_range({"time_range": "all_time"}, COVERAGE)
    assert (start, end) == COVERAGE


def test_same_period_last_year_shift():
    assert shift_range((date(2025, 7, 1), date(2026, 6, 30)), "same_period_last_year") == (
        date(2024, 7, 1), date(2025, 6, 30))


def test_previous_period_shift_is_a_day_count():
    window = (date(2026, 4, 1), date(2026, 6, 30))     # 91 days
    assert shift_range(window, "previous_period") == (date(2025, 12, 31), date(2026, 3, 31))


# ---------------------------------------------------------------------- compare


def test_compare_emits_delta_columns_and_a_full_outer_join():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    keys = [c["key"] for c in compiled.columns]
    assert keys == ["product", "net_sales_sek", "net_sales_sek_compare",
                    "net_sales_sek_delta_pct"]
    assert "FULL OUTER JOIN" in compiled.sql
    assert compiled.compare_range == (date(2024, 7, 1), date(2025, 6, 30))


def test_compare_over_a_date_dimension_joins_on_position_not_on_value():
    """The regression behind "visa månadsförsäljning jämfört med i fjol".

    cur.month lives in 2025-07..2026-06 and prev.month in 2024-07..2025-06, so
    joining on the value matched zero rows: 24 rows instead of 12, every delta NULL.
    The join has to be on position within the window.
    """
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert "USING (month)" not in compiled.sql
    assert "c.month__ord = pv.month__ord" in compiled.sql
    assert "DENSE_RANK() OVER (ORDER BY" in compiled.sql


def test_compare_over_a_date_dimension_returns_both_real_dates():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    keys = [c["key"] for c in compiled.columns]
    assert keys == ["month", "month_compare", "net_sales_sek",
                    "net_sales_sek_compare", "net_sales_sek_delta_pct"]
    # The comparison series has to be labellable with the period it came from.
    assert "pv.month AS month_compare" in compiled.sql


def test_the_internal_ordinal_never_reaches_the_caller():
    """__ord is a join mechanism. Leaking it would put a meaningless integer
    column in the table view and the CSV export."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert not any(c["key"].endswith("__ord") for c in compiled.columns)


def test_compare_mixing_a_date_and_a_plain_dimension():
    """Position for the date, value for the product — and DENSE_RANK rather than
    ROW_NUMBER so the repeated month keeps one shared position across products."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month", "product"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert "c.month__ord = pv.month__ord" in compiled.sql
    assert "c.product IS NOT DISTINCT FROM pv.product" in compiled.sql
    assert "COALESCE(c.product, pv.product) AS product" in compiled.sql


def test_compare_without_a_date_dimension_needs_no_ordinal():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert "__ord" not in compiled.sql
    assert "DENSE_RANK()" not in compiled.sql


def test_compare_without_dimensions_uses_cross_join():
    compiled = compile_ok({"measures": ["net_sales_sek"], "compare_to": "previous_period"})
    assert "CROSS JOIN" in compiled.sql


def test_delta_is_computed_in_sql_not_by_the_caller():
    compiled = compile_ok({"measures": ["units"], "compare_to": "previous_period"})
    assert "units_delta_pct" in compiled.sql
    assert "ROUND(" in compiled.sql


# ------------------------------------------------------------- shape and limits


def test_category_filter_expands_the_hierarchy():
    compiled = compile_ok({"measures": ["net_sales_sek"], "filters": {"category_ids": [1]}})
    assert "FROM dim_category" in compiled.sql
    assert "parent_id = ANY" in compiled.sql


def test_limit_is_clamped_to_max_rows():
    compiled = compile_ok({"measures": ["units"], "limit": 10_000_000})
    assert f"LIMIT {MAX_ROWS}" in compiled.sql


def test_time_series_is_ordered_chronologically_by_default():
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["month"]})
    assert "ORDER BY month ASC" in compiled.sql


def test_order_by_measure_requires_that_measure_to_be_selected():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "order_by": {"measure": "net_sales_sek", "dir": "desc"},
        "limit": 10,
    })
    assert "ORDER BY net_sales_sek DESC" in compiled.sql


def test_ratio_measures_are_computed_from_sums():
    """avg_price must be SUM/SUM, never AVG of a per-row ratio."""
    compiled = compile_ok({"measures": ["avg_price_sek", "discount_rate"]})
    assert "SUM(s.net_sales_sek) / NULLIF(SUM(s.qty), 0)" in compiled.sql
    assert "AVG(" not in compiled.sql


def test_columns_carry_units_and_swedish_labels():
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["region"]})
    by_key = {c["key"]: c for c in compiled.columns}
    assert by_key["net_sales_sek"]["unit"] == "SEK"
    assert by_key["net_sales_sek"]["label"] == "Nettoförsäljning"
    assert by_key["region"]["label"] == "Län"


def test_joins_are_emitted_in_dependency_order():
    compiled = compile_ok({"measures": ["units"], "dimensions": ["category", "brand"]})
    sql = compiled.sql
    assert sql.index("dim_product") < sql.index("dim_brand")
    assert sql.index("sub.category_id = p.category_id") < sql.index("top.category_id")
