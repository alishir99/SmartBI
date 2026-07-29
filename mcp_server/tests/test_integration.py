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
