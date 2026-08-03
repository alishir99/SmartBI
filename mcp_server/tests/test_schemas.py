"""Tests on the tool surface the model actually sees."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from mcp_server.semantic.model import DIMENSIONS, MEASURES, RELATIVE_RANGES
from mcp_server.server import mcp
from mcp_server.tools.schemas import (
    CompareTo,
    DimensionKey,
    Filters,
    MeasureKey,
    OrderBy,
    RelativeRange,
    TimeRange,
)

EXPECTED_TOOLS = {"get_capabilities", "resolve_entities", "query_sales",
                  "query_market_share"}


@pytest.fixture
async def tools():
    return await mcp.list_tools()


# --------------------------------------------------------------- the isolation test


async def test_no_tool_lets_the_caller_name_a_supplier(tools):
    """If this fails, the whole tenancy argument in the plan collapses."""
    for tool in tools:
        schema = json.dumps(tool.inputSchema).lower()
        assert "supplier_id" not in schema, f"{tool.name} exposes supplier_id"
        assert "supplier" not in (tool.inputSchema.get("properties") or {})


async def test_exactly_four_tools_are_exposed(tools):
    """A small, orthogonal tool set outperforms a large one - keep it deliberate."""
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_every_tool_has_a_description_for_the_model(tools):
    for tool in tools:
        assert tool.description and len(tool.description) > 40, tool.name


# ------------------------------------------------------------------- drift guards schemas.py
# spells the enums out so a reader can see what the model sees.


def test_measure_keys_match_the_registry():
    assert set(get_args(MeasureKey)) == set(MEASURES)


def test_dimension_keys_match_the_registry():
    assert set(get_args(DimensionKey)) == set(DIMENSIONS)


def test_relative_ranges_match_the_registry():
    assert set(get_args(RelativeRange)) == set(RELATIVE_RANGES)


def test_compare_modes_are_the_two_the_compiler_implements():
    assert set(get_args(CompareTo)) == {"previous_period", "same_period_last_year"}


# ------------------------------------------------------------ strictness of inputs


@pytest.mark.parametrize("model", [Filters, TimeRange, OrderBy])
def test_input_models_forbid_unknown_fields(model):
    """extra=forbid becomes additionalProperties:false, so an invented parameter is a validation
    error instead of a silently dropped field."""
    assert model.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        model(nonsense_field=1)


def test_filters_cannot_carry_a_supplier():
    with pytest.raises(ValidationError):
        Filters(supplier_id=3)


def test_query_sales_requires_at_least_a_measure(tools):
    tool = next(t for t in tools if t.name == "query_sales")
    assert "measures" in tool.inputSchema.get("required", [])


def test_channel_filter_is_enum_constrained():
    with pytest.raises(ValidationError):
        Filters(channel=["telefon"])
    assert Filters(channel=["online"]).channel == ["online"]


def test_time_range_accepts_the_from_alias():
    """`from` is a Python keyword, so the field is from_date with an alias."""
    parsed = TimeRange.model_validate({"from": "2026-01-01", "to": "2026-03-31"})
    assert parsed.from_date.isoformat() == "2026-01-01"
    assert parsed.to.isoformat() == "2026-03-31"
