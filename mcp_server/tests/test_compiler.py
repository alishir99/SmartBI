"""Tests for the semantic compiler."""

from datetime import date
from decimal import Decimal

import pytest
import sqlglot

from mcp_server.config import settings
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
    # Every query this compiler emits must be valid Postgres.
    sqlglot.parse_one(compiled.sql, read="postgres")
    return compiled




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
    # Post-aggregate: every reference has to name a column the query actually emits.
    {"measures": ["net_sales_sek"], "order_by": {"field": "net_sales_sek_delta_pct"}},
    {"measures": ["net_sales_sek"], "order_by": {"field": "net_sales_sek_pct_of_total"}},
    {"measures": ["net_sales_sek"], "order_by": {"field": "1; DROP TABLE dim_store"}},
    {"measures": ["net_sales_sek"], "having": {"field": "units", "op": ">", "value": 1}},
    {"measures": ["net_sales_sek"], "dimensions": ["region"],
     "having": {"field": "region", "op": ">", "value": 1}},
    {"measures": ["net_sales_sek"], "having": {"field": "net_sales_sek", "op": "OR 1=1",
                                               "value": 1}},
    {"measures": ["net_sales_sek"], "having": {"field": "net_sales_sek", "op": ">",
                                               "value": "1 OR 1=1"}},
    {"measures": ["net_sales_sek"], "dimensions": ["region"],
     "top_n_per": {"dimension": "product", "n": 3}},
    {"measures": ["net_sales_sek"], "dimensions": ["region"],
     "top_n_per": {"dimension": "region", "n": 0}},
    {"measures": ["avg_price_sek"], "dimensions": ["channel"], "percent_of_total": True},
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
    window = (date(2026, 4, 1), date(2026, 6, 30))  # 91 days
    assert shift_range(window, "previous_period") == (date(2025, 12, 31), date(2026, 3, 31))




def test_compare_emits_delta_columns_and_a_full_outer_join():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    keys = [c["key"] for c in compiled.columns]
    assert keys == ["product", "net_sales_sek", "net_sales_sek_compare",
                    "net_sales_sek_delta", "net_sales_sek_delta_pct"]
    # Both deltas: absolute is what "biggest mover" means on a readable axis, percent is
    # what it means about the product.
    assert "(c.net_sales_sek - pv.net_sales_sek) AS net_sales_sek_delta" in compiled.sql
    assert "FULL OUTER JOIN" in compiled.sql
    assert compiled.compare_range == (date(2024, 7, 1), date(2025, 6, 30))


def test_compare_over_a_date_dimension_joins_on_position_not_on_value():
    """The regression behind "visa månadsförsäljning jämfört med i fjol". cur.month lives in
    2025-07..2026-06 and prev.month in 2024-07..2025-06, so joining on the value matched zero
    rows: 24 rows instead of 12, every delta NULL."""
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
    assert keys == ["month", "month_compare", "net_sales_sek", "net_sales_sek_compare",
                    "net_sales_sek_delta", "net_sales_sek_delta_pct"]
    # The comparison series has to be labellable with the period it came from.
    assert "pv.month AS month_compare" in compiled.sql


def test_the_internal_ordinal_never_reaches_the_caller():
    """__ord is a join mechanism."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert not any(c["key"].endswith("__ord") for c in compiled.columns)


def test_compare_mixing_a_date_and_a_plain_dimension():
    """Position for the date, value for the product - and DENSE_RANK rather than ROW_NUMBER so the
    repeated month keeps one shared position across products."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["month", "product"],
        "compare_to": "same_period_last_year",
        "time_range": "last_12_months",
    })
    assert "c.month__ord = pv.month__ord" in compiled.sql
    assert "c.product = pv.product" in compiled.sql
    assert "COALESCE(c.product, pv.product) AS product" in compiled.sql
    # Plain equality, and this assertion is the reason.
    assert "IS NOT DISTINCT FROM" not in compiled.sql


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


def test_columns_carry_the_configured_currency_and_a_label():
    """The unit is the deployment's currency, not a literal - the same warehouse pointed at
    another market must not hand back columns labelled in a currency it does not hold."""
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["region"]})
    by_key = {c["key"]: c for c in compiled.columns}
    assert by_key["net_sales_sek"]["unit"] == settings.app_currency
    assert by_key["net_sales_sek"]["label"] == "Nettoförsäljning"
    # Generic on purpose: "Län" is a Swedish administrative unit, and the same column
    # holds states, prefectures or provinces elsewhere.
    assert by_key["region"]["label"] == "Region"




def test_order_by_a_derived_compare_column():
    """"Vilka produkter tappar mest mot förra året?" - the biggest decliner is usually a mid-sized
    product, so sorting by the current value never surfaces it."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "compare_to": "same_period_last_year",
        "order_by": {"field": "net_sales_sek_delta_pct", "dir": "asc"},
        "limit": 10,
    })
    assert "ORDER BY net_sales_sek_delta_pct ASC" in compiled.sql


def test_order_by_measure_and_dimension_still_work():
    """The old spelling is what api/routes/dashboard.py sends; `field` is additive."""
    assert "ORDER BY units DESC" in compile_ok({
        "measures": ["units"], "dimensions": ["product"],
        "order_by": {"measure": "units"}}).sql
    assert "ORDER BY region ASC" in compile_ok({
        "measures": ["units"], "dimensions": ["region"],
        "order_by": {"dimension": "region", "dir": "asc"}}).sql


def test_percent_of_total_is_computed_in_sql():
    """"Hur stor andel av försäljningen är online?" - two golden cases used to depend on the model
    dividing, which the system prompt forbids."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["channel"],
        "percent_of_total": True,
    })
    assert "SUM(net_sales_sek) OVER ()" in compiled.sql
    assert [c["key"] for c in compiled.columns][-1] == "net_sales_sek_pct_of_total"
    assert compiled.columns[-1]["unit"] == "%"


def test_percent_of_total_avoids_integer_division():
    """SUM(qty) is a bigint; 100 * bigint / bigint truncates every share to a whole percent, and a
    share that reads 12 when it is 12.4 is simply wrong."""
    compiled = compile_ok({
        "measures": ["units"], "dimensions": ["channel"], "percent_of_total": True})
    assert "100.0 * units" in compiled.sql


def test_percent_of_total_refuses_non_additive_measures():
    """Shares of an average price add to 100 % and mean nothing."""
    with pytest.raises(SpecError, match="summerbart"):
        compile_query({"measures": ["discount_rate"], "dimensions": ["channel"],
                       "percent_of_total": True}, COVERAGE)


def test_percent_of_total_skips_the_ratio_measures_it_cannot_share():
    compiled = compile_ok({
        "measures": ["net_sales_sek", "avg_price_sek"],
        "dimensions": ["channel"],
        "percent_of_total": True,
    })
    keys = [c["key"] for c in compiled.columns]
    assert "net_sales_sek_pct_of_total" in keys
    assert "avg_price_sek_pct_of_total" not in keys


def test_partitioned_top_n_ranks_within_the_partition():
    """"Topplista per län" - a flat GROUP BY with a global LIMIT returns ten Stockholm rows and no
    per-county list at all."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["region", "product"],
        "top_n_per": {"dimension": "region", "n": 3},
    })
    assert ("ROW_NUMBER() OVER (PARTITION BY region ORDER BY net_sales_sek DESC"
            in compiled.sql)
    assert "WHERE __rank <=" in compiled.sql
    # Grouped by county, best first inside each - any other order is unreadable.
    assert "ORDER BY region ASC NULLS LAST, net_sales_sek DESC" in compiled.sql


def test_the_rank_column_never_reaches_the_caller():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["region", "product"],
        "top_n_per": {"dimension": "region", "n": 3},
    })
    assert not any(c["key"] == "__rank" for c in compiled.columns)
    # The outer projection is explicit precisely so __rank stops at the wrapper.
    assert compiled.sql.rindex("__rank") < compiled.sql.index("LIMIT")
    assert "SELECT *" not in compiled.sql.split(") w")[-1]


def test_top_n_per_takes_its_ranking_from_order_by():
    compiled = compile_ok({
        "measures": ["net_sales_sek", "units"],
        "dimensions": ["region", "product"],
        "order_by": {"measure": "units", "dir": "desc"},
        "top_n_per": {"dimension": "region", "n": 2},
    })
    assert "PARTITION BY region ORDER BY units DESC" in compiled.sql


def test_having_filters_on_the_aggregate_not_the_row():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "having": {"field": "net_sales_sek", "op": ">=", "value": 100_000},
    })
    assert "WHERE net_sales_sek::numeric >=" in compiled.sql
    assert "100000" not in compiled.sql  # the threshold is a bound parameter
    assert Decimal("100000") in compiled.params


def test_having_can_target_a_derived_compare_column():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "compare_to": "same_period_last_year",
        "having": {"field": "net_sales_sek_delta_pct", "op": "<", "value": -10},
    })
    assert "WHERE net_sales_sek_delta_pct::numeric <" in compiled.sql


def test_having_runs_before_the_share_denominator():
    """WHERE is evaluated before window functions in the same SELECT, so the percentages are of the
    rows the caller asked to keep - not of a set they filtered away."""
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "percent_of_total": True,
        "having": {"field": "net_sales_sek", "op": ">", "value": 0},
    })
    assert compiled.sql.index("SUM(net_sales_sek) OVER ()") < compiled.sql.index(
        "WHERE net_sales_sek::numeric >")


def test_the_post_aggregate_stage_is_absent_when_nothing_asks_for_it():
    """No wrapper, no window, no behaviour change for every query written before it."""
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["product"]})
    assert "OVER (" not in compiled.sql
    assert "__rank" not in compiled.sql


def test_all_four_post_aggregate_features_compose():
    compiled = compile_ok({
        "measures": ["net_sales_sek"],
        "dimensions": ["region", "product"],
        "compare_to": "same_period_last_year",
        "percent_of_total": True,
        "having": {"field": "net_sales_sek", "op": ">", "value": 1000},
        "order_by": {"measure": "net_sales_sek"},
        "top_n_per": {"dimension": "region", "n": 3},
        "limit": 50,
    })
    sql = compiled.sql
    assert "FULL OUTER JOIN" in sql
    assert "SUM(net_sales_sek) OVER ()" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY region" in sql
    assert "__rank <=" in sql
    assert sql.rstrip().endswith("LIMIT 50")




def test_calendar_dimensions_fold_the_window_instead_of_cutting_it():
    """"Vilken månad säljer bäst?" groups every July together, unlike `month`."""
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": ["month_of_year"]})
    assert compiled.source == ROLLUP
    assert "EXTRACT(MONTH FROM s.date)" in compiled.sql
    assert "GROUP BY EXTRACT(MONTH FROM s.date)::int" in compiled.sql


def test_weekday_is_monday_first():
    """ISODOW, not dim_date.weekday: the column is 0-based and deriving it from the date keeps one
    definition across both sources."""
    compiled = compile_ok({"measures": ["units"], "dimensions": ["weekday"]})
    assert "EXTRACT(ISODOW FROM s.date)" in compiled.sql


@pytest.mark.parametrize("key, fragment", [
    ("is_holiday", "d.is_holiday"),
    ("campaign_id", "d.campaign_id"),
])
def test_dim_date_only_calendar_dimensions_force_the_fact_table(key, fragment):
    compiled = compile_ok({"measures": ["net_sales_sek"], "dimensions": [key]})
    assert compiled.source == FACT
    assert fragment in compiled.sql
    assert "JOIN dim_date d" in compiled.sql


def test_campaign_days_can_be_compared_with_ordinary_days():
    """The generator discounts ~22.5 % on campaign days against ~8 % otherwise, so this is the
    question the dimension exists for."""
    compiled = compile_ok({
        "measures": ["discount_rate", "net_sales_sek"],
        "dimensions": ["campaign_id"],
        "time_range": "last_12_months",
    })
    assert "GROUP BY d.campaign_id" in compiled.sql


def test_joins_are_emitted_in_dependency_order():
    compiled = compile_ok({"measures": ["units"], "dimensions": ["category", "brand"]})
    sql = compiled.sql
    assert sql.index("dim_product") < sql.index("dim_brand")
    assert sql.index("sub.category_id = p.category_id") < sql.index("top.category_id")
