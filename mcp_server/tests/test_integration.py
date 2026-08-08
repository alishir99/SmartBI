"""Integration tests - the assertions that need a real, seeded Postgres."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import asyncpg
import pytest

from mcp_server import db
from mcp_server.tenant import TenantContext
from mcp_server.tools.market_share import query_market_share
from mcp_server.tools.sales import query_sales

pytestmark = pytest.mark.integration

GROUND_TRUTH = Path(__file__).resolve().parents[2] / "data" / "generated" / "ground_truth.json"

# Rounding differences between the generator's float accumulation and Postgres' numeric
# arithmetic are expected; a discrepancy that matters is orders of magnitude larger.
TOLERANCE_SEK = 1.0


_MAX_SUPPLIER_ID = 32  # how far to probe for seeded suppliers


def _reachable() -> bool:
    """A one-second socket probe, so a clean clone skips promptly instead of waiting out a connect
    timeout once per test."""
    try:
        with socket.create_connection(
                (db.settings.postgres_host, db.settings.postgres_port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture
async def pool():
    """A pool against the configured DSN, or a skip if the database is not there."""
    if not _reachable():
        pytest.skip(f"ingen databas på {db.settings.postgres_host}:{db.settings.postgres_port}")
    try:
        await db.init_pool()
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"ingen databas på {db.settings.dsn.rsplit('@', 1)[-1]}: {exc}")
    try:
        yield db.pool()
    finally:
        await db.close_pool()


@pytest.fixture(scope="session")
def truth() -> dict:
    if not GROUND_TRUTH.exists():
        pytest.skip("data/generated/ground_truth.json saknas - kör scripts/generate_data.py")
    with open(GROUND_TRUTH, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
async def suppliers(pool) -> dict[str, int]:
    """Supplier name → id."""
    found: dict[str, int] = {}
    for supplier_id in range(1, _MAX_SUPPLIER_ID + 1):
        async with db.tenant_connection(supplier_id) as connection:
            rows = await connection.fetch("SELECT supplier_id, name FROM dim_supplier")
        if not rows:
            continue
        assert len(rows) == 1, f"supplier {supplier_id} såg {len(rows)} leverantörer"
        assert rows[0]["supplier_id"] == supplier_id
        found[rows[0]["name"]] = supplier_id
    if not found:
        pytest.skip("databasen är tom - kör scripts/seed.py")
    return found


def tenant(supplier_id: int) -> TenantContext:
    return TenantContext(supplier_id=supplier_id)


def total(payload: dict, key: str = "net_sales_sek") -> float:
    return sum(float(row[key]) for row in payload["rows"])



async def test_net_sales_matches_ground_truth_for_every_supplier(pool, truth, suppliers):
    """Four transformations from the generator to the tool, and no krona lost on the way."""
    for name, expected in truth["per_supplier"].items():
        supplier_id = suppliers.get(name)
        assert supplier_id is not None, f"{name} saknas i dim_supplier"

        payload = await query_sales(tenant(supplier_id), {
            "measures": ["net_sales_sek", "units"],
            "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]},
        })

        assert abs(total(payload) - expected["net_sales_sek"]) < TOLERANCE_SEK, name
        assert total(payload, "units") == expected["units"], name


async def test_the_monthly_breakdown_matches_ground_truth(pool, truth, suppliers):
    """The rollup is grouped, not just summed - a grain bug shows up here, not in the total."""
    name = truth["demo_supplier"]
    expected = truth["per_supplier"][name]["net_sales_by_month"]

    payload = await query_sales(tenant(suppliers[name]), {
        "measures": ["net_sales_sek"],
        "dimensions": ["month"],
        "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]},
    })

    actual = {str(row["month"])[:7]: float(row["net_sales_sek"]) for row in payload["rows"]}
    assert len(actual) == len(expected)
    for month, value in expected.items():
        assert abs(actual[month[:7]] - float(value)) < TOLERANCE_SEK, month



async def test_two_suppliers_never_see_the_same_rows(pool, truth, suppliers):
    """The scope is a transaction setting, not a WHERE clause the caller could omit."""
    names = list(truth["per_supplier"])[:2]
    spec = {"measures": ["net_sales_sek"], "dimensions": ["product"],
            "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]}}

    first, second = [await query_sales(tenant(suppliers[name]), spec) for name in names]

    products = [{row["product"] for row in payload["rows"]} for payload in (first, second)]
    assert products[0] and products[1]
    assert not (products[0] & products[1]), "en produkt syntes för två leverantörer"


async def test_a_region_filter_cannot_reach_past_the_tenant(pool, truth, suppliers):
    """A filter narrows a scope; it can never widen one."""
    name = truth["demo_supplier"]
    window = {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]}

    scoped = await query_sales(tenant(suppliers[name]), {
        "measures": ["net_sales_sek"], "time_range": window,
        "filters": {"region": ["Stockholms län"]}})
    everything = await query_sales(tenant(suppliers[name]), {
        "measures": ["net_sales_sek"], "time_range": window})

    assert 0 < total(scoped) < total(everything)


async def test_an_unscoped_connection_sees_nothing(pool):
    """Forgetting to scope must fail closed. RLS makes the fact table empty, not readable."""
    async with pool.acquire() as connection:
        async with connection.transaction():
            count = await connection.fetchval("SELECT COUNT(*) FROM fact_sales_line")
    assert count == 0



async def test_market_share_never_exceeds_one_hundred_percent(pool, truth, suppliers):
    """D1's live regression: the numerator and the denominator must cover the same months."""
    for name in truth["per_supplier"]:
        payload = await query_market_share(tenant(suppliers[name]), {
            "time_range": {"relative": "last_7_days"}})

        for row in payload["rows"]:
            if row.get("suppressed"):
                continue
            assert 0 <= row["share_pct"] <= 100, f"{name} / {row['subcategory']}"

        meta_range = payload["meta"]["time_range"]
        assert meta_range["from"].endswith("-01"), "fönstret ska börja på en månadsgräns"


async def test_a_thin_slice_is_suppressed_rather_than_answered(pool, truth, suppliers):
    """k-anonymity is enforced against the real distribution, not a fixture."""
    thresholds = truth.get("k_anonymity") or {}
    payload = await query_market_share(tenant(suppliers[truth["demo_supplier"]]), {
        "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]}})

    for row in payload["rows"]:
        if row.get("suppressed"):
            # A suppressed row carries no figure that arithmetic could turn back into one.
            assert "share_pct" not in row and "category_net_sek" not in row
            assert row.get("reason")
        else:
            assert row["n_brands"] >= thresholds.get("min_brands", 5)



# Absolute floor, not relative: these are sums over hundreds of thousands of NUMERIC(12,2)
# rows aggregated in a different order, so the last öre can differ.
RECONCILE_TOLERANCE_SEK = 1.0


@pytest.fixture
async def owner():
    """A connection as the *owner* role, which the rest of this module deliberately never uses."""
    if not _reachable():
        pytest.skip(f"ingen databas på {db.settings.postgres_host}:{db.settings.postgres_port}")
    dsn = (f"postgresql://{os.getenv('POSTGRES_USER', 'solvigo')}:"
           f"{os.getenv('POSTGRES_PASSWORD', 'solvigo')}"
           f"@{db.settings.postgres_host}:{db.settings.postgres_port}/"
           f"{os.getenv('POSTGRES_DB', 'solvigo')}")
    try:
        connection = await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"ingen ägaranslutning: {exc}")
    try:
        yield connection
    finally:
        await connection.close()

_ROLLUP_KEYS = [
    ("supplier_id", "f.supplier_id"),
    ("date", "d.date"),
    ("region", "st.region"),
    ("channel", "st.channel"),
    ("product_id", "f.product_id"),
]


async def test_the_rollup_reproduces_the_fact_table_at_every_grain(owner):
    """Nothing anywhere asserted that `mv_sales_daily` agrees with `fact_sales_line`. That is the
    load-bearing gap under the project's central product claim."""
    for rollup_key, fact_key in _ROLLUP_KEYS:
            rows = await owner.fetch(f"""
                WITH rollup AS (
                    SELECT {rollup_key} AS k, SUM(net_sales_sek) AS net, SUM(qty) AS qty
                    FROM mv_sales_daily GROUP BY 1
                ), fact AS (
                    SELECT {fact_key} AS k,
                           SUM(f.net_amount_sek) AS net, SUM(f.quantity) AS qty
                    FROM fact_sales_line f
                    JOIN dim_date  d  ON d.date_id  = f.date_id
                    JOIN dim_store st ON st.store_id = f.store_id
                    GROUP BY 1
                )
                SELECT COALESCE(rollup.k::text, fact.k::text) AS k,
                       COALESCE(rollup.net, 0) AS rollup_net,
                       COALESCE(fact.net, 0)   AS fact_net,
                       COALESCE(rollup.qty, 0) AS rollup_qty,
                       COALESCE(fact.qty, 0)   AS fact_qty
                FROM rollup FULL OUTER JOIN fact USING (k)
                WHERE rollup.k IS NULL
                   OR fact.k IS NULL
                   OR ABS(COALESCE(rollup.net, 0) - COALESCE(fact.net, 0)) > $1
                   OR COALESCE(rollup.qty, 0) <> COALESCE(fact.qty, 0)
                ORDER BY 1 LIMIT 5
            """, RECONCILE_TOLERANCE_SEK)

            detail = "; ".join(
                f"{row['k']}: rollup {row['rollup_net']}/{row['rollup_qty']} "
                f"vs fact {row['fact_net']}/{row['fact_qty']}" for row in rows)
            assert not rows, (
                f"mv_sales_daily disagrees with fact_sales_line grouped by {rollup_key} - "
                f"the rollup is stale or half-refreshed (REFRESH MATERIALIZED VIEW). {detail}")


async def test_the_category_rollup_reproduces_the_fact_table(owner):
    """`mv_category_daily` is the privacy boundary rather than a convenience: `query_market_share`
    may read nothing else."""
    rows = await owner.fetch("""
        WITH rollup AS (
            SELECT category_id AS k, SUM(total_net_sek) AS net, SUM(total_qty) AS qty
            FROM mv_category_daily GROUP BY 1
        ), fact AS (
            SELECT p.category_id AS k,
                   SUM(f.net_amount_sek) AS net, SUM(f.quantity) AS qty
            FROM fact_sales_line f
            JOIN dim_product p ON p.product_id = f.product_id
            GROUP BY 1
        )
        SELECT COALESCE(rollup.k, fact.k) AS k,
               rollup.net AS rollup_net, fact.net AS fact_net
        FROM rollup FULL OUTER JOIN fact USING (k)
        WHERE rollup.k IS NULL OR fact.k IS NULL
           OR ABS(rollup.net - fact.net) > $1
           OR rollup.qty <> fact.qty
        ORDER BY 1 LIMIT 5
    """, RECONCILE_TOLERANCE_SEK)

    detail = "; ".join(f"category {row['k']}: rollup {row['rollup_net']} "
                       f"vs fact {row['fact_net']}" for row in rows)
    assert not rows, f"mv_category_daily disagrees with fact_sales_line. {detail}"


async def test_the_brand_rollup_agrees_with_its_own_rows(owner):
    """`mv_brand_monthly` computes category_net_sek, share_pct, rank and n_brands in window
    functions at refresh time."""
    rows = await owner.fetch("""
        SELECT month, category_id, region,
               MAX(category_net_sek) AS carried,
               SUM(net_sales_sek)    AS summed,
               MAX(n_brands)         AS carried_brands,
               COUNT(*)              AS actual_brands
        FROM mv_brand_monthly
        GROUP BY month, category_id, region
        HAVING ABS(MAX(category_net_sek) - SUM(net_sales_sek)) > $1
            OR MAX(n_brands) <> COUNT(*)
        ORDER BY 1, 2, 3 LIMIT 5
    """, RECONCILE_TOLERANCE_SEK)

    detail = "; ".join(f"{row['month']}/{row['category_id']}/{row['region']}: "
                       f"total {row['carried']} vs {row['summed']}, "
                       f"brands {row['carried_brands']} vs {row['actual_brands']}"
                       for row in rows)
    assert not rows, ("mv_brand_monthly's carried category total or peer count disagrees "
                      f"with its own rows. {detail}")


async def test_the_two_sources_answer_the_same_question_identically(
        monkeypatch, pool, truth, suppliers):
    """The "chat and the dashboard cannot disagree" claim, tested where it could break."""
    from mcp_server.semantic import compiler

    spec = {
        "measures": ["net_sales_sek", "units", "gross_sales_sek", "discount_sek"],
        "dimensions": ["month", "region"],
        "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]},
        # Deliberately left at DEFAULT_LIMIT, which this spec exceeds: 24 months x 22
        # regions is 528 groups against a limit of 500.
    }

    answers = {}
    for forced in ("rollup", "fact"):
        monkeypatch.setattr(compiler, "choose_source",
                            lambda *_args, _forced=forced, **_kw: _forced)
        payload = await query_sales(tenant(suppliers[truth["demo_supplier"]]), dict(spec))
        answers[forced] = {(str(row["month"]), row["region"]): row
                           for row in payload["rows"]}

    rollup, fact = answers["rollup"], answers["fact"]
    assert rollup, "the fixture produced no rows, so this test proved nothing"
    assert set(rollup) == set(fact), (
        "the rollup and the fact table returned different groups: "
        f"only in rollup {sorted(set(rollup) - set(fact))[:3]}, "
        f"only in fact {sorted(set(fact) - set(rollup))[:3]}")
    assert list(rollup) == list(fact), (
        "the two sources returned the same groups in a different order - a LIMIT that bites "
        "would then cut a different slice from each, which is how prose and chart came to "
        "name different winners")

    for key, rollup_row in rollup.items():
        fact_row = fact[key]
        for measure in ("net_sales_sek", "gross_sales_sek", "discount_sek"):
            assert abs(float(rollup_row[measure]) - float(fact_row[measure])) < 1.0, (
                f"{measure} at {key}: rollup {rollup_row[measure]} "
                f"vs fact {fact_row[measure]}")
        assert int(rollup_row["units"]) == int(fact_row["units"]), key



async def test_compare_over_a_non_date_dimension_executes(pool, truth, suppliers):
    """The gap that let a broken feature stay green for a whole remediation pass."""
    payload = await query_sales(tenant(suppliers[truth["demo_supplier"]]), {
        "measures": ["net_sales_sek"],
        "dimensions": ["product"],
        "time_range": {"relative": "last_12_months"},
        "compare_to": "same_period_last_year",
        "order_by": {"measure": "net_sales_sek_delta_pct", "dir": "asc"},
        "limit": 5,
    })

    assert payload["rows"], "no rows came back at all"
    # Sorting on the derived column is the point: the biggest decliner is typically
    # mid-sized, so sorting by current value never surfaces it.
    deltas = [row["net_sales_sek_delta_pct"] for row in payload["rows"]
              if row.get("net_sales_sek_delta_pct") is not None]
    assert deltas, "every delta came back NULL - the comparison join matched nothing"
    assert deltas == sorted(deltas), "ascending sort on the derived column did not hold"


async def test_the_post_aggregate_stage_executes(pool, truth, suppliers):
    """percent_of_total, HAVING and partitioned top-N against the real planner."""
    scope = tenant(suppliers[truth["demo_supplier"]])
    window = {"relative": "last_12_months"}

    share = await query_sales(scope, {
        "measures": ["net_sales_sek"], "dimensions": ["channel"],
        "time_range": window, "percent_of_total": True})
    percentages = [row["net_sales_sek_pct_of_total"] for row in share["rows"]]
    assert percentages, "percent_of_total produced no column"
    # This measure exists because the model was being asked to divide, which the prompt forbids.
    assert abs(sum(percentages) - 100.0) < 0.5, percentages

    filtered = await query_sales(scope, {
        "measures": ["net_sales_sek"], "dimensions": ["product"], "time_range": window,
        "having": {"measure": "net_sales_sek", "op": ">", "value": 1_000_000}})
    assert filtered["rows"]
    assert all(row["net_sales_sek"] > 1_000_000 for row in filtered["rows"])

    per_region = await query_sales(scope, {
        "measures": ["net_sales_sek"], "dimensions": ["region", "product"],
        "time_range": window, "top_n_per": {"dimension": "region", "n": 2}})
    counts: dict[str, int] = {}
    for row in per_region["rows"]:
        counts[row["region"]] = counts.get(row["region"], 0) + 1
    assert counts, "partitioned top-N produced no rows"
    assert max(counts.values()) <= 2, counts
    # More than one region surviving is the actual complaint: a flat GROUP BY with a
    # global LIMIT once returned ten Stockholm rows and nothing else.
    assert len(counts) > 1, "only one region came back - the partition did not apply"


async def test_the_calendar_dimensions_reach_real_columns(pool, truth, suppliers):
    """`dim_date` already carried all four; they were simply never exposed."""
    scope = tenant(suppliers[truth["demo_supplier"]])
    window = {"relative": "last_12_months"}

    for dimension, expected_rows in (("month_of_year", 12), ("weekday", 7)):
        payload = await query_sales(scope, {
            "measures": ["net_sales_sek"], "dimensions": [dimension],
            "time_range": window})
        assert len(payload["rows"]) == expected_rows, (
            f"{dimension} returned {len(payload['rows'])} groups, expected {expected_rows}")

    holidays = await query_sales(scope, {
        "measures": ["net_sales_sek"], "dimensions": ["is_holiday"], "time_range": window})
    assert {str(row["is_holiday"]) for row in holidays["rows"]} == {"Vardag", "Röd dag"}

    # campaign_id is only worth exposing because the generator bug that discounted every
    # line is fixed: campaign days now discount far harder than ordinary ones.
    campaigns = await query_sales(scope, {
        "measures": ["discount_rate"], "dimensions": ["campaign_id"],
        "time_range": window})
    rates = {row["campaign_id"]: float(row["discount_rate"]) for row in campaigns["rows"]}
    assert len(rates) > 1, "no campaign breakdown came back"
    on_campaign = [rate for key, rate in rates.items() if key is not None]
    off_campaign = [rate for key, rate in rates.items() if key is None]
    if on_campaign and off_campaign:
        assert min(on_campaign) > max(off_campaign), (
            f"campaign days ({on_campaign}) do not discount harder than ordinary days "
            f"({off_campaign}) - the generator's campaign branch may have re-broken")
