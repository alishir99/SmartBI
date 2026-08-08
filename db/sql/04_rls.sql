-- Tenant isolation layer 3 - holds even if the app-layer scoping (layers 1-2) has a bug.
-- Postgres has no RLS on materialised views, so rollups use barrier views instead (below).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly LOGIN PASSWORD 'app_readonly';
    END IF;
END
$$;

-- Read-only role the MCP server connects as; dev credentials only (prod: Secret Manager).

-- NULL when app.supplier_id isn't set, so an unscoped connection sees zero rows, not all.
CREATE OR REPLACE FUNCTION current_supplier_id() RETURNS INT
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.supplier_id', true), '')::INT
$$;

-- ENABLE not FORCE: policies bind to app_readonly only, so the seeder/refresh job (table
-- owner) still works.

ALTER TABLE fact_sales_line ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_fact ON fact_sales_line
    FOR SELECT TO app_readonly
    USING (supplier_id = current_supplier_id());

ALTER TABLE dim_supplier ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_supplier ON dim_supplier
    FOR SELECT TO app_readonly
    USING (supplier_id = current_supplier_id());

ALTER TABLE dim_brand ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_brand ON dim_brand
    FOR SELECT TO app_readonly
    USING (supplier_id = current_supplier_id());

ALTER TABLE dim_product ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_product ON dim_product
    FOR SELECT TO app_readonly
    USING (EXISTS (SELECT 1 FROM dim_brand b
                   WHERE b.brand_id = dim_product.brand_id
                     AND b.supplier_id = current_supplier_id()));

-- Shared entities (region/category/store) carry supplier_id IS NULL and resolve for
-- everyone; own products/brands resolve only for their owner.
ALTER TABLE entity_search ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_entity ON entity_search
    FOR SELECT TO app_readonly
    USING (supplier_id IS NULL OR supplier_id = current_supplier_id());

ALTER TABLE saved_card ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_card ON saved_card
    FOR SELECT TO app_readonly
    USING (supplier_id = current_supplier_id());

ALTER TABLE audit_turn ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_audit ON audit_turn
    FOR SELECT TO app_readonly
    USING (supplier_id = current_supplier_id());

-- Own-brand daily detail, scoped exactly like the fact table policy.
CREATE VIEW v_sales_daily WITH (security_barrier = true) AS
SELECT * FROM mv_sales_daily
WHERE supplier_id = current_supplier_id();

-- Own brand's row only, already carrying category_net_sek/share_pct/rank, so "how am I
-- doing vs category" is answerable without any competitor row being reachable.
CREATE VIEW v_brand_monthly WITH (security_barrier = true) AS
SELECT * FROM mv_brand_monthly
WHERE supplier_id = current_supplier_id();

-- Unscoped: category totals carry no brand/supplier identity. k-anonymity is enforced by
-- query_market_share on the requested aggregate, not here (a daily row could dodge it).
CREATE VIEW v_category_daily WITH (security_barrier = true) AS
SELECT * FROM mv_category_daily;

-- Per-brand magnitudes to rank a supplier vs its category; brand_id can't become a name
-- (dim_brand's own RLS), and only query_market_share ever reads this view.
CREATE VIEW v_category_brand_monthly WITH (security_barrier = true) AS
SELECT month, brand_id, category_id, region, net_sales_sek, qty
FROM mv_brand_monthly;

GRANT USAGE ON SCHEMA public TO app_readonly;

GRANT SELECT ON
    fact_sales_line, dim_supplier, dim_brand, dim_product,
    dim_category, dim_store, dim_customer, dim_date,
    entity_search, saved_card, audit_turn,
    v_sales_daily, v_brand_monthly, v_category_daily, v_category_brand_monthly
TO app_readonly;

-- Materialised views themselves are never granted - reachable only via the barrier views.
REVOKE ALL ON mv_sales_daily, mv_category_daily, mv_brand_monthly FROM PUBLIC;

-- app_user (password hashes) is never granted - auth runs on the API's own connection.
