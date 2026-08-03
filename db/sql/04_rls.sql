-- Tenant isolation, layer 3 (IMPLEMENTATION_PLAN.md §6.3, §11.2).
--
-- Layers 1 and 2 live above this file: supplier_id appears in no tool's input schema,
-- and the MCP server derives scope from the connection context rather than the tool
-- arguments. This file is the layer that still holds if both of those have a bug.
--
-- IMPORTANT CORRECTION TO THE PLAN: PostgreSQL does not support row-level security on
-- materialised views - CREATE POLICY only accepts tables. The plan said "RLS policies on
-- fact_sales_line and the rollups"; only the first half is achievable directly. The
-- rollups are therefore protected by the equivalent construct: no grant on the
-- materialised view itself, and access exclusively through a security_barrier view whose
-- predicate is the same current_setting() comparison a policy would have used. Same
-- guarantee, different mechanism - a barrier view stops a user-supplied function being
-- pushed down below the predicate, which is the leak this needs to prevent.

-- The role the MCP server connects as. Read-only by construction: it is granted SELECT
-- and nothing else, so a bug in the semantic compiler cannot write.
-- Dev credentials only; production injects these from Secret Manager (§11.4).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly LOGIN PASSWORD 'app_readonly';
    END IF;
END
$$;

-- Scope helper. Returns NULL when app.supplier_id was never set, and every policy below
-- compares against it - so an unscoped connection sees zero rows rather than all rows.
-- Failing closed is the whole point.
CREATE OR REPLACE FUNCTION current_supplier_id() RETURNS INT
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.supplier_id', true), '')::INT
$$;

-- ------------------------------------------------------------------ RLS: tables
--
-- ENABLE, not FORCE: policies apply to app_readonly but not to the table owner, which is
-- what lets the seeder and the rollup refresh job do their work.

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

-- Shared entities (regions, categories, stores) carry supplier_id IS NULL and stay
-- resolvable by everyone; own products and brands resolve only for their owner.
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

-- --------------------------------------------------------- barrier views: rollups

-- Own-brand daily detail, scoped exactly as the fact policy scopes the fact table.
CREATE VIEW v_sales_daily WITH (security_barrier = true) AS
SELECT * FROM mv_sales_daily
WHERE supplier_id = current_supplier_id();

-- Own brand's row only. Each row already carries category_net_sek, share_pct, rank and
-- n_brands, so "how am I doing against the category" is answerable without a single
-- competitor row being reachable.
CREATE VIEW v_brand_monthly WITH (security_barrier = true) AS
SELECT * FROM mv_brand_monthly
WHERE supplier_id = current_supplier_id();

-- Category totals hold no brand or supplier identity, so the view is unscoped. The
-- k-anonymity guard (>= 5 brands, >= 100 transactions) is deliberately NOT here: it has
-- to be applied to the aggregate the caller actually requested, not to a daily row, or a
-- thin slice could pass the test one day at a time. query_market_share enforces it (§11.3).
CREATE VIEW v_category_daily WITH (security_barrier = true) AS
SELECT * FROM mv_category_daily;

-- Rank is the one market-share figure that cannot be derived from a supplier's own rows:
-- knowing you sold 4 MSEK says nothing about your position. Computing it over an arbitrary
-- window needs per-brand magnitudes for the whole category, so this view exposes them -
-- with supplier_id dropped, and with brand_id left in only because it is needed to group
-- months back into one figure per competitor.
--
-- Why that is not a leak: brand_id cannot be turned into a name, because dim_brand's RLS
-- policy restricts it to the caller's own brands. And query_market_share never returns
-- these rows - it consumes them and emits only own_share, rank, n_brands and the leader's
-- share. The view is reachable by the MCP server; it is not reachable by the model.
CREATE VIEW v_category_brand_monthly WITH (security_barrier = true) AS
SELECT month, brand_id, category_id, region, net_sales_sek, qty
FROM mv_brand_monthly;

-- ----------------------------------------------------------------------- grants

GRANT USAGE ON SCHEMA public TO app_readonly;

GRANT SELECT ON
    fact_sales_line, dim_supplier, dim_brand, dim_product,
    dim_category, dim_store, dim_customer, dim_date,
    entity_search, saved_card, audit_turn,
    v_sales_daily, v_brand_monthly, v_category_daily, v_category_brand_monthly
TO app_readonly;

-- Explicitly NOT granted: the materialised views themselves. The only way to their
-- contents is through the barrier views above.
REVOKE ALL ON mv_sales_daily, mv_category_daily, mv_brand_monthly FROM PUBLIC;

-- Never granted at all: app_user (password hashes). Authentication runs on the API's own
-- connection, not the read-only analytics role.
