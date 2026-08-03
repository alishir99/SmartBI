"""Compile a typed QuerySpec into parameterised SQL."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .model import (
    BASE_JOINS,
    CHANNELS,
    DATE_EXPR,
    DEFAULT_LIMIT,
    DIMENSIONS,
    FACT,
    JOINS,
    MAX_ROWS,
    MEASURES,
    RELATIVE_RANGES,
    ROLLUP,
)


class SpecError(ValueError):
    """The request cannot be expressed. Always the caller's fault, never a 500."""


# What `having.op` may say, and what that becomes in SQL.
HAVING_OPS = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "=", "!=": "<>"}


@dataclass
class Params:
    """Bound parameters for asyncpg, in order."""

    values: list = field(default_factory=list)

    def add(self, value) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


@dataclass
class CompiledQuery:
    sql: str
    params: list
    source: str
    columns: list[dict]
    time_range: tuple[date, date]
    compare_range: tuple[date, date] | None


def resolve_time_range(spec: dict, coverage: tuple[date, date]) -> tuple[date, date]:
    """Turn either explicit dates or a named window into a concrete [from, to]."""
    coverage_from, coverage_to = coverage
    time_range = spec.get("time_range") or {}

    if isinstance(time_range, str):
        time_range = {"relative": time_range}

    relative = time_range.get("relative")
    if relative:
        if relative not in RELATIVE_RANGES:
            raise SpecError(f"okänt tidsintervall '{relative}'; tillåtna: {RELATIVE_RANGES}")
        anchor = coverage_to
        match relative:
            case "last_7_days":
                return max(coverage_from, anchor - timedelta(days=6)), anchor
            case "last_30_days":
                return max(coverage_from, anchor - timedelta(days=29)), anchor
            case "last_90_days":
                return max(coverage_from, anchor - timedelta(days=89)), anchor
            case "last_6_months":
                return max(coverage_from, _months_back(anchor, 6) + timedelta(days=1)), anchor
            case "last_12_months":
                return max(coverage_from, _months_back(anchor, 12) + timedelta(days=1)), anchor
            case "last_month":
                first_this = anchor.replace(day=1)
                last_prev = first_this - timedelta(days=1)
                return last_prev.replace(day=1), last_prev
            case "this_month":
                return anchor.replace(day=1), anchor
            case "this_year" | "ytd":
                return max(coverage_from, date(anchor.year, 1, 1)), anchor
            case "all_time":
                return coverage_from, coverage_to

    start = time_range.get("from")
    end = time_range.get("to")
    if not start or not end:
        # No period given at all: the last full 12 months is the least surprising default, and
        # meta.time_range reports it so the answer can never be silently undated.
        return (max(coverage_from, _months_back(coverage_to, 12) + timedelta(days=1)),
                coverage_to)

    start = date.fromisoformat(start) if isinstance(start, str) else start
    end = date.fromisoformat(end) if isinstance(end, str) else end
    if start > end:
        raise SpecError("time_range.from är efter time_range.to")
    return start, end


def _months_back(anchor: date, months: int) -> date:
    """The same day-of-month N months earlier, clamped to the length of that month."""
    month_index = anchor.month - 1 - months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def shift_range(window: tuple[date, date], mode: str) -> tuple[date, date]:
    """The comparison window for compare_to."""
    start, end = window
    if mode == "previous_period":
        span = (end - start).days + 1
        return start - timedelta(days=span), start - timedelta(days=1)
    if mode == "same_period_last_year":
        return _same_day_last_year(start), _same_day_last_year(end)
    raise SpecError(f"okänd compare_to '{mode}'")


def _same_day_last_year(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:            # 29 Feb
        return value.replace(year=value.year - 1, day=28)


def choose_source(dimensions: list[str], measures: list[str], filters: dict) -> str:
    """Rollup unless something genuinely needs the fact table."""
    for key in dimensions:
        if key not in DIMENSIONS:
            raise SpecError(f"okänd dimension '{key}'; tillåtna: {sorted(DIMENSIONS)}")
        if not DIMENSIONS[key].available_in(ROLLUP):
            return FACT
    for key in measures:
        if key not in MEASURES:
            raise SpecError(f"okänt mått '{key}'; tillåtna: {sorted(MEASURES)}")
        if not MEASURES[key].available_in(ROLLUP):
            return FACT
    if filters.get("store_ids"):
        return FACT
    return ROLLUP


def _validate(spec: dict) -> tuple[list[str], list[str], dict]:
    measures = list(spec.get("measures") or [])
    dimensions = list(spec.get("dimensions") or [])
    filters = dict(spec.get("filters") or {})

    if not measures:
        raise SpecError("minst ett mått krävs")
    if len(dimensions) != len(set(dimensions)):
        raise SpecError("dimensioner måste vara unika")

    for key in measures:
        if key not in MEASURES:
            raise SpecError(f"okänt mått '{key}'; tillåtna: {sorted(MEASURES)}")
    for key in dimensions:
        if key not in DIMENSIONS:
            raise SpecError(f"okänd dimension '{key}'; tillåtna: {sorted(DIMENSIONS)}")

    unknown = set(filters) - {
        "product_ids", "brand_ids", "category_ids", "store_ids", "region", "channel"}
    if unknown:
        raise SpecError(f"okända filter: {sorted(unknown)}")

    for channel in filters.get("channel") or []:
        if channel not in CHANNELS:
            raise SpecError(f"okänd kanal '{channel}'; tillåtna: {CHANNELS}")

    return measures, dimensions, filters


def _where(source: str, filters: dict, window: tuple[date, date],
           params: Params, joins: set[str]) -> list[str]:
    date_expr = DATE_EXPR[source]
    clauses = [f"{date_expr} BETWEEN {params.add(window[0])} AND {params.add(window[1])}"]

    if ids := filters.get("product_ids"):
        column = "s.product_id" if source == ROLLUP else "f.product_id"
        clauses.append(f"{column} = ANY({params.add(list(ids))}::int[])")

    if ids := filters.get("brand_ids"):
        joins.update(("product",))
        clauses.append(f"p.brand_id = ANY({params.add(list(ids))}::int[])")

    if ids := filters.get("category_ids"):
        joins.update(("product",))
        # Two-level hierarchy: a level-1 id matches every product in its children, a level-2 id
        # matches directly.
        placeholder = params.add(list(ids))
        clauses.append(
            f"p.category_id IN (SELECT category_id FROM dim_category "
            f"WHERE category_id = ANY({placeholder}::int[]) "
            f"   OR parent_id = ANY({placeholder}::int[]))")

    if ids := filters.get("store_ids"):
        if source == ROLLUP:
            raise SpecError("butiksfilter kräver faktatabellen")
        clauses.append(f"f.store_id = ANY({params.add(list(ids))}::int[])")

    if regions := filters.get("region"):
        column = "s.region" if source == ROLLUP else "st.region"
        if source == FACT:
            joins.add("store")
        clauses.append(f"{column} = ANY({params.add(list(regions))}::text[])")

    if channels := filters.get("channel"):
        column = "s.channel" if source == ROLLUP else "st.channel"
        if source == FACT:
            joins.add("store")
        clauses.append(f"{column} = ANY({params.add(list(channels))}::text[])")

    # Note what is *absent*: any supplier predicate.
    return clauses


def _select_block(source: str, measures: list[str], dimensions: list[str],
                  window: tuple[date, date], filters: dict, params: Params,
                  date_ordinals: bool = False) -> str:
    """One aggregated SELECT over the chosen source."""
    joins: set[str] = set(BASE_JOINS[source])
    date_expr = DATE_EXPR[source]

    select_parts, group_parts = [], []
    for key in dimensions:
        dimension = DIMENSIONS[key]
        joins.update(dimension.requires(source))
        expr = dimension.expr[source].format(date=date_expr)
        select_parts.append(f"{expr} AS {key}")
        group_parts.append(expr)
        if date_ordinals and dimension.type == "date":
            # Window functions run after GROUP BY, so this ranks the grouped periods.
            select_parts.append(f"DENSE_RANK() OVER (ORDER BY {expr}) AS {key}__ord")

    for key in measures:
        measure = MEASURES[key]
        joins.update(measure.requires(source))
        select_parts.append(f"{measure.expr[source]} AS {key}")

    where = _where(source, filters, window, params, joins)

    # Join order matters: dim_brand needs dim_product, dim_category(top) needs sub.
    ordered = [name for name in JOINS[source] if name in joins]
    from_clause = ("v_sales_daily s" if source == ROLLUP else "fact_sales_line f")
    join_sql = "\n    ".join(JOINS[source][name] for name in ordered)

    sql = f"SELECT {', '.join(select_parts)}\n  FROM {from_clause}"
    if join_sql:
        sql += f"\n    {join_sql}"
    sql += f"\n WHERE {' AND '.join(where)}"
    if group_parts:
        sql += f"\n GROUP BY {', '.join(group_parts)}"
    return sql


def _positive_int(value, name: str) -> int:
    # bool is an int in Python, so `limit=True` would otherwise pass as "one row". A caller who
    # sends a boolean has made a mistake and should hear about it.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SpecError(f"{name} måste vara ett positivt heltal")
    return value


def _order_key(order_by: dict, available: list[str]) -> tuple[str, str]:
    """Resolve one sort key against the columns the query actually returns."""
    key = order_by.get("field") or order_by.get("measure") or order_by.get("dimension")
    if key not in available:
        raise SpecError(f"kan inte sortera på '{key}'; tillgängliga kolumner: {available}")
    direction = "DESC" if str(order_by.get("dir", "desc")).lower() == "desc" else "ASC"
    return key, direction


def _post_aggregate(sql: str, spec: dict, measures: list[str], dimensions: list[str],
                    columns: list[dict], params: Params,
                    compare: bool) -> tuple[str, list[dict], list[str] | None]:
    """Share-of-total, aggregate filtering and per-partition top-N, applied after grouping."""
    percent_of_total = spec.get("percent_of_total")
    having = spec.get("having")
    top_n_per = spec.get("top_n_per")
    if not (percent_of_total or having or top_n_per):
        return sql, columns, None

    base_keys = [column["key"] for column in columns]
    select_parts = list(base_keys)

    share_of: list[str] = []
    if percent_of_total:
        share_of = [key for key in measures if MEASURES[key].additive]
        if not share_of:
            raise SpecError(
                f"percent_of_total kräver ett summerbart mått; {sorted(measures)} är "
                "kvoter vars andelar inte betyder något")
        for key in share_of:
            measure = MEASURES[key]
            # 100.0, not 100: SUM(qty) is a bigint and integer division would silently truncate
            # every share to a whole percent.
            select_parts.append(
                f"ROUND((100.0 * {key} / NULLIF(SUM({key}) OVER (), 0))::numeric, 1) "
                f"AS {key}_pct_of_total")
            columns = [*columns, {"key": f"{key}_pct_of_total", "type": "number", "unit": "%",
                                  "label": f"{measure.label} (andel av totalen)"}]

    output_keys = [column["key"] for column in columns]

    where = ""
    if having:
        # Only aggregates: filtering a dimension is what `filters` is for, and doing it here
        # would run after the grouping instead of before it - same rows, more work, and a second
        # way to express one thing.
        aggregate_keys = set(measures)
        if compare:
            aggregate_keys |= {f"{key}_compare" for key in measures}
            aggregate_keys |= {f"{key}_delta" for key in measures}
            aggregate_keys |= {f"{key}_delta_pct" for key in measures}
        key = having.get("field") or having.get("measure")
        if key not in aggregate_keys:
            raise SpecError(
                f"having kan bara filtrera på ett hämtat mått; '{key}' är inte ett av "
                f"{sorted(aggregate_keys)}. Använd filters för att filtrera på dimensioner.")
        operator = HAVING_OPS.get(having.get("op"))
        if operator is None:
            raise SpecError(
                f"okänd operator '{having.get('op')}'; tillåtna: {sorted(HAVING_OPS)}")
        value = having.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
            raise SpecError("having.value måste vara ett tal")
        # Both sides cast to numeric: the measures are a mix of numeric and bigint, and Decimal
        # is the only Python type asyncpg encodes as numeric without complaint.
        where = (f"\n WHERE {key}::numeric {operator} "
                 f"{params.add(Decimal(str(value)))}::numeric")

    order: list[str] | None = None
    if top_n_per:
        partition = top_n_per.get("dimension")
        if partition not in dimensions:
            raise SpecError(f"top_n_per.dimension '{partition}' måste vara en av de "
                            f"grupperade dimensionerna {dimensions}")
        rows = _positive_int(top_n_per.get("n"), "top_n_per.n")
        order_by = spec.get("order_by")
        if order_by:
            rank_key, direction = _order_key(order_by, output_keys)
            if rank_key not in base_keys:
                # A window function cannot see another window function's alias at the same
                # level, and ranking by a share is in any case the same order as ranking by the
                # measure it divides.
                raise SpecError(f"kan inte rangordna top_n_per på '{rank_key}'; "
                                "använd måttet självt")
        else:
            rank_key, direction = measures[0], "DESC"
        select_parts.append(f"ROW_NUMBER() OVER (PARTITION BY {partition} "
                            f"ORDER BY {rank_key} {direction} NULLS LAST) AS __rank")
        order = [f"{partition} ASC NULLS LAST", f"{rank_key} {direction} NULLS LAST"]

    sql = f"SELECT {', '.join(select_parts)}\n  FROM (\n{sql}\n) q{where}"
    if top_n_per:
        # A second level, because a window function is not available to the WHERE of the SELECT
        # that computes it.
        sql = (f"SELECT {', '.join(output_keys)}\n  FROM (\n{sql}\n) w"
               f"\n WHERE __rank <= {params.add(rows)}")
    return sql, columns, order


def compile_query(spec: dict, coverage: tuple[date, date]) -> CompiledQuery:
    """Validate and compile. Raises SpecError on anything it cannot express."""
    measures, dimensions, filters = _validate(spec)
    source = choose_source(dimensions, measures, filters)
    window = resolve_time_range(spec, coverage)

    compare_to = spec.get("compare_to")
    compare_window = shift_range(window, compare_to) if compare_to else None

    params = Params()
    current = _select_block(source, measures, dimensions, window, filters, params)

    if compare_window is None:
        sql = current
        columns = _columns(dimensions, measures, compare=False)
    else:
        date_dimensions = [key for key in dimensions if DIMENSIONS[key].type == "date"]
        if date_dimensions:
            # Both blocks have to be rebuilt with the ordinal, including the current one.
            params = Params()
            current = _select_block(source, measures, dimensions, window, filters,
                                    params, date_ordinals=True)
        previous = _select_block(source, measures, dimensions, compare_window,
                                 filters, params, date_ordinals=bool(date_dimensions))

        if dimensions:
            # FULL OUTER so a group present in only one period still appears.
            conditions, select_parts = [], []
            for key in dimensions:
                if key in date_dimensions:
                    conditions.append(f"c.{key}__ord = pv.{key}__ord")
                    # Both real dates are returned: the caller needs to label the comparison
                    # series with the period it actually came from.
                    select_parts.append(f"c.{key}")
                    select_parts.append(f"pv.{key} AS {key}_compare")
                else:
                    conditions.append(f"c.{key} = pv.{key}")
                    select_parts.append(f"COALESCE(c.{key}, pv.{key}) AS {key}")
            join = f"FULL OUTER JOIN prev pv ON {' AND '.join(conditions)}"
        else:
            join = "CROSS JOIN prev pv"
            select_parts = []

        for key in measures:
            select_parts += [
                f"c.{key}",
                f"pv.{key} AS {key}_compare",
                # Both deltas are computed here rather than by the model. The absolute one is
                # what "biggest mover" should usually mean: ranking on the percentage alone
                # puts a product that went from 400 kr to 6 000 kr above one that gained a
                # million, and draws a chart with one bar in it.
                f"(c.{key} - pv.{key}) AS {key}_delta",
                f"ROUND((100.0 * (c.{key} - pv.{key}) / "
                f"NULLIF(ABS(pv.{key}), 0))::numeric, 1) AS {key}_delta_pct",
            ]

        sql = (f"WITH cur AS (\n{current}\n), prev AS (\n{previous}\n)\n"
               f"SELECT {', '.join(select_parts)}\n  FROM cur c\n  {join}")
        columns = _columns(dimensions, measures, compare=True)

    sql, columns, order = _post_aggregate(sql, spec, measures, dimensions, columns, params,
                                          compare=compare_window is not None)

    order_by = spec.get("order_by")
    if order:
        # Forced by top_n_per: the partitions have to come out grouped.
        keys = order
    elif order_by:
        key, direction = _order_key(order_by, [str(column["key"]) for column in columns])
        keys = [f"{key} {direction} NULLS LAST"]
    elif dimensions:
        # Every grouped query gets a total order, and it has to be *total* rather than merely
        # present.
        leading = dimensions[0]
        if DIMENSIONS[leading].type == "date":
            # NULLS LAST matters under compare: a period present only in the comparison window
            # has no current date, and should trail rather than lead the series.
            keys = [f"{leading} ASC NULLS LAST"]
        else:
            keys = [f"{measures[0]} DESC NULLS LAST"]
        keys += [f"{key} ASC NULLS LAST" for key in dimensions if key != leading]
    else:
        keys = []

    if keys:
        sql = f"SELECT * FROM (\n{sql}\n) q ORDER BY {', '.join(keys)}"

    # `or DEFAULT_LIMIT` would quietly turn limit=0 into 500.
    limit = spec.get("limit")
    limit = DEFAULT_LIMIT if limit is None else _positive_int(limit, "limit")
    sql += f"\n LIMIT {min(limit, MAX_ROWS)}"

    return CompiledQuery(sql=sql, params=params.values, source=source, columns=columns,
                         time_range=window, compare_range=compare_window)


def _columns(dimensions: list[str], measures: list[str],
             compare: bool) -> list[dict]:
    columns: list[dict] = []
    for key in dimensions:
        dimension = DIMENSIONS[key]
        columns.append({"key": key, "type": dimension.type, "label": dimension.label})
        if compare and dimension.type == "date":
            # The compare row carries its own real date, not just the current one.
            columns.append({"key": f"{key}_compare", "type": dimension.type,
                            "label": f"{dimension.label} (jämförelse)"})
    for key in measures:
        measure = MEASURES[key]
        columns.append({"key": key, "type": "number", "unit": measure.unit,
                        "label": measure.label})
        if compare:
            columns.append({"key": f"{key}_compare", "type": "number",
                            "unit": measure.unit, "label": f"{measure.label} (jämförelse)"})
            columns.append({"key": f"{key}_delta", "type": "number", "unit": measure.unit,
                            "label": f"{measure.label} (förändring)"})
            columns.append({"key": f"{key}_delta_pct", "type": "number", "unit": "%",
                            "label": f"{measure.label} (förändring i %)"})
    return columns
