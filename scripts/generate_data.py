"""Seeded synthetic Swedish retail data generator (IMPLEMENTATION_PLAN.md §5.1)."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from console import use_utf8_stdout
from reference_data import (
    AGE_BUCKETS,
    BRAND_SUBCATEGORIES,
    CAMPAIGNS,
    CATEGORIES,
    CUSTOMER_SEGMENTS,
    DEMO_SUPPLIER,
    FIXED_HOLIDAYS,
    LOYALTY_TIERS,
    MODEL_SUFFIXES,
    REGIONS,
    SEASONALITY,
    SUBCATEGORY_PROFILE,
    SUPPLIERS,
    THIN_SUBCATEGORY,
)

# Proportions of the generated world.
N_PHYSICAL_STORES = 60
N_CUSTOMERS = 40_000
DEFAULT_LINES = 800_000
DEFAULT_START = date(2024, 7, 1)
DEFAULT_END = date(2026, 6, 30)

# Unit volume falls off sharply with price: (price / median) ** PRICE_ELASTICITY.
PRICE_ELASTICITY = -0.85
DEMO_HOME_CATEGORY = "Ljud & Bild"   # where the demo supplier is meant to be strong
DEMO_HOME_BOOST = 2.4

RETURN_RATE = 0.015          # share of lines that come back as a negative mirror line
CASH_PURCHASE_RATE = 0.008   # share of lines with no customer_id at all
ONLINE_SHARE_START = 0.18    # channel mix drifts over the period
ONLINE_SHARE_END = 0.30
WEEKDAY_FACTOR = np.array([0.95, 0.92, 0.95, 1.00, 1.15, 1.25, 0.95])  # Mon..Sun


# --------------------------------------------------------------------- dimensions


def build_suppliers_and_brands() -> tuple[pd.DataFrame, pd.DataFrame]:
    suppliers, brands = [], []
    for supplier_id, (supplier_name, brand_names) in enumerate(SUPPLIERS.items(), start=1):
        suppliers.append({
            "supplier_id": supplier_id,
            "name": supplier_name,
            "org_nr": f"556{100 + supplier_id}-{4000 + supplier_id * 7}",
            "country": "SE",
        })
        for brand_name in brand_names:
            brands.append({
                "brand_id": len(brands) + 1,
                "supplier_id": supplier_id,
                "name": brand_name,
            })
    return pd.DataFrame(suppliers), pd.DataFrame(brands)


def build_categories() -> pd.DataFrame:
    rows = []
    # Level-1 rows first, so the single COPY in seed.py satisfies dim_category's self-
    # referencing foreign key as it goes.
    for top_name in CATEGORIES:
        rows.append({"category_id": len(rows) + 1, "parent_id": None,
                     "name": top_name, "level": 1})
    top_ids = {r["name"]: r["category_id"] for r in rows}
    for top_name, subs in CATEGORIES.items():
        for sub_name in subs:
            rows.append({"category_id": len(rows) + 1, "parent_id": top_ids[top_name],
                         "name": sub_name, "level": 2})
    frame = pd.DataFrame(rows)
    frame["parent_id"] = frame["parent_id"].astype("Int64")
    return frame


def build_products(rng: np.random.Generator, brands: pd.DataFrame,
                   categories: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    brand_id_by_name = dict(zip(brands["name"], brands["brand_id"], strict=True))
    sub = categories[categories["level"] == 2]
    category_id_by_name = dict(zip(sub["name"], sub["category_id"], strict=True))

    rows = []
    for sub_name, competing in BRAND_SUBCATEGORIES.items():
        noun, price_min, price_max = SUBCATEGORY_PROFILE[sub_name]
        n_products = int(rng.integers(14, 23))
        for i in range(n_products):
            brand_name = competing[i % len(competing)]
            suffix = MODEL_SUFFIXES[(i * 5 + len(sub_name)) % len(MODEL_SUFFIXES)]
            model = f"{brand_name[0]}{100 + (i * 13) % 900}"
            # Log-uniform across the band so cheap products dominate, then round to a Swedish
            # retail price ending in 9.
            price = float(np.exp(rng.uniform(np.log(price_min), np.log(price_max))))
            price = max(price_min, round(price / 10) * 10 - 1)

            # ~15 % of the range launches during the period rather than before it.
            if rng.random() < 0.15:
                launch = start + pd.Timedelta(days=int(rng.integers(30, 600)))
            else:
                launch = start - pd.Timedelta(days=int(rng.integers(30, 1200)))

            rows.append({
                "product_id": len(rows) + 1,
                "brand_id": brand_id_by_name[brand_name],
                "category_id": category_id_by_name[sub_name],
                "name": f"{brand_name} {noun} {model} {suffix}",
                "ean": f"73{len(rows) + 1:011d}",
                "list_price_sek": round(price, 2),
                "launch_date": pd.Timestamp(launch).date(),
                "discontinued_date": None,
            })

    products = pd.DataFrame(rows)

    # Exactly the mess §5.1 promises: a handful of products stop being sold partway through, one
    # of them belonging to the demo supplier so the truncated series is visible on the dashboard
    # we actually show.
    demo_brands = SUPPLIERS[DEMO_SUPPLIER]
    demo_brand_ids = [brand_id_by_name[b] for b in demo_brands]
    demo_candidates = products.index[products["brand_id"].isin(demo_brand_ids)].to_numpy()
    discontinued = [int(rng.choice(demo_candidates))]
    others = products.index[~products["brand_id"].isin(demo_brand_ids)].to_numpy()
    discontinued += [int(x) for x in rng.choice(others, size=3, replace=False)]

    span_days = (end - start).days
    for idx in discontinued:
        cutoff = start + pd.Timedelta(days=int(rng.integers(span_days // 3, span_days - 60)))
        products.loc[idx, "discontinued_date"] = pd.Timestamp(cutoff).date()

    return products


def build_stores(rng: np.random.Generator, start: date) -> pd.DataFrame:
    region_names = list(REGIONS)
    weights = np.array([REGIONS[r]["weight"] for r in region_names], dtype=float)

    # Every län gets at least one physical store; the rest are allocated by population.
    counts = np.ones(len(region_names), dtype=int)
    remaining = N_PHYSICAL_STORES - counts.sum()
    extra = rng.multinomial(remaining, weights / weights.sum())
    counts += extra

    rows = []
    for region, n in zip(region_names, counts, strict=True):
        cities = REGIONS[region]["cities"]
        for i in range(int(n)):
            city, municipality, lat, lon = cities[i % len(cities)]
            rows.append({
                "store_id": len(rows) + 1,
                "name": f"{city} {'Centrum' if i == 0 else f'Handelsplats {i + 1}'}",
                "channel": "fysisk",
                "city": city,
                "municipality": municipality,
                "region": region,
                "lat": lat + float(rng.normal(0, 0.01)),
                "lon": lon + float(rng.normal(0, 0.02)),
                "opened_date": start - pd.Timedelta(days=int(rng.integers(400, 4000))),
            })

    # One online pseudo-store per län.
    for region in region_names:
        rows.append({
            "store_id": len(rows) + 1,
            "name": f"Onlinebutik – {region}",
            "channel": "online",
            "city": REGIONS[region]["cities"][0][0],
            "municipality": REGIONS[region]["cities"][0][1],
            "region": region,
            "lat": None,
            "lon": None,
            "opened_date": start - pd.Timedelta(days=2000),
        })

    stores = pd.DataFrame(rows)
    stores["opened_date"] = pd.to_datetime(stores["opened_date"]).dt.date

    # One physical store opens mid-period, so at least one series legitimately starts late and a
    # naive year-over-year comparison on it would be wrong.
    physical = stores.index[stores["channel"] == "fysisk"].to_numpy()
    late = int(rng.choice(physical))
    stores.loc[late, "opened_date"] = start + pd.Timedelta(days=400)
    stores.loc[late, "name"] = stores.loc[late, "name"] + " (ny)"

    return stores


def build_customers(rng: np.random.Generator) -> pd.DataFrame:
    region_names = list(REGIONS)
    weights = np.array([REGIONS[r]["weight"] for r in region_names], dtype=float)
    weights /= weights.sum()

    idx = rng.choice(len(region_names), size=N_CUSTOMERS, p=weights)
    return pd.DataFrame({
        "customer_id": np.arange(1, N_CUSTOMERS + 1),
        "pseudonym_id": [f"cust_{i:07d}" for i in range(1, N_CUSTOMERS + 1)],
        "segment": rng.choice(CUSTOMER_SEGMENTS, size=N_CUSTOMERS, p=[0.72, 0.12, 0.09, 0.07]),
        "region": [region_names[i] for i in idx],
        "age_bucket": rng.choice(AGE_BUCKETS, size=N_CUSTOMERS,
                                 p=[0.13, 0.22, 0.21, 0.18, 0.14, 0.12]),
        "loyalty_tier": rng.choice(LOYALTY_TIERS, size=N_CUSTOMERS, p=[0.45, 0.28, 0.19, 0.08]),
    })


def build_dates(start: date, end: date) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    iso = days.isocalendar()

    campaign_ids = np.zeros(len(days), dtype=int)
    campaign_lookup: dict[tuple[str, int], int] = {}
    for name, month, day_from, day_to, _uplift in CAMPAIGNS:
        in_window = (days.month == month) & (days.day >= day_from) & (days.day <= day_to)
        for year in sorted({int(y) for y in days[in_window].year}):
            key = (name, year)
            campaign_lookup.setdefault(key, len(campaign_lookup) + 1)
            campaign_ids[in_window & (days.year == year)] = campaign_lookup[key]

    is_holiday = np.zeros(len(days), dtype=bool)
    for month, day in FIXED_HOLIDAYS:
        is_holiday |= (days.month == month) & (days.day == day)

    frame = pd.DataFrame({
        "date_id": days.strftime("%Y%m%d").astype(int),
        "date": days.date,
        "iso_year": iso["year"].to_numpy(),
        "iso_week": iso["week"].to_numpy(),
        "month": days.month,
        "quarter": days.quarter,
        "year": days.year,
        "weekday": days.weekday,
        "is_holiday": is_holiday,
        "campaign_id": np.where(campaign_ids == 0, None, campaign_ids),
    })
    frame["campaign_id"] = frame["campaign_id"].astype("Int64")
    return frame


# --------------------------------------------------------------------------- fact


def _daily_demand_weights(dates: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per level-1 category, a relative demand weight for every day in the period."""
    n = len(dates)
    day_index = np.arange(n)
    weekday = WEEKDAY_FACTOR[dates["weekday"].to_numpy()]

    # Underlying market growth over the two years, plus the campaign uplifts.
    trend = 1.0 + 0.14 * (day_index / max(n - 1, 1))
    campaign = np.ones(n)
    months = dates["month"].to_numpy()
    days_of_month = pd.to_datetime(dates["date"]).dt.day.to_numpy()
    for _name, month, day_from, day_to, uplift in CAMPAIGNS:
        window = (months == month) & (days_of_month >= day_from) & (days_of_month <= day_to)
        campaign[window] *= uplift

    weights = {}
    for top_name in CATEGORIES:
        monthly = np.array(SEASONALITY[top_name])[months - 1]
        weights[top_name] = monthly * weekday * trend * campaign
    return weights


def _brand_region_affinity(rng: np.random.Generator, brands: pd.DataFrame) -> np.ndarray:
    """brand_id → per-region multiplier. Some brands genuinely index better regionally."""
    n_regions = len(REGIONS)
    affinity = rng.lognormal(mean=0.0, sigma=0.22, size=(len(brands) + 1, n_regions))

    # A deliberate, checkable fact for the demo: the supplier we log in as is over-indexed in
    # Stockholm, so "vilka produkter säljer bäst i Stockholm?" has a real answer rather than
    # just mirroring the national ranking.
    region_names = list(REGIONS)
    sthlm = region_names.index("Stockholms län")
    gbg = region_names.index("Västra Götalands län")
    demo_brand_ids = brands.loc[brands["name"].isin(SUPPLIERS[DEMO_SUPPLIER]), "brand_id"]
    for brand_id in demo_brand_ids:
        affinity[brand_id, sthlm] *= 1.6
        affinity[brand_id, gbg] *= 1.15
    return affinity


def build_facts(rng: np.random.Generator, products: pd.DataFrame, brands: pd.DataFrame,
                categories: pd.DataFrame, stores: pd.DataFrame, customers: pd.DataFrame,
                dates: pd.DataFrame, n_lines: int) -> pd.DataFrame:
    n_days = len(dates)
    date_ids = dates["date_id"].to_numpy()
    day_dates = pd.to_datetime(dates["date"]).to_numpy()

    # Lookups
    supplier_by_brand = dict(zip(brands["brand_id"], brands["supplier_id"], strict=True))
    parent_of = dict(zip(categories["category_id"], categories["parent_id"], strict=True))
    name_of_category = dict(zip(categories["category_id"], categories["name"], strict=True))
    top_name_of_sub = {cid: name_of_category[parent_of[cid]]
                       for cid in categories.loc[categories["level"] == 2, "category_id"]}

    category_weights = _daily_demand_weights(dates)
    affinity = _brand_region_affinity(rng, brands)

    region_names = list(REGIONS)
    region_index = {name: i for i, name in enumerate(region_names)}
    region_pop = np.array([REGIONS[r]["weight"] for r in region_names], dtype=float)

    # Store pick tables: (region, channel) → store_ids and their relative pull.
    store_pick: dict[tuple[int, str], tuple[np.ndarray, np.ndarray]] = {}
    store_opened = dict(zip(stores["store_id"], pd.to_datetime(stores["opened_date"]),
                            strict=True))
    for (region, channel), group in stores.groupby(["region", "channel"]):
        ids = group["store_id"].to_numpy()
        pull = rng.lognormal(0.0, 0.3, size=len(ids))
        store_pick[(region_index[region], channel)] = (ids, pull / pull.sum())

    # Per-product share of total volume.
    popularity = rng.lognormal(mean=0.0, sigma=1.0, size=len(products))

    # Price elasticity.
    price = products["list_price_sek"].to_numpy(dtype=float)
    popularity *= (price / np.median(price)) ** PRICE_ELASTICITY

    # The supplier the demo logs in as is a real contender in its own home category, so the
    # market-share tile reads "#2 av 6" rather than "#5 av 6". A dashboard where the logged-in
    # brand is an also-ran makes for a poor five-minute demo.
    demo_brand_ids = set(brands.loc[brands["name"].isin(SUPPLIERS[DEMO_SUPPLIER]), "brand_id"])
    is_demo_home = np.array([
        p.brand_id in demo_brand_ids and top_name_of_sub[p.category_id] == DEMO_HOME_CATEGORY
        for p in products.itertuples(index=False)
    ])
    popularity[is_demo_home] *= DEMO_HOME_BOOST

    popularity /= popularity.sum()
    lines_per_product = rng.multinomial(n_lines, popularity)

    online_share = np.linspace(ONLINE_SHARE_START, ONLINE_SHARE_END, n_days)

    frames = []
    for pos, product in enumerate(products.itertuples(index=False)):
        n = int(lines_per_product[pos])
        if n == 0:
            continue

        # Active window: launched, not yet discontinued.
        launch = np.datetime64(product.launch_date)
        active = day_dates >= launch
        if product.discontinued_date is not None:
            active &= day_dates <= np.datetime64(product.discontinued_date)
        if not active.any():
            continue

        top_name = top_name_of_sub[product.category_id]
        weights = category_weights[top_name] * active
        total = weights.sum()
        if total <= 0:
            continue
        day_pos = rng.choice(n_days, size=n, p=weights / total)

        # Region: population × the brand's regional affinity.
        region_w = region_pop * affinity[product.brand_id]
        region_pos = rng.choice(len(region_names), size=n, p=region_w / region_w.sum())

        is_online = rng.random(n) < online_share[day_pos]
        store_ids = np.empty(n, dtype=np.int64)
        for r in np.unique(region_pos):
            for channel, mask in (("online", is_online), ("fysisk", ~is_online)):
                sel = (region_pos == r) & mask
                k = int(sel.sum())
                if k:
                    ids, pull = store_pick[(int(r), channel)]
                    store_ids[sel] = rng.choice(ids, size=k, p=pull)

        # A store cannot sell before it opened; move those lines to a sibling store in the same
        # region rather than dropping them, so regional totals stay intact.
        for store_id in np.unique(store_ids):
            opened = store_opened[store_id]
            too_early = (store_ids == store_id) & (day_dates[day_pos] < np.datetime64(opened))
            k = int(too_early.sum())
            if not k:
                continue
            for i in np.flatnonzero(too_early):
                channel = "online" if is_online[i] else "fysisk"
                ids, pull = store_pick[(int(region_pos[i]), channel)]
                alternatives = ids[ids != store_id]
                if len(alternatives) == 0:
                    continue
                alt_pull = pull[ids != store_id]
                store_ids[i] = rng.choice(alternatives, p=alt_pull / alt_pull.sum())

        quantity = 1 + rng.poisson(0.30, size=n)

        # Prices drift over the period - electronics deflate, most other things creep up.
        drift = rng.normal(-0.02, 0.05)
        price_factor = 1.0 + drift * (day_pos / max(n_days - 1, 1))
        unit_price = product.list_price_sek * price_factor

        # Discounts: heavy during campaigns, sporadic otherwise.
        campaign_day = dates["campaign_id"].notna().to_numpy()[day_pos]
        discount_pct = np.where(
            campaign_day,
            rng.uniform(0.10, 0.35, size=n),
            np.where(rng.random(n) < 0.08, rng.uniform(0.05, 0.20, size=n), 0.0),
        )

        gross = np.round(quantity * unit_price, 2)
        discount = np.round(gross * discount_pct, 2)

        frames.append(pd.DataFrame({
            "date_id": date_ids[day_pos],
            "store_id": store_ids,
            "product_id": product.product_id,
            "supplier_id": supplier_by_brand[product.brand_id],
            "quantity": quantity,
            "gross_amount_sek": gross,
            "discount_amount_sek": discount,
            "net_amount_sek": np.round(gross - discount, 2),
            "is_return": False,
        }))

    facts = pd.concat(frames, ignore_index=True)

    # Order matters: baskets are formed first, then a customer is attached to the whole basket.
    facts = _append_returns(rng, facts, dates)
    facts = _assign_orders(rng, facts)
    facts = _attach_customers(rng, facts, stores, customers)

    facts.insert(0, "sale_line_id", np.arange(1, len(facts) + 1))
    return facts


def _attach_customers(rng: np.random.Generator, facts: pd.DataFrame, stores: pd.DataFrame,
                      customers: pd.DataFrame) -> pd.DataFrame:
    """One customer per order, shopping in the store's own region."""
    region_of_store = dict(zip(stores["store_id"], stores["region"], strict=True))
    order_id = facts["order_id"].to_numpy()

    # order_id is non-decreasing here (factorised over rows already sorted into baskets), so the
    # first row of each order is where the value changes.
    first = np.flatnonzero(np.diff(order_id, prepend=order_id[0] - 1) != 0)
    lines_per_order = np.diff(np.append(first, len(order_id)))
    order_region = pd.Series(facts["store_id"].to_numpy()[first]).map(region_of_store)

    per_order = np.full(len(first), -1, dtype=np.int64)
    for region, group in customers.groupby("region"):
        pool = group["customer_id"].to_numpy()
        sel = (order_region == region).to_numpy()
        k = int(sel.sum())
        if k:
            per_order[sel] = rng.choice(pool, size=k)

    per_order[rng.random(len(first)) < CASH_PURCHASE_RATE] = -1
    customer_ids = np.repeat(per_order, lines_per_order)
    facts["customer_id"] = pd.Series(customer_ids).replace(-1, pd.NA).astype("Int64")
    return facts


def _append_returns(rng: np.random.Generator, facts: pd.DataFrame,
                    dates: pd.DataFrame) -> pd.DataFrame:
    """Returns are mirror lines with negative amounts, a few days after the sale."""
    returned = rng.random(len(facts)) < RETURN_RATE
    mirror = facts[returned].copy()
    if mirror.empty:
        return facts

    date_ids = dates["date_id"].to_numpy()
    position = pd.Series(np.arange(len(date_ids)), index=date_ids)
    shifted = position.loc[mirror["date_id"]].to_numpy() + rng.integers(3, 21, size=len(mirror))

    # A return whose lag falls past the end of coverage has not happened yet, so it is dropped
    # rather than clamped onto the final day.
    within_coverage = shifted < len(date_ids)
    mirror = mirror[within_coverage]
    if mirror.empty:
        return facts
    mirror["date_id"] = date_ids[shifted[within_coverage]]

    for column in ("quantity", "gross_amount_sek", "discount_amount_sek", "net_amount_sek"):
        mirror[column] = -mirror[column]
    mirror["is_return"] = True

    return pd.concat([facts, mirror], ignore_index=True)


def _assign_orders(rng: np.random.Generator, facts: pd.DataFrame) -> pd.DataFrame:
    """Chunk the lines sold at one store on one day into baskets of 1–3 lines."""
    # Lines arrive grouped by product (one frame per product), so shuffle before chunking or
    # every basket would contain the same product repeatedly.
    facts = facts.iloc[rng.permutation(len(facts))].reset_index(drop=True)
    facts = facts.sort_values(["date_id", "store_id"], kind="stable").reset_index(drop=True)

    group = facts.groupby(["date_id", "store_id"], sort=False)
    within = group.cumcount().to_numpy()
    group_id = group.ngroup().to_numpy()

    basket_size = rng.choice([1, 1, 1, 2, 2, 3], size=group_id.max() + 1)
    order_key = group_id.astype(np.int64) * (within.max() + 1) + within // basket_size[group_id]
    facts["order_id"] = pd.factorize(order_key)[0] + 1
    return facts


# ------------------------------------------------------------------ ground truth


def build_ground_truth(facts: pd.DataFrame, products: pd.DataFrame, brands: pd.DataFrame,
                       suppliers: pd.DataFrame, categories: pd.DataFrame,
                       stores: pd.DataFrame, dates: pd.DataFrame) -> dict:
    """Independently recompute the answers the eval suite will hold the system to."""
    df = (facts
          .merge(dates[["date_id", "date", "month", "year"]], on="date_id")
          .merge(products[["product_id", "brand_id", "category_id", "name"]], on="product_id")
          .merge(brands[["brand_id", "name"]], on="brand_id", suffixes=("_product", "_brand"))
          .merge(stores[["store_id", "region", "channel"]], on="store_id"))
    df["month_start"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()

    sub = categories[categories["level"] == 2]
    subcategory_name = dict(zip(sub["category_id"], sub["name"], strict=True))
    supplier_name = dict(zip(suppliers["supplier_id"], suppliers["name"], strict=True))

    def money(series: pd.Series) -> float:
        return float(round(series.sum(), 2))

    per_supplier = {}
    for supplier_id, group in df.groupby("supplier_id"):
        monthly = (group.groupby("month_start")["net_amount_sek"].sum().round(2))
        per_region = (group.groupby("region")["net_amount_sek"].sum().round(2)
                      .sort_values(ascending=False))
        top_products = (group.groupby("name_product")
                        .agg(net_sales_sek=("net_amount_sek", "sum"),
                             units=("quantity", "sum"))
                        .round(2).sort_values("net_sales_sek", ascending=False).head(10))
        sthlm = group[group["region"] == "Stockholms län"]
        top_sthlm = (sthlm.groupby("name_product")["net_amount_sek"].sum()
                     .round(2).sort_values(ascending=False).head(10))

        per_supplier[supplier_name[supplier_id]] = {
            "net_sales_sek": money(group["net_amount_sek"]),
            "gross_sales_sek": money(group["gross_amount_sek"]),
            "units": int(group["quantity"].sum()),
            "order_lines": int(len(group)),
            "orders": int(group["order_id"].nunique()),
            "net_sales_by_month": {str(k.date()): float(v) for k, v in monthly.items()},
            "net_sales_by_region": {k: float(v) for k, v in per_region.items()},
            "top_10_products_by_net_sales": [
                {"product": name, "net_sales_sek": float(row.net_sales_sek),
                 "units": int(row.units)}
                for name, row in top_products.iterrows()
            ],
            "top_10_products_stockholm_by_net_sales": [
                {"product": name, "net_sales_sek": float(value)}
                for name, value in top_sthlm.items()
            ],
        }

    # Market share per brand × subcategory × month, plus the peer count the k-anonymity guard
    # tests against.
    by_brand = (df.groupby(["month_start", "category_id", "name_brand"])["net_amount_sek"]
                .sum().round(2).reset_index())
    totals = (by_brand.groupby(["month_start", "category_id"])
              .agg(category_net_sek=("net_amount_sek", "sum"),
                   n_brands=("name_brand", "nunique")).reset_index())
    by_brand = by_brand.merge(totals, on=["month_start", "category_id"])
    by_brand["share_pct"] = (100 * by_brand["net_amount_sek"]
                             / by_brand["category_net_sek"]).round(2)
    by_brand["rank"] = (by_brand.groupby(["month_start", "category_id"])["net_amount_sek"]
                        .rank(ascending=False, method="min").astype(int))

    demo_brands = set(SUPPLIERS[DEMO_SUPPLIER])
    demo_share = by_brand[by_brand["name_brand"].isin(demo_brands)]
    market_share = [
        {"month": str(row.month_start.date()),
         "subcategory": subcategory_name[row.category_id],
         "brand": row.name_brand,
         "net_sales_sek": float(row.net_amount_sek),
         "category_net_sek": float(row.category_net_sek),
         "share_pct": float(row.share_pct),
         "rank": int(row.rank),
         "n_brands": int(row.n_brands)}
        for row in demo_share.itertuples(index=False)
    ]

    brands_per_subcategory = (df.groupby("category_id")["name_brand"].nunique()
                              .rename(subcategory_name).sort_values())

    return {
        "seed_contract": "regenerate with: python scripts/generate_data.py --seed 42",
        "coverage": {"from": str(df["date"].min()), "to": str(df["date"].max())},
        "totals": {
            "order_lines": int(len(df)),
            "orders": int(df["order_id"].nunique()),
            "net_sales_sek": money(df["net_amount_sek"]),
            "units": int(df["quantity"].sum()),
            "returned_lines": int(df["is_return"].sum()),
            "lines_without_customer": int(df["customer_id"].isna().sum()),
            "products": int(len(products)),
            "stores": int(len(stores)),
            "suppliers": int(len(suppliers)),
            "brands": int(len(brands)),
        },
        "demo_supplier": DEMO_SUPPLIER,
        "per_supplier": per_supplier,
        "demo_supplier_market_share": market_share,
        "brands_per_subcategory": {k: int(v) for k, v in brands_per_subcategory.items()},
        "k_anonymity": {
            "min_brands": 5,
            "min_transactions": 100,
            "thin_subcategory": THIN_SUBCATEGORY,
            "subcategories_below_threshold": [
                k for k, v in brands_per_subcategory.items() if v < 5
            ],
        },
    }


# --------------------------------------------------------------------------- main


def reconcile(facts: pd.DataFrame, ground_truth: dict) -> None:
    """Assert the oracle and the emitted rows agree before either is trusted."""
    totals = ground_truth["totals"]
    assert len(facts) == totals["order_lines"], "line count mismatch"

    net = round(float(facts["net_amount_sek"].sum()), 2)
    assert abs(net - totals["net_sales_sek"]) < 0.01, f"net mismatch: {net}"

    per_supplier_net = round(
        sum(s["net_sales_sek"] for s in ground_truth["per_supplier"].values()), 2)
    assert abs(per_supplier_net - totals["net_sales_sek"]) < 1.0, "supplier split mismatch"

    assert totals["returned_lines"] > 0, "no returns generated"
    assert totals["lines_without_customer"] > 0, "no cash purchases generated"
    assert ground_truth["k_anonymity"]["subcategories_below_threshold"], \
        "k-anonymity path would never fire - the thin subcategory is not thin"


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lines", type=int, default=DEFAULT_LINES)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data" / "generated")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"generating with seed={args.seed}, {args.start} → {args.end}")
    suppliers, brands = build_suppliers_and_brands()
    categories = build_categories()
    products = build_products(rng, brands, categories, args.start, args.end)
    stores = build_stores(rng, args.start)
    customers = build_customers(rng)
    dates = build_dates(args.start, args.end)
    print(f"  dims: {len(suppliers)} suppliers, {len(brands)} brands, "
          f"{len(products)} products, {len(stores)} stores, {len(dates)} days")

    facts = build_facts(rng, products, brands, categories, stores, customers,
                        dates, args.lines)
    print(f"  facts: {len(facts):,} order lines, {facts['order_id'].nunique():,} orders")

    ground_truth = build_ground_truth(facts, products, brands, suppliers, categories,
                                      stores, dates)
    reconcile(facts, ground_truth)
    print("  reconciled: oracle agrees with the emitted rows")

    columns = ["sale_line_id", "order_id", "date_id", "store_id", "customer_id",
               "product_id", "supplier_id", "quantity", "gross_amount_sek",
               "discount_amount_sek", "net_amount_sek", "is_return"]
    for name, frame in [("dim_supplier", suppliers), ("dim_brand", brands),
                        ("dim_category", categories), ("dim_product", products),
                        ("dim_store", stores), ("dim_customer", customers),
                        ("dim_date", dates), ("fact_sales_line", facts[columns])]:
        path = args.out / f"{name}.csv"
        frame.to_csv(path, index=False)
        print(f"  wrote {path.name}: {len(frame):,} rows")

    (args.out / "ground_truth.json").write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote ground_truth.json ({len(ground_truth['per_supplier'])} suppliers)")


if __name__ == "__main__":
    main()
