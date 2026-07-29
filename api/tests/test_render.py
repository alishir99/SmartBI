"""Tests for deterministic chart selection and ChartSpec validation (§8).

The point of choosing the chart from the result's shape *before* consulting the model is that
every chart in the product looks like it belongs to the same product. These tests pin the
mapping, and pin that a model override is only honoured when it references real columns.
"""

from __future__ import annotations

from api.agent.render import (
    build_card,
    propose_chart,
    split_answer,
    validate_chart,
)
from api.models import ChartSpec
from api.result_cache import CachedResult

META = {"tool": "query_sales", "source": "mv_sales_daily (rollup)", "scope": "supplier:abcd",
        "time_range": {"from": "2025-07-01", "to": "2026-06-30"},
        "coverage": {"from": "2024-07-01", "to": "2026-06-30"},
        "executed_at": "2026-07-28T10:00:00Z"}


def make(columns, rows, **kwargs) -> CachedResult:
    return CachedResult(query_id="q_1", supplier_id=1, tool="query_sales", tool_args={},
                        columns=columns, rows=rows, row_count=kwargs.get("row_count", len(rows)),
                        truncated=False, meta=kwargs.get("meta", META))


MEASURE = {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}
MONTH = {"key": "month", "type": "date", "label": "Månad"}
PRODUCT = {"key": "product", "type": "text", "label": "Produkt"}
REGION = {"key": "region", "type": "text", "label": "Län"}


# --------------------------------------------------------------- deterministic mapping

def test_a_single_value_becomes_a_kpi():
    spec = propose_chart(make([MEASURE], [{"net_sales_sek": 93_011_117.0}]))
    assert spec.type == "kpi"
    assert spec.y == ["net_sales_sek"]


def test_a_time_dimension_becomes_a_line():
    spec = propose_chart(make([MONTH, MEASURE], [{"month": "2026-01-01",
                                                  "net_sales_sek": 1.0}]))
    assert spec.type == "line"
    assert spec.x == "month"


def test_one_category_plus_one_measure_becomes_a_bar():
    spec = propose_chart(make([PRODUCT, MEASURE], [{"product": "Nordström TV N100 Pro",
                                                    "net_sales_sek": 1.0}]))
    assert spec.type == "bar"
    assert spec.x == "product"
    assert spec.sort == "desc"


def test_two_categories_become_a_stacked_bar_not_a_pie():
    """Part-of-whole is a stacked bar deliberately: these break down by län, and a
    twenty-one-slice pie is unreadable."""
    # Two rows, not one: stacking is a claim about how several rows compose, and a one-row
    # result now falls through to a plain bar (there is nothing to stack it against).
    spec = propose_chart(make([REGION, PRODUCT, MEASURE], [
        {"region": "Stockholms län", "product": "A", "net_sales_sek": 1.0},
        {"region": "Skåne län", "product": "B", "net_sales_sek": 2.0}]))
    assert spec.type == "stacked_bar"
    assert spec.series == "product"


def test_a_single_row_is_not_stacked_against_itself():
    """query_market_share returns one row per own brand; asking for one brand's share in one
    subcategory yields a single row whose `subcategory` is a constant echo of the filter."""
    spec = propose_chart(make([REGION, PRODUCT, MEASURE], [
        {"region": "Stockholms län", "product": "A", "net_sales_sek": 1.0}]))
    assert spec.type == "bar"


def test_a_time_series_split_by_category_keeps_one_line_per_series():
    spec = propose_chart(make([MONTH, REGION, MEASURE], [
        {"month": "2026-01-01", "region": "Stockholms län", "net_sales_sek": 1.0}]))
    assert spec.type == "line"
    assert spec.series == "region"


def test_many_dimensions_fall_back_to_a_table():
    columns = [MONTH, REGION, PRODUCT, {"key": "channel", "type": "text", "label": "Kanal"},
               MEASURE]
    assert propose_chart(make(columns, [{}])).type == "table"


def test_comparison_columns_are_not_charted_as_series():
    """net_sales_sek and its _delta_pct must not share an axis — kronor next to percent."""
    columns = [MONTH, MEASURE,
               {"key": "net_sales_sek_compare", "type": "number", "label": "Jmf", "unit": "SEK"},
               {"key": "net_sales_sek_delta_pct", "type": "number", "label": "Förändring",
                "unit": "%"}]
    spec = propose_chart(make(columns, [{"month": "2026-01-01", "net_sales_sek": 1.0}]))
    assert spec.y == ["net_sales_sek"]


# ------------------------------------------------------------------- override policy

def test_a_valid_override_is_honoured():
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    override = ChartSpec(type="bar", x="product", y=["net_sales_sek"], title="Topp")
    spec, problems = validate_chart(override, result)
    assert not problems
    assert spec.title == "Topp"


def test_an_override_naming_a_missing_column_is_rejected():
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    override = ChartSpec(type="bar", x="butik", y=["net_sales_sek"], title="Fel")
    spec, problems = validate_chart(override, result)
    assert problems
    assert spec.x == "product", "must fall back to the deterministic proposal"


def test_a_text_column_cannot_be_put_on_the_value_axis():
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    override = ChartSpec(type="bar", x="net_sales_sek", y=["product"], title="Bakvänt")
    _, problems = validate_chart(override, result)
    assert any("inte numerisk" in p for p in problems)


def test_a_malformed_override_does_not_lose_the_answer():
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    card = build_card(result=result, narrative="Svar.",
                      envelope={"chart": {"type": "sunburst", "title": "Nej"}})
    assert card.chart is not None and card.chart.type == "bar"
    assert card.narrative == "Svar."
    assert any("ogiltigt" in c for c in card.caveats)


# ------------------------------------------------------------------ answer envelope

def test_the_json_block_is_split_from_the_prose():
    narrative, envelope = split_answer(
        'Försäljningen ökade.\n\n```json\n{"status": "ok", "query_id": "q_1"}\n```')
    assert narrative == "Försäljningen ökade."
    assert envelope["query_id"] == "q_1"


def test_the_last_json_block_wins():
    narrative, envelope = split_answer(
        'Exempel:\n```json\n{"status": "clarify"}\n```\nSvar.\n'
        '```json\n{"status": "ok"}\n```')
    assert envelope["status"] == "ok"
    assert "Svar." in narrative


def test_a_missing_block_still_yields_the_prose():
    narrative, envelope = split_answer("Bara text, inget block.")
    assert narrative == "Bara text, inget block."
    assert envelope == {}


def test_malformed_json_does_not_raise():
    narrative, envelope = split_answer('Svar.\n```json\n{not json}\n```')
    assert envelope == {}
    assert "Svar." in narrative


# ------------------------------------------------------------------------- the card

def test_validation_failure_keeps_the_chart_and_drops_the_prose():
    """The safety guarantee, as the user experiences it."""
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    card = build_card(result=result, narrative="Detta innehöll ett påhittat tal.",
                      envelope={}, status="validation_failed")
    assert card.narrative == ""
    assert card.chart is not None
    assert card.query_id == "q_1"
    assert "kunde inte verifieras" in card.caveats[0]


def test_cannot_answer_carries_suggestions_and_no_chart():
    card = build_card(result=None, narrative="Marginal finns inte i datan.",
                      envelope={"suggestions": ["Visa nettoförsäljning istället"]},
                      status="cannot_answer")
    assert card.chart is None
    assert card.query_id is None
    assert card.suggestions == ["Visa nettoförsäljning istället"]


def test_provenance_is_built_from_the_tools_own_meta():
    result = make([PRODUCT, MEASURE], [{"product": "A", "net_sales_sek": 1.0}])
    card = build_card(result=result, narrative="Svar.", envelope={})
    assert card.provenance is not None
    assert card.provenance.source == "mv_sales_daily (rollup)"
    assert card.provenance.scope == "supplier:abcd"
    assert card.provenance.vat == "exkl. moms"
