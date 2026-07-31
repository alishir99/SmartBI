"""Integration tests — the assertions that need a real, seeded Postgres.

Everything else in this suite runs on a laptop with no database: the compiler is tested by
parsing the SQL it emits, the validator by feeding it rows. That leaves two claims the whole
design rests on untested, because neither is provable without the server actually running them:

1. **RLS stops a cross-tenant read.** `db/sql/tests/isolation.sql` proves it at the SQL level.
   These tests prove it one layer up, through the tools the model actually calls — which is
   where a leak would have to happen, and where a barrier view that compiles but does not
   filter would still look fine.
2. **The tools reproduce `ground_truth.json`.** The generator writes the totals it intended;
   the star schema, the materialised rollups and the semantic layer are four transformations
   away from it. Agreement between the two ends is what says none of them lost a krona.

They skip themselves when nothing answers on the configured DSN, so `pytest -q` stays a
clean-clone command. CI runs them explicitly against its Postgres service with `-m integration`.
"""

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


# How far to probe for seeded suppliers. Comfortably above the eight the generator writes.
_MAX_SUPPLIER_ID = 32


def _reachable() -> bool:
    """A one-second socket probe, so a clean clone skips promptly instead of waiting out a
    connect timeout once per test."""
    try:
        with socket.create_connection(
                (db.settings.postgres_host, db.settings.postgres_port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture
async def pool():
    """A pool against the configured DSN, or a skip if the database is not there.

    Function-scoped on purpose: pytest-asyncio gives each test its own event loop, and an
    asyncpg pool cannot be shared across loops. Opening one per test costs milliseconds.
    """
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
        pytest.skip("data/generated/ground_truth.json saknas — kör scripts/generate_data.py")
    with open(GROUND_TRUTH, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
async def suppliers(pool) -> dict[str, int]:
    """Supplier name → id.

    Discovered by probing scoped connections rather than by reading `dim_supplier` in one
    query, because `dim_supplier` is itself RLS-protected: an unscoped SELECT returns zero
    rows. That constraint is the point — the map has to be built the way the application
    reads, and each probe doubles as an assertion that a scoped read returns exactly the
    caller's own row.
    """
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
        pytest.skip("databasen är tom — kör scripts/seed.py")
    return found


def tenant(supplier_id: int) -> TenantContext:
    return TenantContext(supplier_id=supplier_id)


def total(payload: dict, key: str = "net_sales_sek") -> float:
    return sum(float(row[key]) for row in payload["rows"])


# ------------------------------------------------------------------ the numbers reconcile

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
    """The rollup is grouped, not just summed — a grain bug shows up here, not in the total."""
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


# ------------------------------------------------------------------------ isolation holds

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


# ------------------------------------------------------------------- market share is sane

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


# ------------------------------------------------- the rollup and the fact table agree

# Compared with an absolute floor rather than a relative one: these are sums over hundreds of
# thousands of NUMERIC(12,2) rows aggregated in a different order, so the last öre can differ.
# A genuinely half-refreshed rollup is off by whole days, not by rounding.
RECONCILE_TOLERANCE_SEK = 1.0


@pytest.fixture
async def owner():
    """A connection as the *owner* role, which the rest of this module deliberately never uses.

    Reconciliation is an operator concern, not an application one, and the first attempt at
    these tests proved it by failing with `permission denied for materialized view
    mv_category_daily`. That error is the design working: `app_readonly` may reach the category
    rollup only through a barrier view, and `fact_sales_line` only under an RLS predicate. So
    the application role structurally *cannot* compare the two objects — it can never see both
    sides of the comparison at once, which is exactly the property the privacy model is built
    on and exactly why this check needs a different connection.
    """
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

# The rollup's grouping keys. Checked one at a time rather than as one grand total, because a
# grand total that matches can still hide two errors that cancel — and the fact-table side has
# to re-join dim_date and dim_store to reach these keys, which is precisely the work the
# rollup exists to avoid and precisely where it could have gone wrong.
_ROLLUP_KEYS = [
    ("supplier_id", "f.supplier_id"),
    ("date", "d.date"),
    ("region", "st.region"),
    ("channel", "st.channel"),
    ("product_id", "f.product_id"),
]


async def test_the_rollup_reproduces_the_fact_table_at_every_grain(owner):
    """Nothing anywhere asserted that `mv_sales_daily` agrees with `fact_sales_line`.

    That is the load-bearing gap under the project's central product claim. `choose_source` is
    free to answer the same question from either object — the rollup normally, the fact table
    when a dimension or measure is not available in it — so "chat and the dashboard cannot
    disagree" holds only if the two objects hold the same numbers. A half-refreshed
    materialised view breaks that silently: every query still succeeds, and the answers are
    merely wrong by however much the refresh missed.
    """
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
                f"mv_sales_daily disagrees with fact_sales_line grouped by {rollup_key} — "
                f"the rollup is stale or half-refreshed (REFRESH MATERIALIZED VIEW). {detail}")


async def test_the_category_rollup_reproduces_the_fact_table(owner):
    """`mv_category_daily` is the privacy boundary rather than a convenience:
    `query_market_share` may read nothing else. A drift here moves every share and every rank
    the product reports about a market the caller cannot otherwise see, and there is no second
    source to notice it."""
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
    functions at refresh time. Those are the only numbers in the schema that are *derived*
    rather than summed, and n_brands is what the k-anonymity threshold is tested against — so
    a wrong count is a wrong suppression decision, which is a privacy outcome rather than an
    accuracy one. The window has to still agree with the rows it was computed over."""
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
    """The "chat and the dashboard cannot disagree" claim, tested where it could break.

    The three tests above compare the *objects*. This one compares the *answers*, through the
    compiler, with every join, filter and GROUP BY the tool actually emits — which is the
    layer a divergence would have to cross to reach a user. Forcing the source is the only way
    to ask the question at all: `choose_source` is deterministic, so in normal operation one
    of these two paths is simply never exercised for a given spec.
    """
    from mcp_server.semantic import compiler

    spec = {
        "measures": ["net_sales_sek", "units", "gross_sales_sek", "discount_sek"],
        "dimensions": ["month", "region"],
        "time_range": {"from": truth["coverage"]["from"], "to": truth["coverage"]["to"]},
        # Explicit, and above the 528 groups this produces (24 months x 22 regions).
        # The first draft of this test left it at DEFAULT_LIMIT=500 and failed with the two
        # sources returning *different regions* for the last month — not a reconciliation
        # failure but finding B2 in the review: with `order_by` absent the compiler orders by
        # the leading date dimension alone, so a LIMIT that bites cuts an arbitrary slice of
        # the trailing group, and "arbitrary" differs between two physical sources. That is a
        # real defect and it belongs to the ordering fix, not here; this test asks whether the
        # two sources hold the same numbers, and it should not be able to fail for a second
        # reason.
        "limit": 5000,
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

    for key, rollup_row in rollup.items():
        fact_row = fact[key]
        for measure in ("net_sales_sek", "gross_sales_sek", "discount_sek"):
            assert abs(float(rollup_row[measure]) - float(fact_row[measure])) < 1.0, (
                f"{measure} at {key}: rollup {rollup_row[measure]} "
                f"vs fact {fact_row[measure]}")
        assert int(rollup_row["units"]) == int(fact_row["units"]), key
