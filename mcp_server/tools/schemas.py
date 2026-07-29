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
    dir: Literal["asc", "desc"] = "desc"
