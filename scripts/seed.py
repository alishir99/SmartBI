"""Load the generated CSVs into Postgres, then build everything derived from them."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from console import use_utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "generated"

# Load order matters: dim_category has a self-referencing foreign key and the generator emits
# every level-1 row before any level-2 row, so a single COPY satisfies it.
TABLES = [
    "dim_supplier",
    "dim_brand",
    "dim_category",
    "dim_product",
    "dim_store",
    "dim_customer",
    "dim_date",
    "fact_sales_line",
]

DEMO_PASSWORD = "demo1234"

# One user per supplier for the first two suppliers: the second exists so tenant isolation can
# be *shown* live rather than asserted - log in as Erik and the same question returns a
# different company's numbers.
DEMO_USERS = [
    ("anna@nordstromaudio.se", "Anna Lindqvist", "Nordström Audio AB", "supplier_admin"),
    ("erik@lagerkvisthem.se", "Erik Sandberg", "Lagerkvist Hem AB", "supplier_viewer"),
]

# Curated synonyms so lexical retrieval alone handles how Swedes actually type.
REGION_SYNONYMS = {
    "Stockholms län": "stockholm sthlm sthlms huvudstaden stockholmsområdet",
    "Västra Götalands län": "göteborg gbg goteborg västra götaland vgr borås",
    "Skåne län": "skåne skane malmö malmo lund helsingborg öresund",
    "Uppsala län": "uppsala",
    "Östergötlands län": "östergötland linköping norrköping",
    "Jönköpings län": "jönköping jonkoping småland",
    "Hallands län": "halland halmstad varberg",
    "Örebro län": "örebro orebro",
    "Södermanlands län": "södermanland sörmland eskilstuna nyköping",
    "Dalarnas län": "dalarna falun borlänge",
    "Gävleborgs län": "gävleborg gävle gavle sandviken",
    "Värmlands län": "värmland karlstad",
    "Västmanlands län": "västmanland västerås vasteras",
    "Västerbottens län": "västerbotten umeå umea skellefteå norrland",
    "Norrbottens län": "norrbotten luleå lulea piteå norrland",
    "Kalmar län": "kalmar västervik öland",
    "Västernorrlands län": "västernorrland sundsvall örnsköldsvik norrland",
    "Kronobergs län": "kronoberg växjö vaxjo småland",
    "Blekinge län": "blekinge karlskrona",
    "Jämtlands län": "jämtland östersund norrland",
    "Gotlands län": "gotland visby",
}

CATEGORY_SYNONYMS = {
    "Hörlurar": "lurar headset trådlösa lurar öronsnäckor hörselkåpor in-ear",
    "Högtalare": "speakers ljud bluetooth-högtalare soundbar",
    "TV": "television tv-apparater platt-tv skärm",
    "Ljudanläggningar": "stereo hifi ljudsystem receiver förstärkare",
    "Bilstereo": "bilradio billjud carplay",
    "Kaffebryggare": "kaffemaskin espresso bryggare kaffe",
    "Köksmaskiner": "matberedare mixer stavmixer köksassistent",
    "Dammsugare": "robotdammsugare skaftdammsugare städ",
    "Belysning": "lampor lampa ljus led glödlampor",
    "Bärbara datorer": "laptop laptops dator datorer ultrabook",
    "Mobiltelefoner": "mobil mobiler telefon telefoner smartphone",
    "Surfplattor": "tablet tablets ipad platta",
    "Datortillbehör": "tillbehör mus tangentbord kablar dockor",
    "Träningsutrustning": "gym träning hantlar löpband styrketräning",
    "Cyklar": "cykel elcykel mountainbike",
    "Utomhusliv": "friluft camping tält vandring outdoor",
    "Vintersport": "skidor slalom snowboard vinter pjäxor",
    "Hårvård": "schampo balsam hår hårprodukter",
    "Personvård": "hygien rakning tandvård kroppsvård",
    "Byggleksaker": "byggsatser klossar bygglek",
    "Sällskapsspel": "brädspel spel kortspel familjespel",
    "Babyprodukter": "baby bebis barnvagn blöjor småbarn",
    "Ljud & Bild": "ljud bild hemelektronik audio video",
    "Hem & Kök": "hem kök hushåll vitvaror",
    "Dator & Mobil": "dator mobil it elektronik",
    "Sport & Fritid": "sport fritid träning outdoor",
    "Skönhet & Hälsa": "skönhet hälsa hygien beauty",
    "Barn & Leksaker": "barn leksaker lek",
}


def dsn() -> str:
    user = os.getenv("POSTGRES_USER", "solvigo")
    password = os.getenv("POSTGRES_PASSWORD", "solvigo")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "solvigo")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


async def connect(retries: int = 30) -> asyncpg.Connection:
    """Wait for Postgres."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return await asyncpg.connect(dsn())
        except (OSError, asyncpg.PostgresError) as exc:
            last = exc
            await asyncio.sleep(1)
            if attempt % 5 == 4:
                print(f"  waiting for postgres… ({attempt + 1}s)")
    raise SystemExit(f"could not reach postgres: {last}")


async def load_tables(connection: asyncpg.Connection) -> None:
    for table in TABLES:
        path = DATA / f"{table}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path}. Run: python scripts/generate_data.py --seed 42")
        # null='' because pandas writes an empty field for NULL, and those are meaningful here:
        # cash purchases have no customer, online stores have no coordinates, current products
        # have no discontinued date.
        await connection.copy_to_table(
            table, source=str(path), format="csv", header=True, null="")
        count = await connection.fetchval(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {count:,} rows")

    # The CSVs carry explicit sale_line_id values, which leaves the BIGSERIAL sequence at 1.
    await connection.execute(
        "SELECT setval(pg_get_serial_sequence('fact_sales_line', 'sale_line_id'), "
        "COALESCE((SELECT MAX(sale_line_id) FROM fact_sales_line), 1))")


async def build_entity_search(connection: asyncpg.Connection) -> None:
    """One searchable row per resolvable entity, with curated synonyms."""
    await connection.execute("TRUNCATE entity_search")

    await connection.execute("""
        INSERT INTO entity_search (kind, entity_id, label, path, synonyms, supplier_id)
        SELECT 'product', p.product_id, p.name,
               top.name || ' › ' || sub.name || ' › ' || p.name,
               lower(b.name || ' ' || sub.name || ' ' || COALESCE(p.ean, '')),
               b.supplier_id
          FROM dim_product p
          JOIN dim_brand b   ON b.brand_id = p.brand_id
          JOIN dim_category sub ON sub.category_id = p.category_id
          JOIN dim_category top ON top.category_id = sub.parent_id
    """)

    await connection.execute("""
        INSERT INTO entity_search (kind, entity_id, label, path, synonyms, supplier_id)
        SELECT 'brand', b.brand_id, b.name, 'Varumärke › ' || b.name,
               lower(b.name), b.supplier_id
          FROM dim_brand b
    """)

    await connection.execute("""
        INSERT INTO entity_search (kind, entity_id, label, path, synonyms, supplier_id)
        SELECT 'category', c.category_id, c.name,
               COALESCE(parent.name || ' › ', '') || c.name,
               lower(c.name), NULL
          FROM dim_category c
          LEFT JOIN dim_category parent ON parent.category_id = c.parent_id
    """)

    await connection.execute("""
        INSERT INTO entity_search (kind, entity_id, label, path, synonyms, supplier_id)
        SELECT 'store', s.store_id, s.name,
               s.region || ' › ' || s.city || ' › ' || s.name,
               lower(s.city || ' ' || s.municipality || ' ' || s.channel), NULL
          FROM dim_store s
    """)

    # Regions are not a table, so they get synthetic ids - dense_rank over the distinct names,
    # stable for a given dataset.
    await connection.execute("""
        INSERT INTO entity_search (kind, entity_id, label, path, synonyms, supplier_id)
        SELECT 'region', dense_rank() OVER (ORDER BY region)::int, region,
               'Län › ' || region, lower(region), NULL
          FROM (SELECT DISTINCT region FROM dim_store) r
    """)

    for label, synonyms in {**REGION_SYNONYMS, **CATEGORY_SYNONYMS}.items():
        await connection.execute(
            "UPDATE entity_search SET synonyms = synonyms || ' ' || $2 "
            " WHERE label = $1 AND kind IN ('region', 'category')", label, synonyms)

    count = await connection.fetchval("SELECT COUNT(*) FROM entity_search")
    print(f"  entity_search: {count:,} rows")


async def create_users(connection: asyncpg.Connection) -> None:
    from argon2 import PasswordHasher

    hasher = PasswordHasher()
    await connection.execute("TRUNCATE app_user CASCADE")
    for email, display_name, supplier_name, role in DEMO_USERS:
        supplier_id = await connection.fetchval(
            "SELECT supplier_id FROM dim_supplier WHERE name = $1", supplier_name)
        if supplier_id is None:
            raise SystemExit(f"supplier not found: {supplier_name}")
        await connection.execute(
            "INSERT INTO app_user (email, password_hash, supplier_id, role, display_name) "
            "VALUES ($1, $2, $3, $4, $5)",
            email, hasher.hash(DEMO_PASSWORD), supplier_id, role, display_name)
        print(f"  user {email} → {supplier_name} ({role})")


async def refresh_rollups(connection: asyncpg.Connection) -> None:
    # Plain REFRESH, not CONCURRENTLY: this runs once on an empty-but-populated view where
    # CONCURRENTLY has no advantage and takes an exclusive lock either way.
    for view in ("mv_sales_daily", "mv_category_daily", "mv_brand_monthly"):
        await connection.execute(f"REFRESH MATERIALIZED VIEW {view}")
        count = await connection.fetchval(f"SELECT COUNT(*) FROM {view}")
        print(f"  {view}: {count:,} rows")


async def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="reload even if the database already holds facts")
    args = parser.parse_args()

    connection = await connect()
    try:
        existing = await connection.fetchval("SELECT COUNT(*) FROM fact_sales_line")
        if existing and not args.force:
            print(f"already seeded ({existing:,} order lines) - use --force to reload")
            return
        if existing:
            print("truncating…")
            await connection.execute(
                "TRUNCATE fact_sales_line, dim_product, dim_brand, dim_supplier, "
                "dim_store, dim_customer, dim_date, dim_category CASCADE")

        print("loading tables…")
        await load_tables(connection)
        print("building entity search…")
        await build_entity_search(connection)
        print("creating demo users…")
        await create_users(connection)
        print("refreshing rollups…")
        await refresh_rollups(connection)
        print("done.")
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
