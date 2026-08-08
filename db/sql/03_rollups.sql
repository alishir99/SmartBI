-- Materialised rollups (§5.3): latency, plus the privacy boundary - mv_category_daily and
-- mv_brand_monthly are the only objects query_market_share may read, so competitor detail
-- was never in the object, not filtered out after the fact.

-- Own-brand detail, still supplier-attributable. Reached through v_sales_daily.
CREATE MATERIALIZED VIEW mv_sales_daily AS
SELECT
    d.date,
    f.supplier_id,
    f.product_id,
    st.region,
    st.channel,
    SUM(f.quantity)                                   AS qty,
    SUM(f.net_amount_sek)                             AS net_sales_sek,
    SUM(f.gross_amount_sek)                           AS gross_sales_sek,
    SUM(f.discount_amount_sek)                        AS discount_sek,
    COUNT(*)                                          AS n_lines,
    COUNT(DISTINCT f.order_id)                        AS n_orders
FROM fact_sales_line f
JOIN dim_date  d  ON d.date_id  = f.date_id
JOIN dim_store st ON st.store_id = f.store_id
GROUP BY d.date, f.supplier_id, f.product_id, st.region, st.channel;

CREATE UNIQUE INDEX uq_mv_sales_daily
    ON mv_sales_daily (date, supplier_id, product_id, region, channel);
CREATE INDEX idx_mv_sales_daily_supplier ON mv_sales_daily (supplier_id, date);

-- Category totals across ALL brands, no brand/supplier identity - aggregated away is what
-- makes it safe to read cross-tenant. n_brands/n_transactions feed the k-anonymity guard (§11.3).
CREATE MATERIALIZED VIEW mv_category_daily AS
SELECT
    d.date,
    p.category_id,
    st.region,
    st.channel,
    SUM(f.quantity)                                   AS total_qty,
    SUM(f.net_amount_sek)                             AS total_net_sek,
    COUNT(DISTINCT p.brand_id)                        AS n_brands,
    COUNT(DISTINCT f.order_id)                        AS n_transactions
FROM fact_sales_line f
JOIN dim_date    d  ON d.date_id     = f.date_id
JOIN dim_store   st ON st.store_id   = f.store_id
JOIN dim_product p  ON p.product_id  = f.product_id
GROUP BY d.date, p.category_id, st.region, st.channel;

CREATE UNIQUE INDEX uq_mv_category_daily
    ON mv_category_daily (date, category_id, region, channel);

-- Each row carries its own category context (total/share/rank/peer count), so a supplier
-- can answer "how am I doing vs category" from only its own rows.
CREATE MATERIALIZED VIEW mv_brand_monthly AS
WITH base AS (
    SELECT
        date_trunc('month', d.date)::date AS month,
        b.brand_id,
        b.supplier_id,
        p.category_id,
        st.region,
        SUM(f.net_amount_sek) AS net_sales_sek,
        SUM(f.quantity)       AS qty
    FROM fact_sales_line f
    JOIN dim_date     d  ON d.date_id    = f.date_id
    JOIN dim_store    st ON st.store_id  = f.store_id
    JOIN dim_product  p  ON p.product_id = f.product_id
    JOIN dim_brand    b  ON b.brand_id   = p.brand_id
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    month,
    brand_id,
    supplier_id,
    category_id,
    region,
    net_sales_sek,
    qty,
    SUM(net_sales_sek) OVER w                                  AS category_net_sek,
    ROUND(100 * net_sales_sek / NULLIF(SUM(net_sales_sek) OVER w, 0), 2) AS share_pct,
    RANK() OVER (PARTITION BY month, category_id, region ORDER BY net_sales_sek DESC) AS rank,
    COUNT(*) OVER w                                            AS n_brands
FROM base
WINDOW w AS (PARTITION BY month, category_id, region);

CREATE UNIQUE INDEX uq_mv_brand_monthly
    ON mv_brand_monthly (month, brand_id, category_id, region);
CREATE INDEX idx_mv_brand_monthly_supplier ON mv_brand_monthly (supplier_id, month);
