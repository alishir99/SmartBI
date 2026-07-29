"""query_market_share — the one tool that reads beyond the caller's own rows.

It is a separate tool for exactly that reason (§6.2): the privileged read lives in one
auditable place instead of being a flag buried inside query_sales. Everything it returns is
an aggregate. Competitor brands are never named and never itemised, and a slice too thin to
aggregate safely returns `suppressed` rather than a number.

Grain: one row per own brand × subcategory, over the requested window. Per *brand* rather
than per supplier because rank is only meaningful against comparable units — a supplier with
two brands in one subcategory competes there twice, and adding them together before ranking
against single brands would flatter it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .. import db
from ..semantic.compiler import Params, resolve_time_range
from ..tenant import TenantContext
from .sales import _jsonable, scope_label

# A slice must contain at least this many competing brands and this many transactions
# before any share figure is returned. Below either threshold, "din andel" plus arithmetic
# would recover a named competitor's revenue (§11.3).
MIN_BRANDS = 5
MIN_TRANSACTIONS = 100

SQL = """
WITH own AS (
    SELECT b.brand_id, b.category_id,
           SUM(b.net_sales_sek) AS own_net_sek,
           SUM(b.qty)           AS own_units
      FROM v_brand_monthly b
     WHERE b.month BETWEEN date_trunc('month', $1::date) AND date_trunc('month', $2::date)
           {category_clause}{region_clause}
     GROUP BY b.brand_id, b.category_id
),
peers AS (
    SELECT p.category_id, p.brand_id,
           SUM(p.net_sales_sek) AS brand_net_sek
      FROM v_category_brand_monthly p
     WHERE p.month BETWEEN date_trunc('month', $1::date) AND date_trunc('month', $2::date)
           {category_clause}{region_clause}
     GROUP BY p.category_id, p.brand_id
),
field AS (
    SELECT category_id,
           COUNT(*)           AS n_brands,
           MAX(brand_net_sek) AS leader_net_sek
      FROM peers
     GROUP BY category_id
),
totals AS (
    SELECT t.category_id,
           SUM(t.total_net_sek)  AS category_net_sek,
           SUM(t.n_transactions) AS n_transactions
      FROM v_category_daily t
     WHERE t.date BETWEEN $1 AND $2
           {category_clause}{region_clause}
     GROUP BY t.category_id
)
SELECT br.name          AS brand,
       c.name           AS subcategory,
       own.category_id,
       own.own_net_sek,
       own.own_units,
       totals.category_net_sek,
       totals.n_transactions,
       field.n_brands,
       field.leader_net_sek,
       (SELECT COUNT(*) + 1 FROM peers pr
         WHERE pr.category_id = own.category_id
           AND pr.brand_net_sek > own.own_net_sek) AS rank
  FROM own
  JOIN dim_brand    br ON br.brand_id    = own.brand_id
  JOIN dim_category c  ON c.category_id  = own.category_id
  JOIN field           ON field.category_id  = own.category_id
  JOIN totals          ON totals.category_id = own.category_id
 ORDER BY own.own_net_sek DESC
"""


def _snap_to_whole_months(window: tuple[date, date]) -> tuple[date, date]:
    """Widen a window so it starts and ends on calendar month boundaries.

    The own-brand and peer figures come from monthly rollups, so the numerator is
    always a whole number of months. Leaving the category total on the exact
    requested dates put a full-month numerator over a part-month denominator, which
    is how a share above 100 % was reachable from the dashboard's own last_7_days
    chip. Snapping both sides to the same months is what makes the ratio meaningful.

    It also removes the finest axis for differencing the k-anonymity guard: an
    arbitrary date window can no longer be nudged a day at a time to isolate a
    single competitor's contribution (§11.3).
    """
    start, end = window
    first = start.replace(day=1)
    # Day 28 + 4 days always lands in the next month, whatever the month length.
    last = (end.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last


async def query_market_share(tenant: TenantContext, spec: dict) -> dict:
    coverage = await db.coverage()
    requested = resolve_time_range(spec, coverage)
    window = _snap_to_whole_months(requested)
    snapped = window != requested

    params = Params()
    params.add(window[0])          # $1
    params.add(window[1])          # $2

    category_clause = ""
    if category_ids := (spec.get("category_ids") or None):
        placeholder = params.add(list(category_ids))
        # Same two-level expansion as query_sales, so "Ljud & Bild" works as well as
        # "Hörlurar". Unqualified column name so the one fragment fits all three CTEs.
        category_clause = (
            f" AND category_id IN (SELECT category_id FROM dim_category "
            f"WHERE category_id = ANY({placeholder}::int[]) "
            f"OR parent_id = ANY({placeholder}::int[]))")

    region_clause = ""
    if regions := (spec.get("region") or None):
        region_clause = f" AND region = ANY({params.add(list(regions))}::text[])"

    sql = SQL.format(category_clause=category_clause, region_clause=region_clause)

    async with db.tenant_connection(tenant.supplier_id) as connection:
        records = await connection.fetch(sql, *params.values)

    rows = [_row(dict(record.items())) for record in records]

    return {
        "rows": rows,
        "row_count": len(rows),
        "suppressed_count": sum(1 for r in rows if r["suppressed"]),
        "meta": {
            "tool": "query_market_share",
            "source": "mv_brand_monthly + mv_category_daily (aggregat)",
            "scope": scope_label(tenant.supplier_id),
            "currency": "SEK",
            "vat": "exkl. moms",
            # The reported range is the one actually measured, not the one asked for.
            # A source chip that showed the requested dates would misdescribe the number.
            "time_range": {
                "from": window[0].isoformat(),
                "to": window[1].isoformat(),
                "requested_from": requested[0].isoformat(),
                "requested_to": requested[1].isoformat(),
                "snapped_to_whole_months": snapped,
            },
            **({"note": (
                f"Marknadsandel mäts per hel kalendermånad. Det begärda intervallet "
                f"{requested[0].isoformat()}–{requested[1].isoformat()} har utökats till "
                f"{window[0].isoformat()}–{window[1].isoformat()}.")} if snapped else {}),
            "k_anonymity": {"min_brands": MIN_BRANDS, "min_transactions": MIN_TRANSACTIONS},
            "policy": "Konkurrenters siffror returneras aldrig, varken namngivna eller "
                      "itemiserade. Endast egen andel, egen placering och kategoritotal.",
            "executed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }


def _row(record: dict) -> dict:
    data = {key: _jsonable(value) for key, value in record.items()}
    n_brands = data.get("n_brands") or 0
    n_transactions = data.get("n_transactions") or 0
    suppressed = n_brands < MIN_BRANDS or n_transactions < MIN_TRANSACTIONS

    row = {
        "brand": data["brand"],
        "subcategory": data["subcategory"],
        "category_id": data["category_id"],
        "own_net_sek": data["own_net_sek"],
        "own_units": data["own_units"],
        "n_brands": n_brands,
        "suppressed": suppressed,
    }

    if suppressed:
        # Everything derivable from the category total is withheld together. Leaving rank
        # in while removing share would still narrow down a competitor's revenue.
        row["reason"] = (
            f"Utelämnat: kategorin innehåller {n_brands} varumärken och {n_transactions} "
            f"köp i urvalet. Marknadsandel visas först vid minst {MIN_BRANDS} varumärken "
            f"och {MIN_TRANSACTIONS} köp, eftersom andelen annars skulle avslöja en "
            f"enskild konkurrents försäljning.")
        return row

    category_net = data["category_net_sek"] or 0
    row.update({
        "category_net_sek": category_net,
        "share_pct": round(100 * data["own_net_sek"] / category_net, 2) if category_net
                     else None,
        "rank": data["rank"],
        "leader_share_pct": (round(100 * data["leader_net_sek"] / category_net, 2)
                             if category_net else None),
    })
    return row
