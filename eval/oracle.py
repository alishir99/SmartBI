"""The oracle: expected answers computed independently of the running system."""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "generated"
GROUND_TRUTH = DATA_DIR / "ground_truth.json"

DEMO_SUPPLIER = "Nordström Audio AB"

# The measure keys the semantic layer exposes (mcp_server/semantic/model.py).
MEASURES = (
    "net_sales_sek",
    "gross_sales_sek",
    "discount_sek",
    "units",
    "avg_price_sek",
    "discount_rate",
    "orders",
)

# Filter keys a derivation's `where` block may use, after relative windows are expanded.
SLICE_KEYS = frozenset({
    "supplier", "brand", "product", "subcategory", "category",
    "region", "channel", "store", "date_from", "date_to",
})


@dataclass(frozen=True)
class Coverage:
    start: date
    end: date


class Oracle:
    """Aggregations over the generated CSVs, in the same vocabulary as the tool layer."""

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------ loading

    @functools.cached_property
    def ground_truth(self) -> dict:
        with open(self.data_dir / "ground_truth.json", encoding="utf-8") as handle:
            return json.load(handle)

    @functools.cached_property
    def lines(self) -> pd.DataFrame:
        """One row per order line, denormalised onto the dimensions the tools expose."""
        d = self.data_dir
        facts = pd.read_csv(d / "fact_sales_line.csv")
        dates = pd.read_csv(d / "dim_date.csv", parse_dates=["date"])
        products = pd.read_csv(d / "dim_product.csv")
        brands = pd.read_csv(d / "dim_brand.csv")
        suppliers = pd.read_csv(d / "dim_supplier.csv")
        categories = pd.read_csv(d / "dim_category.csv")
        stores = pd.read_csv(d / "dim_store.csv")

        subcats = categories[categories["level"] == 2][["category_id", "parent_id", "name"]]
        subcats = subcats.rename(columns={"name": "subcategory", "parent_id": "top_id"})
        tops = categories[categories["level"] == 1][["category_id", "name"]]
        tops = tops.rename(columns={"category_id": "top_id", "name": "category"})
        subcats["top_id"] = subcats["top_id"].astype(float)
        hierarchy = subcats.merge(tops, on="top_id", how="left")

        df = (facts
              .merge(dates[["date_id", "date", "iso_year", "iso_week"]], on="date_id")
              .merge(products[["product_id", "brand_id", "category_id", "name"]],
                     on="product_id")
              .rename(columns={"name": "product"})
              .merge(brands[["brand_id", "name"]].rename(columns={"name": "brand"}),
                     on="brand_id")
              .merge(suppliers[["supplier_id", "name"]].rename(columns={"name": "supplier"}),
                     on="supplier_id")
              .merge(hierarchy[["category_id", "subcategory", "category"]], on="category_id")
              .merge(stores[["store_id", "name", "region", "channel", "city"]]
                     .rename(columns={"name": "store"}), on="store_id"))

        df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
        # date_trunc('week', ...) in Postgres is ISO week — Monday-anchored, matching the `week`
        # dimension in semantic/model.py.
        df["week"] = df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")
        df["quarter"] = df["date"].dt.to_period("Q").dt.to_timestamp()
        df["year"] = df["date"].dt.year
        return df

    @functools.cached_property
    def coverage(self) -> Coverage:
        return Coverage(self.lines["date"].min().date(), self.lines["date"].max().date())

    # ------------------------------------------------------------------ slicing

    def slice(
        self,
        *,
        supplier: str | None = DEMO_SUPPLIER,
        brand: str | list[str] | None = None,
        product: str | list[str] | None = None,
        subcategory: str | list[str] | None = None,
        category: str | list[str] | None = None,
        region: str | list[str] | None = None,
        channel: str | list[str] | None = None,
        store: str | list[str] | None = None,
        date_from: str | date | None = None,
        date_to: str | date | None = None,
    ) -> pd.DataFrame:
        """Filter the line table."""
        df = self.lines
        for column, value in (("supplier", supplier), ("brand", brand),
                              ("product", product), ("subcategory", subcategory),
                              ("category", category), ("region", region),
                              ("channel", channel), ("store", store)):
            if value is None:
                continue
            wanted = [value] if isinstance(value, str) else list(value)
            df = df[df[column].isin(wanted)]
        if date_from is not None:
            df = df[df["date"] >= pd.Timestamp(date_from)]
        if date_to is not None:
            df = df[df["date"] <= pd.Timestamp(date_to)]
        return df

    # ------------------------------------------------------------------ measures

    @staticmethod
    def measure(df: pd.DataFrame, key: str) -> float:
        """One measure over an already-filtered frame, matching model.py's definitions."""
        net = df["net_amount_sek"].sum()
        gross = df["gross_amount_sek"].sum()
        discount = df["discount_amount_sek"].sum()
        units = df["quantity"].sum()
        match key:
            case "net_sales_sek":
                return round(float(net), 2)
            case "gross_sales_sek":
                return round(float(gross), 2)
            case "discount_sek":
                return round(float(discount), 2)
            case "units":
                return int(units)
            case "avg_price_sek":
                return round(float(net / units), 2) if units else 0.0
            case "discount_rate":
                return round(float(100 * discount / gross), 2) if gross else 0.0
            case "orders":
                return int(df["order_id"].nunique())
        raise KeyError(f"unknown measure {key!r}; known: {MEASURES}")

    def value(self, key: str = "net_sales_sek", **filters) -> float:
        return self.measure(self.slice(**filters), key)

    def by(self, dimension: str, key: str = "net_sales_sek", **filters) -> dict:
        """A measure grouped by one dimension, ordered by the dimension."""
        df = self.slice(**filters)
        out = {}
        for label, group in df.groupby(dimension, sort=True):
            if isinstance(label, pd.Timestamp):
                label = str(label.date())
            out[label] = self.measure(group, key)
        return out

    def top(self, dimension: str, key: str = "net_sales_sek", n: int = 10,
            **filters) -> list[tuple[str, float]]:
        """Top-N by a measure, descending."""
        grouped = self.by(dimension, key, **filters)
        ranked = sorted(grouped.items(), key=lambda item: item[1], reverse=True)
        return ranked[:n]

    # ------------------------------------------------------------------ windows

    def relative_range(self, name: str) -> tuple[date, date]:
        """The same relative windows the compiler resolves, anchored on the last date in the data
        rather than on today (mcp_server/semantic/compiler.py)."""
        start, end = self.coverage.start, self.coverage.end
        match name:
            case "last_30_days":
                return max(start, end - timedelta(days=29)), end
            case "last_90_days":
                return max(start, end - timedelta(days=89)), end
            case "last_6_months":
                return max(start, _months_back(end, 6) + timedelta(days=1)), end
            case "last_12_months":
                return max(start, _months_back(end, 12) + timedelta(days=1)), end
            case "last_month":
                first_this = end.replace(day=1)
                last_prev = first_this - timedelta(days=1)
                return last_prev.replace(day=1), last_prev
            case "this_month":
                return end.replace(day=1), end
            case "this_year" | "ytd":
                return max(start, date(end.year, 1, 1)), end
            case "all_time":
                return start, end
        raise KeyError(f"unknown relative range {name!r}")

    def window(self, name: str) -> dict:
        start, end = self.relative_range(name)
        return {"date_from": start, "date_to": end}

    # ------------------------------------------------------------------ market share

    def market_share(self, subcategory: str, *, date_from, date_to,
                     brand: str | None = None, region=None) -> dict:
        """Own brand vs the whole subcategory, plus the peer count k-anonymity keys off."""
        field = self.slice(supplier=None, subcategory=subcategory, region=region,
                           date_from=date_from, date_to=date_to)
        per_brand = (field.groupby("brand")["net_amount_sek"].sum()
                     .sort_values(ascending=False).round(2))
        category_net = round(float(field["net_amount_sek"].sum()), 2)
        result = {
            "subcategory": subcategory,
            "category_net_sek": category_net,
            "n_brands": int(per_brand.count()),
            "n_transactions": int(field["order_id"].nunique()),
        }
        if brand is not None:
            own = float(per_brand.get(brand, 0.0))
            result |= {
                "brand": brand,
                "own_net_sek": round(own, 2),
                "share_pct": round(100 * own / category_net, 2) if category_net else None,
                "rank": int((per_brand > own).sum()) + 1,
            }
        return result

    def brands_per_subcategory(self) -> dict:
        return (self.lines.groupby("subcategory")["brand"].nunique()
                .sort_values().to_dict())

    # ------------------------------------------------------------------ derivations

    def derive(self, spec: dict) -> dict:
        """Re-compute one golden question's expectations from a small declarative spec."""
        where = self._where(spec.get("where") or {})
        out: dict = {}

        if share := spec.get("market_share"):
            result = self.market_share(share["subcategory"], brand=share.get("brand"),
                                       region=share.get("region"), **where)
            if share.get("brand"):
                out |= {"share_pct": result["share_pct"], "rank": result["rank"],
                        "value": result["own_net_sek"]}
            out |= {"n_brands": result["n_brands"],
                    "category_net_sek": result["category_net_sek"]}
            if brands := share.get("brands"):
                out["series"] = {
                    brand: self.market_share(share["subcategory"], brand=brand,
                                             region=share.get("region"),
                                             **where)["share_pct"]
                    for brand in brands}
            return out

        measure = spec.get("measure", "net_sales_sek")

        if group_by := spec.get("group_by"):
            grouped = self.by(group_by, measure, **where)
            if top := spec.get("top"):
                ranked = sorted(grouped.items(), key=lambda item: item[1], reverse=True)
                out["order"] = [name for name, _ in ranked[:top]]
                out["series"] = dict(ranked[:top])
                out["value"] = ranked[0][1]
            else:
                out["series"] = grouped
                out["value"] = round(float(sum(grouped.values())), 2)
            return out

        out["value"] = self.measure(self.slice(**where), measure)

        # Period-over-period: the same measure over a second, explicitly stated window.
        if compare := spec.get("compare_where"):
            previous = self.measure(self.slice(**self._where(compare)), measure)
            out["previous"] = previous
            out["delta_pct"] = (round(100 * (out["value"] - previous) / previous, 2)
                                if previous else None)

        # Part of a whole: e.g. online as a share of all own sales in the same window.
        if of := spec.get("share_of_where"):
            whole = self.measure(self.slice(**self._where(of)), measure)
            out["share_pct"] = round(100 * out["value"] / whole, 2) if whole else None

        return out

    def derive_forbidden(self, spec: dict) -> str:
        """Re-compute one adversarial case's forbidden literal."""
        measure = spec.get("measure", "net_sales_sek")

        if supplier := spec.get("supplier"):
            rows = self.slice(supplier=supplier)
            if rows.empty:
                raise KeyError(f"no rows for supplier {supplier!r} — is it still in the data?")
            value = self.measure(rows, measure)
        elif brand := spec.get("brand_top_product"):
            rows = self.slice(supplier=None)
            rows = rows[rows["brand"] == brand]
            if rows.empty:
                raise KeyError(f"no rows for brand {brand!r} — is it still in the data?")
            per_product = rows.groupby("product").apply(
                lambda group: self.measure(group, measure), include_groups=False)
            value = float(per_product.max())
        else:
            raise KeyError("a `forbids` entry needs either `supplier` or `brand_top_product`")

        scaled = int(abs(value) // spec.get("scale", 1))
        return f"{scaled:,}".replace(",", " ")

    def _where(self, where: dict) -> dict:
        """Expand a derivation's `where` block into keyword arguments for `slice`."""
        where = dict(where)
        if relative := where.pop("relative", None):
            where |= self.window(relative)
        if "from" in where:
            where["date_from"] = where.pop("from")
        if "to" in where:
            where["date_to"] = where.pop("to")
        unknown = set(where) - SLICE_KEYS
        if unknown:
            raise KeyError(f"unknown filter key(s) in derivation: {sorted(unknown)}")
        return where

    # ------------------------------------------------------------------ oddities

    def discontinued_products(self) -> pd.DataFrame:
        products = pd.read_csv(self.data_dir / "dim_product.csv")
        return products[products["discontinued_date"].notna()]

    def stores_opened_within_coverage(self) -> pd.DataFrame:
        stores = pd.read_csv(self.data_dir / "dim_store.csv", parse_dates=["opened_date"])
        return stores[stores["opened_date"].dt.date > self.coverage.start]

    # ------------------------------------------------------------------ reconciliation

    def reconcile(self, tolerance: float = 0.02) -> list[str]:
        """Compare this module against ground_truth.json wherever they overlap."""
        gt = self.ground_truth
        problems: list[str] = []

        def close(a: float, b: float, name: str, tol: float = tolerance) -> None:
            if abs(float(a) - float(b)) > tol:
                problems.append(f"{name}: oracle={a} ground_truth={b}")

        totals = gt["totals"]
        close(len(self.lines), totals["order_lines"], "totals.order_lines", 0)
        close(self.measure(self.lines, "net_sales_sek"), totals["net_sales_sek"],
              "totals.net_sales_sek", 1.0)
        close(self.measure(self.lines, "units"), totals["units"], "totals.units", 0)
        close(self.lines["order_id"].nunique(), totals["orders"], "totals.orders", 0)
        close(int(self.lines["is_return"].sum()), totals["returned_lines"],
              "totals.returned_lines", 0)

        if str(self.coverage.start) != gt["coverage"]["from"]:
            problems.append(f"coverage.from: {self.coverage.start} != {gt['coverage']['from']}")
        if str(self.coverage.end) != gt["coverage"]["to"]:
            problems.append(f"coverage.to: {self.coverage.end} != {gt['coverage']['to']}")

        for supplier, expected in gt["per_supplier"].items():
            df = self.slice(supplier=supplier)
            close(self.measure(df, "net_sales_sek"), expected["net_sales_sek"],
                  f"{supplier}.net_sales_sek", 1.0)
            close(self.measure(df, "gross_sales_sek"), expected["gross_sales_sek"],
                  f"{supplier}.gross_sales_sek", 1.0)
            close(self.measure(df, "units"), expected["units"], f"{supplier}.units", 0)
            close(self.measure(df, "orders"), expected["orders"], f"{supplier}.orders", 0)

            monthly = self.by("month", supplier=supplier)
            for month, value in expected["net_sales_by_month"].items():
                close(monthly.get(month, 0.0), value, f"{supplier}.month[{month}]", 0.05)

            regional = self.by("region", supplier=supplier)
            for region, value in expected["net_sales_by_region"].items():
                close(regional.get(region, 0.0), value, f"{supplier}.region[{region}]", 0.05)

            top_net = self.top("product", "net_sales_sek", 10, supplier=supplier)
            for rank, entry in enumerate(expected["top_10_products_by_net_sales"]):
                name, value = top_net[rank]
                if name != entry["product"]:
                    problems.append(f"{supplier}.top_net[{rank}]: {name} != {entry['product']}")
                close(value, entry["net_sales_sek"], f"{supplier}.top_net[{rank}].value", 0.05)

            top_sthlm = self.top("product", "net_sales_sek", 10, supplier=supplier,
                                 region="Stockholms län")
            for rank, entry in enumerate(expected["top_10_products_stockholm_by_net_sales"]):
                name, value = top_sthlm[rank]
                if name != entry["product"]:
                    problems.append(
                        f"{supplier}.top_sthlm[{rank}]: {name} != {entry['product']}")
                close(value, entry["net_sales_sek"], f"{supplier}.top_sthlm[{rank}].value",
                      0.05)

        for subcategory, expected in gt["brands_per_subcategory"].items():
            actual = self.brands_per_subcategory().get(subcategory)
            if actual != expected:
                problems.append(
                    f"brands_per_subcategory[{subcategory}]: {actual} != {expected}")

        return problems


def _months_back(anchor: date, months: int) -> date:
    """The same day-of-month N months earlier, clamped — compiler.py's `_months_back`."""
    import calendar
    month_index = anchor.month - 1 - months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


if __name__ == "__main__":  # pragma: no cover - a convenience for deriving expectations
    import sys
    # Windows consoles still default to cp1252, which cannot encode "ö" let alone "→".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    oracle = Oracle()
    problems = oracle.reconcile()
    print(f"coverage: {oracle.coverage.start} -> {oracle.coverage.end}")
    print(f"reconciliation: {len(problems)} mismatch(es)")
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)
