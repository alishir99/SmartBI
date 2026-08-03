"""Tool input schemas."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MeasureKey = Literal[
    "net_sales_sek",
    "gross_sales_sek",
    "discount_sek",
    "units",
    "avg_price_sek",
    "discount_rate",
    "orders",
]

DimensionKey = Literal[
    "day", "week", "month", "quarter", "year",
    "month_of_year", "weekday", "is_holiday", "campaign_id",
    "product", "brand", "subcategory", "category",
    "region", "channel", "store", "city",
    "customer_segment", "loyalty_tier",
]

RelativeRange = Literal[
    "last_7_days", "last_30_days", "last_90_days", "last_6_months", "last_12_months",
    "last_month", "this_month", "this_year", "ytd", "all_time",
]

CompareTo = Literal["previous_period", "same_period_last_year"]

Channel = Literal["fysisk", "online"]

EntityKind = Literal["product", "category", "store", "brand", "region"]


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[int] | None = Field(
        None, description="Produkt-ID från resolve_entities.")
    brand_ids: list[int] | None = Field(
        None, description="Varumärkes-ID från resolve_entities. Endast egna varumärken.")
    category_ids: list[int] | None = Field(
        None, description="Kategori- eller underkategori-ID. En huvudkategori expanderas "
                          "automatiskt till sina underkategorier.")
    store_ids: list[int] | None = Field(
        None, description="Butiks-ID. Tvingar frågan till faktatabellen.")
    region: list[str] | None = Field(
        None, description="Län, exakt som de heter i get_capabilities.")
    channel: list[Channel] | None = None


class TimeRange(BaseModel):
    """Either an explicit window or a named one - not both."""

    model_config = ConfigDict(extra="forbid")

    from_date: date | None = Field(None, alias="from")
    to: date | None = None
    relative: RelativeRange | None = None


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure: MeasureKey | None = None
    dimension: DimensionKey | None = None
    # The one free-text field on the whole tool surface, and the reason it is safe: it is
    # matched against the column list the compiler is about to emit and rejected if absent, so
    # it can only ever name a column this query already has.
    field: str | None = Field(
        None, description="Kolumnnyckel ur resultatet, för härledda kolumner: "
                          "'<mått>_delta_pct' och '<mått>_compare' (kräver compare_to), "
                          "'<mått>_pct_of_total' (kräver percent_of_total). "
                          "Okända nycklar avvisas.")
    dir: Literal["asc", "desc"] = "desc"


class Having(BaseModel):
    """Filter on an aggregate - the threshold applies after grouping, not per order line."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        description="Ett hämtat mått, eller dess härledda kolumn under compare_to "
                    "('<mått>_compare', '<mått>_delta_pct'). Dimensioner filtreras med "
                    "filters, inte här.")
    op: Literal[">", ">=", "<", "<=", "=", "!="]
    value: float


class TopNPer(BaseModel):
    """Top N *within* each value of a dimension, rather than N rows overall."""

    model_config = ConfigDict(extra="forbid")

    dimension: DimensionKey = Field(
        description="Dimensionen att dela upp topplistan på. Måste också finnas i "
                    "dimensions.")
    n: int = Field(ge=1, description="Antal rader per värde i dimensionen.")
