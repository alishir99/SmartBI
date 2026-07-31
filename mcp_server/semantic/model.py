"""The semantic layer: what may be measured, sliced and filtered.

This registry is the whole reason the design is not text-to-SQL (§6.1). Every identifier
that reaches the database originates here, in code, and every *value* reaches it as a bound
parameter. There is no path by which model-authored text becomes SQL.

Two physical sources answer the same logical questions:

  rollup — v_sales_daily, a security-barrier view over mv_sales_daily. Fast, and already
           scoped to the caller's supplier.
  fact   — fact_sales_line, protected by RLS. Slower, but carries store, customer and
           order grain that the rollup has aggregated away.

The compiler picks the rollup whenever the request is expressible there, and says which it
used in meta.source. Callers never choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROLLUP = "rollup"
FACT = "fact"

# The date column each source exposes; dimension expressions interpolate it as {date}.
DATE_EXPR = {ROLLUP: "s.date", FACT: "d.date"}

# Join fragments, keyed by a short name. A query emits only the joins its selected
# dimensions, measures and filters actually ask for.
JOINS: dict[str, dict[str, str]] = {
    ROLLUP: {
        "product": "JOIN dim_product p ON p.product_id = s.product_id",
        "brand": "JOIN dim_brand b ON b.brand_id = p.brand_id",
        "subcategory": "JOIN dim_category sub ON sub.category_id = p.category_id",
        "category": "JOIN dim_category top ON top.category_id = sub.parent_id",
    },
    FACT: {
        "date": "JOIN dim_date d ON d.date_id = f.date_id",
        "product": "JOIN dim_product p ON p.product_id = f.product_id",
        "brand": "JOIN dim_brand b ON b.brand_id = p.brand_id",
        "subcategory": "JOIN dim_category sub ON sub.category_id = p.category_id",
        "category": "JOIN dim_category top ON top.category_id = sub.parent_id",
        "store": "JOIN dim_store st ON st.store_id = f.store_id",
        "customer": "LEFT JOIN dim_customer cu ON cu.customer_id = f.customer_id",
    },
}

# Joins every query of a given source always needs.
BASE_JOINS = {ROLLUP: (), FACT: ("date",)}


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    type: str                                   # date | text | number
    expr: dict[str, str]                        # source -> SQL expression
    joins: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def requires(self, source: str) -> tuple[str, ...]:
        return self.joins.get(source, ())

    def available_in(self, source: str) -> bool:
        return source in self.expr


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit: str | None
    expr: dict[str, str]
    joins: dict[str, tuple[str, ...]] = field(default_factory=dict)
    description: str = ""
    # Whether the rows of this measure sum to a meaningful whole. Ratios do not: the shares
    # of a total average price add up to 100 % and mean nothing. percent_of_total refuses to
    # emit a column for a non-additive measure rather than emit a plausible wrong one.
    additive: bool = True

    def requires(self, source: str) -> tuple[str, ...]:
        return self.joins.get(source, ())

    def available_in(self, source: str) -> bool:
        return source in self.expr


def _time_dimension(key: str, label: str, trunc: str | None) -> Dimension:
    if trunc is None:
        expr = {ROLLUP: "{date}", FACT: "{date}"}
    else:
        expr = {ROLLUP: f"date_trunc('{trunc}', {{date}})::date",
                FACT: f"date_trunc('{trunc}', {{date}})::date"}
    return Dimension(key=key, label=label, type="date", expr=expr)


DIMENSIONS: dict[str, Dimension] = {d.key: d for d in [
    _time_dimension("day", "Dag", None),
    _time_dimension("week", "Vecka", "week"),
    _time_dimension("month", "Månad", "month"),
    _time_dimension("quarter", "Kvartal", "quarter"),
    _time_dimension("year", "År", "year"),

    Dimension("product", "Produkt", "text",
              expr={ROLLUP: "p.name", FACT: "p.name"},
              joins={ROLLUP: ("product",), FACT: ("product",)}),
    Dimension("brand", "Varumärke", "text",
              expr={ROLLUP: "b.name", FACT: "b.name"},
              joins={ROLLUP: ("product", "brand"), FACT: ("product", "brand")}),
    Dimension("subcategory", "Underkategori", "text",
              expr={ROLLUP: "sub.name", FACT: "sub.name"},
              joins={ROLLUP: ("product", "subcategory"), FACT: ("product", "subcategory")}),
    Dimension("category", "Kategori", "text",
              expr={ROLLUP: "top.name", FACT: "top.name"},
              joins={ROLLUP: ("product", "subcategory", "category"),
                     FACT: ("product", "subcategory", "category")}),
    Dimension("region", "Län", "text",
              expr={ROLLUP: "s.region", FACT: "st.region"},
              joins={FACT: ("store",)}),
    Dimension("channel", "Kanal", "text",
              expr={ROLLUP: "s.channel", FACT: "st.channel"},
              joins={FACT: ("store",)}),

    # Calendar attributes, not periods. A period dimension cuts the window into consecutive
    # slices; these fold it — every July in the window lands in the same group. That is what
    # "vilken månad säljer bäst?" and "hur ser en normalvecka ut?" actually ask, and it is
    # why they are separate keys rather than a mode on `month`.
    Dimension("month_of_year", "Månad på året", "number",
              expr={ROLLUP: "EXTRACT(MONTH FROM {date})::int",
                    FACT: "EXTRACT(MONTH FROM {date})::int"}),
    # ISODOW, so 1 = måndag and the natural numeric sort is the order a Swedish reader
    # expects. dim_date.weekday is 0-based; deriving from the date instead keeps one
    # definition for both sources rather than two that silently differ by one.
    Dimension("weekday", "Veckodag", "number",
              expr={ROLLUP: "EXTRACT(ISODOW FROM {date})::int",
                    FACT: "EXTRACT(ISODOW FROM {date})::int"}),
    # Fact-only: the rollup carries the date but not the calendar's judgement of it, and
    # hard-coding the red days into SQL here would be a second source of truth for them.
    # Returned as words rather than a boolean because the answer is prose, not a flag.
    Dimension("is_holiday", "Dagtyp", "text",
              expr={FACT: "CASE WHEN d.is_holiday THEN 'Röd dag' ELSE 'Vardag' END"}),
    # NULL means "no campaign ran that day", which makes the ordinary days a group of their
    # own — the comparison the question is usually after. There is no dim_campaign, so the
    # id is all there is to return.
    Dimension("campaign_id", "Kampanj", "number",
              expr={FACT: "d.campaign_id"}),

    # Below the rollup's grain — asking for any of these forces the fact table.
    Dimension("store", "Butik", "text",
              expr={FACT: "st.name"}, joins={FACT: ("store",)}),
    Dimension("city", "Stad", "text",
              expr={FACT: "st.city"}, joins={FACT: ("store",)}),
    Dimension("customer_segment", "Kundsegment", "text",
              expr={FACT: "cu.segment"}, joins={FACT: ("customer",)}),
    Dimension("loyalty_tier", "Lojalitetsnivå", "text",
              expr={FACT: "cu.loyalty_tier"}, joins={FACT: ("customer",)}),
]}


MEASURES: dict[str, Measure] = {m.key: m for m in [
    Measure("net_sales_sek", "Nettoförsäljning", "SEK",
            expr={ROLLUP: "SUM(s.net_sales_sek)", FACT: "SUM(f.net_amount_sek)"},
            description="Försäljning efter rabatt och returer, exkl. moms."),
    Measure("gross_sales_sek", "Bruttoförsäljning", "SEK",
            expr={ROLLUP: "SUM(s.gross_sales_sek)", FACT: "SUM(f.gross_amount_sek)"},
            description="Försäljning före rabatt, exkl. moms."),
    Measure("discount_sek", "Rabatt", "SEK",
            expr={ROLLUP: "SUM(s.discount_sek)", FACT: "SUM(f.discount_amount_sek)"},
            description="Total rabatt i kronor."),
    Measure("units", "Sålda enheter", "st",
            expr={ROLLUP: "SUM(s.qty)", FACT: "SUM(f.quantity)"},
            description="Antal sålda enheter, netto efter returer."),
    Measure("avg_price_sek", "Snittpris", "SEK",
            expr={ROLLUP: "SUM(s.net_sales_sek) / NULLIF(SUM(s.qty), 0)",
                  FACT: "SUM(f.net_amount_sek) / NULLIF(SUM(f.quantity), 0)"},
            description="Nettoförsäljning delat med antal enheter.", additive=False),
    Measure("discount_rate", "Rabattgrad", "%",
            expr={ROLLUP: "100 * SUM(s.discount_sek) / NULLIF(SUM(s.gross_sales_sek), 0)",
                  FACT: "100 * SUM(f.discount_amount_sek) / NULLIF(SUM(f.gross_amount_sek), 0)"},
            description="Rabatt som andel av bruttoförsäljning.", additive=False),

    # Deliberately fact-only. The rollup stores n_orders per (date, product, region,
    # channel); summing that across products would count a two-product basket twice.
    # A measure that is only correct at one grain does not belong in the rollup path.
    Measure("orders", "Antal köp", "st",
            expr={FACT: "COUNT(DISTINCT f.order_id)"},
            description="Antal unika köp (ordrar). Räknas alltid på radnivå för att "
                        "undvika dubbelräkning när flera produkter ingår i samma köp."),
]}


# Filters the caller may express. Values are always bound parameters; the column each one
# targets is fixed here and can never come from the request.
FILTER_FIELDS: dict[str, dict[str, str]] = {
    "product_ids": {"label": "Produkter", "type": "int[]"},
    "brand_ids": {"label": "Varumärken", "type": "int[]"},
    "category_ids": {"label": "Kategorier", "type": "int[]",
                     "note": "Accepterar både kategori och underkategori; en "
                             "huvudkategori expanderas till sina underkategorier."},
    "store_ids": {"label": "Butiker", "type": "int[]"},
    "region": {"label": "Län", "type": "text[]"},
    "channel": {"label": "Kanal", "type": "text[]"},
}

CHANNELS = ["fysisk", "online"]

# Relative windows the caller may name instead of giving explicit dates. Resolved against
# the last date present in the data, not against today — the demo dataset ends before the
# current date and silently returning an empty period would be worse than useless.
RELATIVE_RANGES = [
    "last_7_days", "last_30_days", "last_90_days", "last_6_months", "last_12_months",
    "last_month", "this_month", "this_year", "ytd", "all_time",
]

# A tool result never returns more than this many rows regardless of `limit`; the chart
# path pages through the API instead. Keeps one careless request from pulling the fact
# table into memory.
MAX_ROWS = 20_000
DEFAULT_LIMIT = 500
