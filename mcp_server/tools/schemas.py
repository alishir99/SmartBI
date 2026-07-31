"""Tool input schemas.

Written as explicit `Literal`s rather than generated from the registry, because these are
what the model sees and a reader of this file should be able to see them too. A drift test
(tests/test_schemas.py) fails the build if they stop matching model.py, so the duplication
cannot rot.

Every model sets `extra="forbid"`, which becomes `additionalProperties: false` in the JSON
schema — so an invented parameter is a validation error rather than a silently ignored
field. Notably absent from all of them: `supplier_id`.
"""

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
    """Either an explicit window or a named one — not both."""

    model_config = ConfigDict(extra="forbid")

    from_date: date | None = Field(None, alias="from")
    to: date | None = None
    relative: RelativeRange | None = None


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure: MeasureKey | None = None
    dimension: DimensionKey | None = None
    # The one free-text field on the whole tool surface, and the reason it is safe: it is
    # matched against the column list the compiler is about to emit and rejected if absent,
    # so it can only ever name a column this query already has. It exists because the
    # interesting sort keys are derived and therefore have no registry entry — sorting by
    # net_sales_sek_delta_pct is the difference between finding the biggest decliner and
    # finding the biggest seller that happens to have declined.
    field: str | None = Field(
        None, description="Kolumnnyckel ur resultatet, för härledda kolumner: "
                          "'<mått>_delta_pct' och '<mått>_compare' (kräver compare_to), "
                          "'<mått>_pct_of_total' (kräver percent_of_total). "
                          "Okända nycklar avvisas.")
    dir: Literal["asc", "desc"] = "desc"


class Having(BaseModel):
    """Filter on an aggregate — the threshold applies after grouping, not per order line."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        description="Ett hämtat mått, eller dess härledda kolumn under compare_to "
                    "('<mått>_compare', '<mått>_delta_pct'). Dimensioner filtreras med "
                    "filters, inte här.")
    op: Literal[">", ">=", "<", "<=", "=", "!="]
    value: float


class TopNPer(BaseModel):
    """Top N *within* each value of a dimension, rather than N rows overall.

    Without this, "topplista per län" is a global LIMIT and returns the ten best rows in the
    country — which in practice is ten Stockholm rows and no list per county at all.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: DimensionKey = Field(
        description="Dimensionen att dela upp topplistan på. Måste också finnas i "
                    "dimensions.")
    n: int = Field(ge=1, description="Antal rader per värde i dimensionen.")
