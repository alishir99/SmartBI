"""Tests for the oracle.

The oracle is the only reason the golden literals are evidence rather than assertion: it
re-aggregates the emitted CSVs without touching the API, the MCP server or the database.
That makes it load-bearing and therefore dangerous — a bug here would not fail loudly, it
would quietly become the "expected" answer and certify the system as correct against a
wrong number.

`reconcile()` is the defence, and `test_reconciles_against_ground_truth` is the test that
licences everything downstream. The rest of this module pins the design decisions that a
plausible refactor would erase without breaking anything visibly:

* relative windows anchor on the LAST DATE IN THE DATA, not on today. Swap that for
  `date.today()` and every window silently empties as the fixture ages;
* `slice()` defaults to the demo tenant, so an expectation written without a scope is
  tenant-scoped rather than accidentally global;
* `market_share()` reports `n_brands` and suppresses nothing — the k-anonymity policy
  lives in the caller, and an oracle that applied it could not be used to test the guard;
* `Vintersport` really is below the k-threshold, which is the entire premise of the
  thin-slice cases in adversarial.yaml.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eval.oracle import DEMO_SUPPLIER, MEASURES, Oracle

pytestmark = pytest.mark.skipif(
    not (Oracle().data_dir / "fact_sales_line.csv").exists(),
    reason=("data/generated is missing — regenerate with: "
            "python scripts/generate_data.py --seed 42"),
)

# Every window `relative_range` claims to resolve. Kept explicit rather than derived from
# the implementation so that dropping one is a test failure, not a silent narrowing.
WINDOWS = (
    "last_30_days", "last_90_days", "last_6_months", "last_12_months",
    "last_month", "this_month", "this_year", "ytd", "all_time",
)


@pytest.fixture(scope="module")
def oracle() -> Oracle:
    # Module-scoped: `lines` is a cached_property over seven CSVs, and rebuilding it per
    # test would dominate the runtime of the whole suite.
    return Oracle()


# ---------------------------------------------------------------- the licence


def test_reconciles_against_ground_truth(oracle):
    problems = oracle.reconcile()
    assert problems == [], (
        f"the oracle disagrees with data/generated/ground_truth.json in "
        f"{len(problems)} place(s):\n  - " + "\n  - ".join(problems))


def test_data_files_are_present(oracle):
    for name in ("fact_sales_line.csv", "dim_date.csv", "dim_product.csv", "dim_brand.csv",
                 "dim_supplier.csv", "dim_category.csv", "dim_store.csv",
                 "ground_truth.json"):
        assert (oracle.data_dir / name).exists(), f"{name} missing from {oracle.data_dir}"


# ---------------------------------------------------------------- measures


def test_measure_accepts_exactly_the_advertised_keys(oracle):
    df = oracle.slice()
    for key in MEASURES:
        value = oracle.measure(df, key)
        assert isinstance(value, (int, float)), f"{key} returned {value!r}"


def test_unknown_measure_raises(oracle):
    # The failure mode this forbids is a typo'd measure returning None and comparing
    # equal to nothing in particular.
    with pytest.raises(KeyError, match="unknown measure"):
        oracle.measure(oracle.slice(), "net_sales")


def test_measure_definitions_are_internally_consistent(oracle):
    df = oracle.slice()
    gross = oracle.measure(df, "gross_sales_sek")
    net = oracle.measure(df, "net_sales_sek")
    discount = oracle.measure(df, "discount_sek")
    assert gross - net == pytest.approx(discount, abs=1.0)
    assert oracle.measure(df, "discount_rate") == pytest.approx(100 * discount / gross, abs=0.01)
    assert oracle.measure(df, "avg_price_sek") == pytest.approx(
        net / oracle.measure(df, "units"), abs=0.01)


def test_empty_slice_does_not_divide_by_zero(oracle):
    empty = oracle.slice(brand="Ingen sådan")
    assert len(empty) == 0
    assert oracle.measure(empty, "avg_price_sek") == 0.0
    assert oracle.measure(empty, "discount_rate") == 0.0


# ---------------------------------------------------------------- windows


@pytest.mark.parametrize("name", WINDOWS)
def test_relative_range_stays_inside_coverage(name, oracle):
    start, end = oracle.relative_range(name)
    assert start <= end, f"{name} resolved to an inverted range"
    assert start >= oracle.coverage.start, f"{name} starts before the data does"
    assert end <= oracle.coverage.end, f"{name} ends after the data does"


@pytest.mark.parametrize("name", [w for w in WINDOWS if w != "last_month"])
def test_windows_anchor_on_the_last_date_in_the_data(name, oracle):
    """Not on today. compiler.py resolves relative ranges against the data's coverage so
    the demo keeps working as the fixture ages; an oracle anchored on `date.today()` would
    agree with it only for as long as the two happened to coincide."""
    _, end = oracle.relative_range(name)
    assert end == oracle.coverage.end, f"{name} ended at {end}, not {oracle.coverage.end}"


def test_windows_are_not_anchored_on_today(oracle):
    today = date.today()
    if oracle.coverage.end == today:
        pytest.skip("coverage happens to end today, so the two anchors are indistinguishable")
    assert oracle.relative_range("last_30_days") == (
        oracle.coverage.end - timedelta(days=29), oracle.coverage.end)
    assert oracle.relative_range("this_month")[0] == oracle.coverage.end.replace(day=1)


def test_last_month_is_the_month_before_the_last_data_month(oracle):
    start, end = oracle.relative_range("last_month")
    first_of_last_data_month = oracle.coverage.end.replace(day=1)
    assert end == first_of_last_data_month - timedelta(days=1)
    assert start == end.replace(day=1)


def test_last_12_months_is_a_full_year_ending_at_coverage(oracle):
    start, end = oracle.relative_range("last_12_months")
    assert end == oracle.coverage.end
    assert start == date(end.year - 1, end.month, end.day) + timedelta(days=1)


def test_ytd_and_this_year_are_the_same_window(oracle):
    assert oracle.relative_range("ytd") == oracle.relative_range("this_year")
    assert oracle.relative_range("this_year")[0].month == 1


def test_all_time_is_the_whole_coverage(oracle):
    assert oracle.relative_range("all_time") == (oracle.coverage.start, oracle.coverage.end)


def test_unknown_window_raises(oracle):
    with pytest.raises(KeyError, match="unknown relative range"):
        oracle.relative_range("last_fortnight")


# ---------------------------------------------------------------- tenant scoping


def test_slice_defaults_to_the_demo_tenant(oracle):
    scoped = oracle.slice()
    assert set(scoped["supplier"].unique()) == {DEMO_SUPPLIER}


def test_slice_can_be_widened_only_explicitly(oracle):
    everyone = oracle.slice(supplier=None)
    assert len(everyone) > len(oracle.slice())
    assert len(set(everyone["supplier"].unique())) > 1


def test_unknown_filter_key_in_a_derivation_raises(oracle):
    with pytest.raises(KeyError, match="unknown filter key"):
        oracle.derive({"measure": "net_sales_sek", "where": {"customer_segment": "premium"}})


# ---------------------------------------------------------------- market share


def test_market_share_reports_peer_count_without_suppressing(oracle):
    """The oracle mirrors the *policy*, not the SQL. If it applied the k-anonymity guard
    itself it could not be used to check that the guard fired for the right reason."""
    window = oracle.window("last_12_months")
    result = oracle.market_share("TV", brand="Nordström", **window)
    assert result["n_brands"] >= 1
    assert "suppressed" not in result
    assert result["category_net_sek"] > 0
    assert 0 <= result["share_pct"] <= 100
    assert result["rank"] >= 1


def test_market_share_is_scoped_to_the_whole_subcategory(oracle):
    """Own sales must be a strict part of the field, otherwise `share_pct` is meaningless.
    This is the one place the oracle looks past the tenant on purpose."""
    window = oracle.window("last_12_months")
    result = oracle.market_share("TV", brand="Nordström", **window)
    assert result["own_net_sek"] < result["category_net_sek"]


def test_market_share_without_a_brand_reports_the_field_only(oracle):
    result = oracle.market_share("TV", **oracle.window("all_time"))
    assert "share_pct" not in result
    assert result["n_brands"] >= 1


def test_vintersport_is_below_the_k_anonymity_threshold(oracle):
    """The thin-slice cases in adversarial.yaml assert that a real subcategory gets
    suppressed. That demo is only meaningful while this stays true of the data."""
    per_subcategory = oracle.brands_per_subcategory()
    assert "Vintersport" in per_subcategory, (
        f"Vintersport is gone from the data; adversarial.yaml's thin-slice cases now test "
        f"nothing. Subcategories present: {sorted(per_subcategory)}")
    assert per_subcategory["Vintersport"] < 5, (
        f"Vintersport now holds {per_subcategory['Vintersport']} brands, at or above the "
        f"k-threshold of 5 — the suppression demo no longer fires")
    assert per_subcategory["Vintersport"] == min(per_subcategory.values())


def test_the_tenant_sells_nothing_in_vintersport(oracle):
    # Two independent reasons the thin-slice question cannot yield a figure; this is the
    # second one, and it is the reason the case is in adversarial.yaml at all.
    assert len(oracle.slice(subcategory="Vintersport")) == 0


# ---------------------------------------------------------------- oddities


def test_the_discontinued_product_stops_before_coverage_ends(oracle):
    discontinued = oracle.discontinued_products()
    assert not discontinued.empty, "no discontinued product — the truncated-series case is dead"


def test_a_store_opened_inside_the_coverage_window(oracle):
    new_stores = oracle.stores_opened_within_coverage()
    assert not new_stores.empty, "no late-opening store — the partial-history case is dead"
