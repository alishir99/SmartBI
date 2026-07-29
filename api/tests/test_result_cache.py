"""Tests for the result cache — the store the charts read from.

Two properties matter here. One is a security property: an entry is reachable only by the
tenant it was created for, so a guessed or leaked query_id cannot become a cross-tenant read.
The other is the grounding property: the preview handed to the model is bounded and says so.
"""

from __future__ import annotations

from api.result_cache import PREVIEW_ROWS, CachedResult, ResultCache, from_tool_result

PAYLOAD = {
    "query_id": "q_abc123",
    "columns": [{"key": "product", "type": "text", "label": "Produkt"},
                {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}],
    "rows": [{"product": f"Produkt {i}", "net_sales_sek": float(i)} for i in range(200)],
    "row_count": 200,
    "meta": {"tool": "query_sales", "source": "mv_sales_daily (rollup)"},
}


def cached(supplier_id: int = 1) -> CachedResult:
    return from_tool_result(supplier_id=supplier_id, tool="query_sales",
                           tool_args={"limit": 200}, payload=PAYLOAD)


# ------------------------------------------------------------------ tenant scoping

def test_an_entry_is_readable_by_its_own_tenant():
    cache = ResultCache()
    entry = cache.put(cached(supplier_id=1))
    assert cache.get(entry.query_id, 1) is not None


def test_another_tenant_cannot_read_the_same_query_id():
    """The route turns this None into a 404 — not a 403, which would confirm the id exists."""
    cache = ResultCache()
    entry = cache.put(cached(supplier_id=1))
    assert cache.get(entry.query_id, 2) is None


def test_an_unknown_query_id_is_a_miss():
    assert ResultCache().get("q_nonexistent", 1) is None


# ------------------------------------------------------------------------- eviction

def test_the_cache_is_size_capped():
    cache = ResultCache(max_entries=3)
    for i in range(10):
        payload = {**PAYLOAD, "query_id": f"q_{i}"}
        cache.put(from_tool_result(supplier_id=1, tool="query_sales",
                                   tool_args={}, payload=payload))
    assert len(cache) <= 3


def test_expired_entries_are_not_returned():
    cache = ResultCache(ttl_seconds=0)
    entry = cache.put(cached())
    assert cache.get(entry.query_id, 1) is None


# ---------------------------------------------------------------- preview discipline

def test_the_preview_is_bounded():
    entry = cached()
    preview = entry.preview()
    assert len(preview["rows"]) == PREVIEW_ROWS
    assert preview["row_count"] == 200


def test_the_preview_admits_it_is_a_sample():
    """If the model thinks it saw everything, it will happily total up a sample."""
    preview = cached().preview()
    assert preview["truncated_for_model"] is True
    assert "förhandsvisning" in preview["note"]


def test_the_full_rows_stay_on_the_server():
    """The chart is drawn from these, which is why the values never pass through the model."""
    entry = cached()
    assert len(entry.rows) == 200
    assert len(entry.preview()["rows"]) < len(entry.rows)


def test_a_small_result_is_not_marked_truncated():
    payload = {**PAYLOAD, "rows": PAYLOAD["rows"][:3], "row_count": 3}
    entry = from_tool_result(supplier_id=1, tool="query_sales", tool_args={}, payload=payload)
    assert entry.preview()["truncated_for_model"] is False


# ------------------------------------------------------------------------- adapting

def test_a_market_share_payload_without_columns_still_caches():
    """query_market_share returns no `columns` and no `query_id`; a KeyError here would turn a
    usable answer into a 500."""
    payload = {"rows": [{"subcategory": "Hörlurar", "share_pct": 18.3, "rank": 2}],
               "row_count": 1, "meta": {"tool": "query_market_share"}}
    entry = from_tool_result(supplier_id=1, tool="query_market_share",
                             tool_args={}, payload=payload)
    assert entry.query_id.startswith("q_")
    keys = {c["key"] for c in entry.columns}
    assert {"subcategory", "share_pct", "rank"} <= keys
    assert next(c for c in entry.columns if c["key"] == "share_pct")["type"] == "number"


def test_numeric_columns_are_identified():
    assert cached().numeric_columns() == ["net_sales_sek"]
