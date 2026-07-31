"""Tests for the result cache — the store the charts read from."""

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


# ------------------------------------------------------- aggregates over the full result

# The B2 fixture, built to reproduce the defect rather than to be convenient: the largest value
# sits *outside* the 25 rows the model is shown, so any answer inferred from the sample names
# the wrong winner while quoting a number that really is in the result set — which is exactly
# why the validator used to accept it.
B2_ROWS = (
    [{"product": f"P{i}", "net_sales_sek": 8_507_984.0 - i} for i in range(PREVIEW_ROWS)]
    + [{"product": "P40", "net_sales_sek": 8_932_965.0}]
    + [{"product": f"Q{i}", "net_sales_sek": 1_000.0 + i} for i in range(50)]
)
B2_PAYLOAD = {
    "query_id": "q_b2",
    "columns": [{"key": "product", "type": "text", "label": "Produkt"},
                {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}],
    "rows": B2_ROWS,
    "row_count": len(B2_ROWS),
    "meta": {"tool": "query_sales"},
}


def b2_cached() -> CachedResult:
    return from_tool_result(supplier_id=1, tool="query_sales",
                            tool_args={}, payload=B2_PAYLOAD)


def test_the_real_maximum_is_outside_the_preview():
    """Guard on the fixture itself."""
    result = b2_cached()
    visible = result.preview()["rows"]
    assert len(visible) == PREVIEW_ROWS
    assert all(row["net_sales_sek"] < 8_932_965.0 for row in visible)


def test_the_model_is_told_the_argmax_it_cannot_see():
    """B2: the model saw 25 of 76 rows while propose_chart sorted all 76, so prose and chart could
    name different winners and both look verified."""
    aggregates = b2_cached().preview()["aggregates"]

    assert aggregates["net_sales_sek"]["max"]["value"] == 8_932_965.0
    # The identifying column comes with it — the point is to turn a number into an answer.
    assert aggregates["net_sales_sek"]["max"]["product"] == "P40"


def test_the_total_covers_every_row_not_the_sample():
    aggregates = b2_cached().preview()["aggregates"]
    assert aggregates["net_sales_sek"]["total"] == round(
        sum(row["net_sales_sek"] for row in B2_ROWS), 2)
    assert aggregates["net_sales_sek"]["counted_rows"] == len(B2_ROWS)


def test_the_minimum_carries_its_row_too():
    aggregates = b2_cached().preview()["aggregates"]
    assert aggregates["net_sales_sek"]["min"]["value"] == 1_000.0
    assert aggregates["net_sales_sek"]["min"]["product"] == "Q0"


def test_the_note_warns_that_the_biggest_row_is_probably_not_shown():
    """A sampled preview has to say so in the same breath as the aggregates, or the model has to
    work out which mode it is in."""
    note = b2_cached().preview()["note"]
    assert "aggregates" in note
    assert "stickprov" in note


def test_aggregates_are_present_even_when_nothing_was_truncated():
    small = from_tool_result(supplier_id=1, tool="query_sales", tool_args={}, payload={
        "query_id": "q_small",
        "columns": B2_PAYLOAD["columns"],
        "rows": [{"product": "A", "net_sales_sek": 10.0},
                 {"product": "B", "net_sales_sek": 30.0}],
        "row_count": 2, "meta": {}})
    preview = small.preview()

    assert preview["truncated_for_model"] is False
    assert preview["aggregates"]["net_sales_sek"]["max"]["product"] == "B"
    assert preview["aggregates"]["net_sales_sek"]["mean"] == 20.0


def test_a_suppressed_row_is_skipped_rather_than_counted_as_zero():
    """`query_market_share` genuinely omits `share_pct` on a suppressed row."""
    payload = {
        "rows": [
            {"subcategory": "Hörlurar", "share_pct": 30.0, "suppressed": False},
            {"subcategory": "Högtalare", "share_pct": 20.0, "suppressed": False},
            {"subcategory": "Vintersport", "suppressed": True,
             "reason": "för få varumärken"},
        ],
        "row_count": 3, "meta": {},
    }
    result = from_tool_result(supplier_id=1, tool="query_market_share",
                              tool_args={}, payload=payload)
    share = result.preview()["aggregates"]["share_pct"]

    assert share["counted_rows"] == 2
    assert share["mean"] == 25.0
    assert share["min"]["value"] == 20.0
    assert share["min"]["subcategory"] == "Högtalare"


def test_the_suppression_flag_never_becomes_an_entity_label():
    """`suppressed` and `reason` describe a row's status, not the thing it is about."""
    payload = {
        "rows": [{"subcategory": "Hörlurar", "share_pct": 30.0,
                  "suppressed": False, "reason": None}],
        "row_count": 1, "meta": {},
    }
    result = from_tool_result(supplier_id=1, tool="query_market_share",
                              tool_args={}, payload=payload)

    assert "suppressed" not in result.label_columns()
    assert "reason" not in result.label_columns()
    assert set(result.preview()["aggregates"]["share_pct"]["max"]) == {"value", "subcategory"}


def test_a_boolean_column_is_not_aggregated_as_a_number():
    """bool is a subclass of int in Python, so a careless sum would report that 1.0 of the rows
    were suppressed."""
    payload = {
        "rows": [{"subcategory": "A", "suppressed": True},
                 {"subcategory": "B", "suppressed": False}],
        "row_count": 2, "meta": {},
    }
    result = from_tool_result(supplier_id=1, tool="query_market_share",
                              tool_args={}, payload=payload)
    assert "suppressed" not in result.preview()["aggregates"]


def test_a_column_with_no_numeric_values_is_omitted_rather_than_zeroed():
    payload = {
        "columns": [{"key": "product", "type": "text", "label": "P"},
                    {"key": "net_sales_sek", "type": "number", "label": "N"}],
        "rows": [{"product": "A", "net_sales_sek": None}],
        "row_count": 1, "meta": {},
    }
    result = from_tool_result(supplier_id=1, tool="query_sales", tool_args={},
                              payload=payload)
    assert result.preview()["aggregates"] == {}
