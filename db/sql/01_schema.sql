-- Solvigo Insights — star schema (IMPLEMENTATION_PLAN.md §5.2)
--
-- Grain of the fact table: one row per order line. Everything else is derivable.
-- Money is SEK excluding VAT; the unit is stated in the column name and re-stated
-- in every MCP tool response's meta.unit (§9.3).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- dimensions

CREATE TABLE dim_supplier (
    supplier_id  INT PRIMARY KEY,
    name         TEXT NOT NULL,
    org_nr       TEXT NOT NULL UNIQUE,
    country      TEXT NOT NULL DEFAULT 'SE'
);

CREATE TABLE dim_brand (
    brand_id     INT PRIMARY KEY,
    supplier_id  INT NOT NULL REFERENCES dim_supplier(supplier_id),
    name         TEXT NOT NULL UNIQUE
);

-- Self-referencing hierarchy: level 1 = category, level 2 = subcategory.
CREATE TABLE dim_category (
    category_id  INT PRIMARY KEY,
    parent_id    INT REFERENCES dim_category(category_id),
    name         TEXT NOT NULL,
    level        SMALLINT NOT NULL CHECK (level IN (1, 2))
);

CREATE TABLE dim_product (
    product_id        INT PRIMARY KEY,
    brand_id          INT NOT NULL REFERENCES dim_brand(brand_id),
    category_id       INT NOT NULL REFERENCES dim_category(category_id),
    name              TEXT NOT NULL,
    ean               TEXT NOT NULL UNIQUE,
    list_price_sek    NUMERIC(10, 2) NOT NULL,
    launch_date       DATE NOT NULL,
    discontinued_date DATE
);

CREATE TABLE dim_store (
    store_id     INT PRIMARY KEY,
    name         TEXT NOT NULL,
    channel      TEXT NOT NULL CHECK (channel IN ('fysisk', 'online')),
    city         TEXT NOT NULL,
    municipality TEXT NOT NULL,
    region       TEXT NOT NULL,          -- län
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION,
    opened_date  DATE NOT NULL
);

-- No direct identifiers. pseudonym_id is what an erasure request would target (§15).
CREATE TABLE dim_customer (
    customer_id  BIGINT PRIMARY KEY,
    pseudonym_id TEXT NOT NULL UNIQUE,
    segment      TEXT NOT NULL,
    region       TEXT NOT NULL,
    age_bucket   TEXT NOT NULL,
    loyalty_tier TEXT NOT NULL
);

CREATE TABLE dim_date (
    date_id     INT PRIMARY KEY,          -- YYYYMMDD
    date        DATE NOT NULL UNIQUE,
    iso_year    SMALLINT NOT NULL,
    iso_week    SMALLINT NOT NULL,
    month       SMALLINT NOT NULL,
    quarter     SMALLINT NOT NULL,
    year        SMALLINT NOT NULL,
    weekday     SMALLINT NOT NULL,
    is_holiday  BOOLEAN NOT NULL DEFAULT FALSE,
    campaign_id INT
);

-- ---------------------------------------------------------------------- fact

CREATE TABLE fact_sales_line (
    sale_line_id        BIGSERIAL PRIMARY KEY,
    order_id            BIGINT NOT NULL,
    date_id             INT NOT NULL REFERENCES dim_date(date_id),
    store_id            INT NOT NULL REFERENCES dim_store(store_id),
    customer_id         BIGINT REFERENCES dim_customer(customer_id),  -- NULL = cash purchase
    product_id          INT NOT NULL REFERENCES dim_product(product_id),
    -- Denormalised from dim_product → dim_brand purely so the RLS policy (04_rls.sql)
    -- is a column comparison rather than a two-hop subquery evaluated per row.
    supplier_id         INT NOT NULL REFERENCES dim_supplier(supplier_id),
    quantity            INT NOT NULL,
    gross_amount_sek    NUMERIC(12, 2) NOT NULL,
    discount_amount_sek NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_amount_sek      NUMERIC(12, 2) NOT NULL,
    is_return           BOOLEAN NOT NULL DEFAULT FALSE
);

-- --------------------------------------------------------- entity resolution
--
-- One searchable row per resolvable entity (§5.4). Populated by the seeder from the
-- dimensions; embedding stays NULL unless scripts/embed_entities.py has been run, in
-- which case resolve_entities fuses trigram and vector hits with RRF. Lexical search
-- works with or without it, so the heavy embedding model is opt-in, not a hard dep.
CREATE TABLE entity_search (
    kind       TEXT NOT NULL CHECK (kind IN ('product', 'category', 'store', 'brand', 'region')),
    entity_id  INT NOT NULL,
    label      TEXT NOT NULL,
    path       TEXT NOT NULL,            -- e.g. "Ljud & Bild › Hörlurar › Nordström N7"
    synonyms   TEXT NOT NULL DEFAULT '',
    supplier_id INT REFERENCES dim_supplier(supplier_id),  -- NULL = not supplier-owned
    embedding  vector(384),
    PRIMARY KEY (kind, entity_id)
);

-- ----------------------------------------------------------- app users, audit

CREATE TABLE app_user (
    user_id       SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    supplier_id   INT REFERENCES dim_supplier(supplier_id),  -- NULL for retail_analyst
    role          TEXT NOT NULL CHECK (role IN
                     ('supplier_viewer', 'supplier_admin', 'retail_analyst', 'system_admin')),
    display_name  TEXT NOT NULL
);

-- Every agent turn, for debugging, billing and GDPR accountability alike (§11.2).
CREATE TABLE audit_turn (
    turn_id      BIGSERIAL PRIMARY KEY,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id      INT REFERENCES app_user(user_id),
    supplier_id  INT REFERENCES dim_supplier(supplier_id),
    question     TEXT NOT NULL,
    tool_calls   JSONB NOT NULL DEFAULT '[]'::jsonb,
    row_counts   JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms   INT,
    input_tokens INT,
    output_tokens INT,
    status       TEXT NOT NULL          -- ok | cannot_answer | validation_failed | error
);

-- Saved cards ("Mina vyer"): the spec plus the tool arguments, never a screenshot,
-- so a saved card re-runs live against fresh data (§10).
CREATE TABLE saved_card (
    card_id     BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id     INT NOT NULL REFERENCES app_user(user_id),
    supplier_id INT NOT NULL REFERENCES dim_supplier(supplier_id),
    title       TEXT NOT NULL,
    chart_spec  JSONB NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_args   JSONB NOT NULL
);
