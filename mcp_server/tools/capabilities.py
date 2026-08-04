"""get_capabilities - the model's map of the world."""

from __future__ import annotations

from .. import db
from ..config import settings
from ..semantic.model import (
    CHANNELS,
    DIMENSIONS,
    FILTER_FIELDS,
    MAX_ROWS,
    MEASURES,
    RELATIVE_RANGES,
    ROLLUP,
)
from ..tenant import TenantContext


async def get_capabilities(tenant: TenantContext) -> dict:
    coverage_from, coverage_to = await db.coverage()

    async with db.tenant_connection(tenant.supplier_id) as connection:
        # Scoped by RLS to the caller's own brands, so this doubles as the answer to "vad räknas
        # som vårt märke?".
        brands = await connection.fetch(
            "SELECT brand_id, name FROM dim_brand ORDER BY name")
        supplier = await connection.fetchrow(
            "SELECT supplier_id, name FROM dim_supplier LIMIT 1")
        categories = await connection.fetch(
            "SELECT category_id, name, level, parent_id FROM dim_category "
            "ORDER BY level, name")
        # Coordinates come along because they are the only thing that lets a map be drawn for
        # a warehouse whose regions nobody hardcoded. The mean store position is a good enough
        # centroid for a proportional-symbol map, and `NULL` where a region has no geocoded
        # store is an honest answer the client can hide a map tab over.
        regions = await connection.fetch(
            "SELECT region, AVG(lat) AS lat, AVG(lon) AS lon "
            "  FROM dim_store GROUP BY region ORDER BY region")
        # Calendar, not sales: dim_date is ~730 rows and carries no tenant data, so this is a
        # dimension read like the four above rather than a trip to the fact table. Each
        # campaign_id is one contiguous run of days, so MIN/MAX is the window.
        campaigns = await connection.fetch(
            "SELECT campaign_id, MIN(date) AS starts, MAX(date) AS ends "
            "  FROM dim_date WHERE campaign_id IS NOT NULL "
            " GROUP BY campaign_id ORDER BY starts")

    return {
        "supplier": {
            "supplier_id": supplier["supplier_id"] if supplier else None,
            "name": supplier["name"] if supplier else None,
            "brands": [{"brand_id": r["brand_id"], "name": r["name"]} for r in brands],
        },
        "measures": [
            {"key": m.key, "label": m.label, "unit": m.unit,
             "description": m.description,
             "requires_line_level": not m.available_in(ROLLUP)}
            for m in MEASURES.values()
        ],
        "dimensions": [
            {"key": d.key, "label": d.label, "type": d.type,
             "requires_line_level": not d.available_in(ROLLUP)}
            for d in DIMENSIONS.values()
        ],
        "filters": {
            key: {**meta, **({"allowed_values": [r["region"] for r in regions]}
                             if key == "region" else {}),
                  **({"allowed_values": CHANNELS} if key == "channel" else {})}
            for key, meta in FILTER_FIELDS.items()
        },
        # Name plus centroid. The client's map projects whatever comes back and fits its own
        # bounds to it, so this works for counties, states, prefectures or nothing at all.
        "regions": [{"name": r["region"],
                     "lat": float(r["lat"]) if r["lat"] is not None else None,
                     "lon": float(r["lon"]) if r["lon"] is not None else None}
                    for r in regions],
        "categories": [
            {"category_id": r["category_id"], "name": r["name"],
             "level": r["level"], "parent_id": r["parent_id"]}
            for r in categories
        ],
        "time": {
            "coverage": {"from": coverage_from.isoformat(), "to": coverage_to.isoformat()},
            "relative_ranges": RELATIVE_RANGES,
            "relative_anchor": coverage_to.isoformat(),
            "note": "Relativa perioder räknas från sista datumet i datan, inte från dagens "
                    "datum. Det finns ingen data efter coverage.to.",
            "compare_to": ["previous_period", "same_period_last_year"],
            # The warehouse stores the campaign's id and its days, not its name - so this says
            # when a campaign ran, and never what it was called.
            "campaigns": [{"campaign_id": r["campaign_id"],
                           "from": r["starts"].isoformat(),
                           "to": r["ends"].isoformat()} for r in campaigns],
            "campaigns_note": "Kampanjperioder ur kalendern. Handlaren rabatterar tungt under "
                              "dessa dagar, vilket förklarar toppar som annars ser oförklarade "
                              "ut. Namnen finns inte i datan.",
        },
        "units": {
            "currency": settings.app_currency,
            "vat": settings.vat_code,
            "note": f"Alla belopp är i {settings.app_currency} "
                    f"{'inklusive' if settings.prices_include_vat else 'exklusive'} moms. "
                    f"Nettoförsäljning är efter rabatt och efter returer.",
        },
        "limits": {
            "max_rows": MAX_ROWS,
            "grain_floor": "Aggregerat från orderrad. Kunddata kan endast grupperas på "
                           "segment, ålderskategori eller lojalitetsnivå - aldrig på "
                           "enskild kund.",
        },
        "what_you_may_see_about_others": {
            "own_brands": "Full detalj: produkt × butik × dag.",
            "category_totals": "Endast aggregat, och endast via query_market_share.",
            "own_rank": "Ja, t.ex. '#2 av 7 varumärken i Hörlurar'.",
            "named_competitors": "Nej. Konkurrenters siffror är inte åtkomliga, inte "
                                 "filtrerade - de finns inte i objekten verktyget läser.",
            "k_anonymity": "Marknadsandelar utelämnas om urvalet innehåller färre än 5 "
                           "varumärken eller färre än 100 köp.",
        },
        "cannot_answer": [
            "Marginal, inköpspris och COGS - finns inte i datan som exponeras för "
            "leverantörer.",
            "Lagernivåer och prognoser.",
            "Enskilda kunder eller personuppgifter.",
            "Namngivna konkurrenters försäljning.",
            f"Perioder utanför {coverage_from.isoformat()}–{coverage_to.isoformat()}.",
        ],
    }
