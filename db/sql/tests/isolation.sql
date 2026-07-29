-- Proof of tenant isolation at the database level.
--
-- Deliberately pure SQL with no application code in the way. The claim in the README is that
-- a bug in the MCP server or the API still cannot leak another supplier's rows; that claim is
-- about Postgres, so it should be tested in Postgres.
--
-- Run against a seeded database:
--     psql -v ON_ERROR_STOP=1 -f db/sql/tests/isolation.sql
-- Raises an exception on the first failure, so a non-zero exit means isolation is broken.

\set ON_ERROR_STOP on

-- Become the role the MCP server actually connects as. As the owner, RLS would be bypassed
-- (policies are ENABLE, not FORCE) and every assertion below would pass for the wrong reason.
SET ROLE app_readonly;

DO $$
DECLARE
    rows_supplier_1 bigint;
    rows_supplier_2 bigint;
    leaked          bigint;
BEGIN
    IF current_user <> 'app_readonly' THEN
        RAISE EXCEPTION 'test must run as app_readonly, not %', current_user;
    END IF;

    -- ---------------------------------------------------------------- scoped reads
    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(*) INTO rows_supplier_1 FROM fact_sales_line;

    PERFORM set_config('app.supplier_id', '2', false);
    SELECT COUNT(*) INTO rows_supplier_2 FROM fact_sales_line;

    IF rows_supplier_1 = 0 OR rows_supplier_2 = 0 THEN
        RAISE EXCEPTION 'expected rows for both suppliers, got % and %',
            rows_supplier_1, rows_supplier_2;
    END IF;

    -- Every visible row must belong to the scoped supplier. This is the assertion that
    -- actually matters: not "how many rows" but "whose".
    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(*) INTO leaked FROM fact_sales_line WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'fact_sales_line leaked % rows from other suppliers', leaked;
    END IF;

    -- ------------------------------------------------------------- unscoped = closed
    -- An unset scope must return nothing. Failing closed is the whole design: forgetting to
    -- scope has to be a visibly empty result, never a full-table read.
    PERFORM set_config('app.supplier_id', '', false);
    SELECT COUNT(*) INTO leaked FROM fact_sales_line;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'unscoped connection saw % fact rows; must see 0', leaked;
    END IF;

    -- ------------------------------------------------------------- scoped dimensions
    PERFORM set_config('app.supplier_id', '1', false);

    SELECT COUNT(*) INTO leaked FROM dim_brand WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'dim_brand leaked % competitor brands', leaked;
    END IF;

    -- Brand names are what would make an anonymised competitor figure identifiable, so this
    -- is the policy that keeps v_category_brand_monthly safe to expose.
    SELECT COUNT(*) INTO leaked FROM dim_brand;
    IF leaked = 0 THEN
        RAISE EXCEPTION 'supplier 1 cannot see its own brands';
    END IF;

    SELECT COUNT(*) INTO leaked
      FROM dim_product p
     WHERE NOT EXISTS (SELECT 1 FROM dim_brand b
                        WHERE b.brand_id = p.brand_id AND b.supplier_id = 1);
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'dim_product leaked % foreign products', leaked;
    END IF;

    SELECT COUNT(*) INTO leaked FROM dim_supplier WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'dim_supplier leaked % other suppliers', leaked;
    END IF;

    -- ----------------------------------------------------------- barrier views scope
    SELECT COUNT(*) INTO leaked FROM v_sales_daily WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'v_sales_daily leaked % rows', leaked;
    END IF;

    SELECT COUNT(*) INTO leaked FROM v_brand_monthly WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'v_brand_monthly leaked % rows', leaked;
    END IF;

    -- The category rollup is intentionally unscoped: it holds no brand or supplier identity,
    -- and market share is unanswerable without it. Assert it still returns data, so a future
    -- over-tightening shows up here rather than as a silently broken feature.
    SELECT COUNT(*) INTO leaked FROM v_category_daily;
    IF leaked = 0 THEN
        RAISE EXCEPTION 'v_category_daily returned nothing; market share cannot work';
    END IF;

    RAISE NOTICE 'ok: row-level scoping holds (supplier 1: % rows, supplier 2: % rows)',
        rows_supplier_1, rows_supplier_2;
END $$;


-- ------------------------------------------------------- materialised views are closed
--
-- The rollups carry every supplier's data. They are never granted; the barrier views are the
-- only route in. If a GRANT is ever added carelessly, these three blocks fail.

DO $$
BEGIN
    PERFORM 1 FROM mv_sales_daily LIMIT 1;
    RAISE EXCEPTION 'app_readonly could read mv_sales_daily directly';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: mv_sales_daily is not directly readable';
END $$;

DO $$
BEGIN
    PERFORM 1 FROM mv_brand_monthly LIMIT 1;
    RAISE EXCEPTION 'app_readonly could read mv_brand_monthly directly';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: mv_brand_monthly is not directly readable';
END $$;

DO $$
BEGIN
    PERFORM 1 FROM app_user LIMIT 1;
    RAISE EXCEPTION 'app_readonly could read app_user (password hashes)';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: app_user is not readable by the analytics role';
END $$;


-- ------------------------------------------------------------------ read-only is read-only
DO $$
BEGIN
    PERFORM set_config('app.supplier_id', '1', false);
    UPDATE fact_sales_line SET quantity = quantity WHERE false;
    RAISE EXCEPTION 'app_readonly could issue an UPDATE';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: app_readonly cannot write';
END $$;

RESET ROLE;
\echo 'isolation.sql: all assertions passed'
