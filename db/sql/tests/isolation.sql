-- Proof of tenant isolation at the DB level: deliberately pure SQL, no application code in
-- the way, since the claim (a bug in the MCP server/API still can't leak rows) is about Postgres.
-- Run: psql -v ON_ERROR_STOP=1 -f db/sql/tests/isolation.sql

\set ON_ERROR_STOP on

-- The role the MCP server connects as. As owner, RLS would be bypassed (ENABLE not FORCE)
-- and every assertion below would pass for the wrong reason.
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

    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(*) INTO rows_supplier_1 FROM fact_sales_line;

    PERFORM set_config('app.supplier_id', '2', false);
    SELECT COUNT(*) INTO rows_supplier_2 FROM fact_sales_line;

    IF rows_supplier_1 = 0 OR rows_supplier_2 = 0 THEN
        RAISE EXCEPTION 'expected rows for both suppliers, got % and %',
            rows_supplier_1, rows_supplier_2;
    END IF;

    -- Every visible row must belong to the scoped supplier - "whose", not just "how many".
    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(*) INTO leaked FROM fact_sales_line WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'fact_sales_line leaked % rows from other suppliers', leaked;
    END IF;

    -- Unset scope must return nothing: failing closed, never a full-table read.
    PERFORM set_config('app.supplier_id', '', false);
    SELECT COUNT(*) INTO leaked FROM fact_sales_line;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'unscoped connection saw % fact rows; must see 0', leaked;
    END IF;

    PERFORM set_config('app.supplier_id', '1', false);

    SELECT COUNT(*) INTO leaked FROM dim_brand WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'dim_brand leaked % competitor brands', leaked;
    END IF;

    -- Brand names would make an anonymised competitor figure identifiable - this policy
    -- is what keeps v_category_brand_monthly safe to expose.
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

    SELECT COUNT(*) INTO leaked FROM v_sales_daily WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'v_sales_daily leaked % rows', leaked;
    END IF;

    SELECT COUNT(*) INTO leaked FROM v_brand_monthly WHERE supplier_id <> 1;
    IF leaked <> 0 THEN
        RAISE EXCEPTION 'v_brand_monthly leaked % rows', leaked;
    END IF;

    -- Category rollup is intentionally unscoped (no brand/supplier identity); assert it
    -- still returns data so a future over-tightening shows up here, not as a broken feature.
    SELECT COUNT(*) INTO leaked FROM v_category_daily;
    IF leaked = 0 THEN
        RAISE EXCEPTION 'v_category_daily returned nothing; market share cannot work';
    END IF;

    RAISE NOTICE 'ok: row-level scoping holds (supplier 1: % rows, supplier 2: % rows)',
        rows_supplier_1, rows_supplier_2;
END $$;


-- Rollups carry every supplier's data and are never granted; barrier views are the only
-- route in. A careless GRANT makes these three blocks fail.

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

-- Read-only is read-only.
DO $$
BEGIN
    PERFORM set_config('app.supplier_id', '1', false);
    UPDATE fact_sales_line SET quantity = quantity WHERE false;
    RAISE EXCEPTION 'app_readonly could issue an UPDATE';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: app_readonly cannot write';
END $$;

-- Adversarial assertions: everything above proves RLS works, not that RLS is what's doing
-- the work or that it can't be walked around. These four pin the assumptions the rest rests on.

-- 1: the role cannot ignore policies. A superuser/BYPASSRLS role skips RLS entirely, which
-- would make this whole file pass while isolating nothing.
DO $$
DECLARE
    is_super   boolean;
    can_bypass boolean;
BEGIN
    SELECT rolsuper, rolbypassrls INTO is_super, can_bypass
    FROM pg_roles WHERE rolname = 'app_readonly';

    IF is_super IS NULL THEN
        RAISE EXCEPTION 'app_readonly does not exist';
    END IF;
    IF is_super THEN
        RAISE EXCEPTION 'app_readonly is a SUPERUSER - every RLS assertion above passes for '
                        'the wrong reason, because policies are not applied to superusers';
    END IF;
    IF can_bypass THEN
        RAISE EXCEPTION 'app_readonly holds BYPASSRLS - row-level security is advisory for '
                        'this role and the isolation proven above does not exist';
    END IF;

    RAISE NOTICE 'ok: app_readonly is neither SUPERUSER nor BYPASSRLS';
END $$;


-- 2: the scope cannot be made to widen. app.supplier_id is a text GUC cast to INT by the
-- policy - the requirement isn't that a bad value errors, only that it never yields more rows.
DO $$
DECLARE
    payload   text;
    visible   bigint;
    injected  text[] := ARRAY['1 OR 1=1', '1,2', '1; SELECT 1', '1 UNION SELECT 2', '2abc'];
BEGIN
    FOREACH payload IN ARRAY injected LOOP
        BEGIN
            PERFORM set_config('app.supplier_id', payload, false);
            SELECT COUNT(DISTINCT supplier_id) INTO visible FROM fact_sales_line;

            IF visible > 1 THEN
                RAISE EXCEPTION 'app.supplier_id = % widened the scope to % suppliers',
                    payload, visible;
            END IF;
            RAISE NOTICE 'ok: app.supplier_id = % yielded % supplier(s)', payload, visible;
        EXCEPTION
            WHEN invalid_text_representation THEN
                -- The ::INT cast rejected it - the strongest possible outcome.
                RAISE NOTICE 'ok: app.supplier_id = % was rejected by the cast', payload;
        END;
    END LOOP;

    -- Scope still works afterwards, so the loop above didn't pass by leaving the session broken.
    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(DISTINCT supplier_id) INTO visible FROM fact_sales_line;
    IF visible <> 1 THEN
        RAISE EXCEPTION 'after the injection attempts a legitimate scope saw % suppliers',
            visible;
    END IF;
END $$;


-- 3: the barrier views cannot be pushed past. security_barrier (04_rls.sql) exists because
-- Postgres may otherwise push a user-supplied function into the view and leak scoped rows.
DO $$
BEGIN
    EXECUTE $fn$
        CREATE FUNCTION leak_probe(anyelement) RETURNS boolean AS
        $body$ SELECT true $body$ LANGUAGE sql COST 0.0000001
    $fn$;
    -- Reaching here means the function exists - the failure. Drop it before raising so a
    -- failing run leaves no artefact for the next one.
    EXECUTE 'DROP FUNCTION IF EXISTS leak_probe(anyelement)';
    RAISE EXCEPTION 'app_readonly could CREATE FUNCTION - a cheap function can be pushed '
                    'into a barrier view and used to read rows the policy excludes';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: app_readonly cannot create functions';
END $$;


-- 4: the policies are still on. Nothing above distinguishes "policy allowed exactly the
-- caller's rows" from "policy is off and the caller happens to be scoped anyway" - check directly.
DO $$
DECLARE
    unprotected text;
BEGIN
    SELECT string_agg(relname, ', ' ORDER BY relname) INTO unprotected
    FROM pg_class
    WHERE relname IN ('fact_sales_line', 'dim_product', 'dim_brand', 'dim_supplier',
                      'saved_card', 'audit_turn')
      AND relkind = 'r'
      AND NOT relrowsecurity;

    IF unprotected IS NOT NULL THEN
        RAISE EXCEPTION 'row level security is DISABLED on: %', unprotected;
    END IF;
    RAISE NOTICE 'ok: row level security is enabled on every tenant-scoped table';
END $$;


RESET ROLE;
\echo 'isolation.sql: all assertions passed'
