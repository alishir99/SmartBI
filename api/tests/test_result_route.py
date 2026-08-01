"""Where the chart actually reads its legend."""

from __future__ import annotations

import pytest

from api.result_cache import CachedResult, ResultCache
from api.routes import result as result_route


class FakeTenant:
    user_id = 7
    supplier_id = 1


def compared_result() -> CachedResult:
    return CachedResult(
        query_id="q_1", supplier_id=1, tool="query_sales", tool_args={},
        columns=[{"key": "month", "type": "date", "label": "Månad"},
                 {"key": "product_id", "type": "number", "label": "product_id"},
                 {"key": "net_sales_sek", "type": "number", "unit": "SEK",
                  "label": "Nettoförsäljning"},
                 {"key": "net_sales_sek_compare", "type": "number", "unit": "SEK",
                  "label": "Nettoförsäljning (jämförelse)"}],
        rows=[{"month": "2026-01-01", "product_id": 3, "net_sales_sek": 5.0,
               "net_sales_sek_compare": 4.0}],
        row_count=1, truncated=False,
        meta={"tool": "query_sales", "source": "mv_sales_daily", "scope": "supplier:abcd",
              "time_range": {"from": "2025-07-01", "to": "2026-06-30"},
              "compare_range": {"from": "2024-07-01", "to": "2025-06-30"},
              "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
              "executed_at": "2026-08-01T10:00:00Z"})


async def page():
    cache = ResultCache()
    cache.put(compared_result())
    return await result_route.get_result("q_1", offset=0, limit=1000,
                                         tenant=FakeTenant(), cache=cache)


@pytest.mark.asyncio
async def test_the_legend_names_the_comparison_period():
    """The chart's legend comes from here, not from the card   so a second copy of the label
    logic here is a legend that disagrees with the card's own table view."""
    labels = {c.key: c.label for c in (await page()).columns}

    assert labels["net_sales_sek_compare"] == "Nettoförsäljning (jul 2024–jun 2025)"


@pytest.mark.asyncio
async def test_identifier_columns_still_never_reach_the_reader():
    keys = [c.key for c in (await page()).columns]

    assert keys == ["month", "net_sales_sek", "net_sales_sek_compare"]


@pytest.mark.asyncio
async def test_an_unknown_query_id_is_a_404_not_a_403():
    """A 403 would confirm the id exists and belongs to someone else."""
    with pytest.raises(Exception) as raised:
        await result_route.get_result("q_nope", offset=0, limit=1000,
                                      tenant=FakeTenant(), cache=ResultCache())

    assert getattr(raised.value, "status_code", None) == 404
