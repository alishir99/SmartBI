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


-- ==========================================================================================
-- Adversarial assertions: the three ways this proof could be true and worthless.
--
-- Everything above proves that RLS *works*. None of it proves that RLS is what is doing the
-- work, or that it cannot be walked around. These three do — each one pins an assumption the
-- rest of the file silently rests on.
-- ==========================================================================================

-- 1 -------------------------------------------------------- the role cannot ignore policies
--
-- Every assertion above is conditional on app_readonly being an ordinary role. A superuser
-- bypasses RLS entirely, and so does BYPASSRLS — and either would make this whole file pass
-- while isolating nothing at all. That is currently true and nothing enforced it, which is
-- the definition of an assumption rather than a guarantee.
--
-- It is also the sharpest way to state the risk in the compose file: the API connects as the
-- owner, which IS a superuser, and is safe only because every statement it issues carries an
-- explicit supplier_id predicate. The read path is safe structurally; the write path is safe
-- by discipline. This assertion is why that distinction is worth making out loud.
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
        RAISE EXCEPTION 'app_readonly is a SUPERUSER — every RLS assertion above passes for '
                        'the wrong reason, because policies are not applied to superusers';
    END IF;
    IF can_bypass THEN
        RAISE EXCEPTION 'app_readonly holds BYPASSRLS — row-level security is advisory for '
                        'this role and the isolation proven above does not exist';
    END IF;

    RAISE NOTICE 'ok: app_readonly is neither SUPERUSER nor BYPASSRLS';
END $$;


-- 2 ------------------------------------------------------ the scope cannot be made to widen
--
-- app.supplier_id is a text GUC that the policy casts to INT. A text setting that reaches a
-- comparison is the classic place an injected predicate would be smuggled in, so the question
-- is what the cast does with something that is not a number. The requirement is not that it
-- errors — it is that it never yields a WIDER set. Erroring is one acceptable outcome; zero
-- rows is another; anything that returns rows for a supplier the caller did not name is not.
--
-- Tested with the three shapes that would matter: a SQL fragment, a comma list, and a value
-- with trailing text that a lenient cast might truncate rather than reject.
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

            -- The cast did not error. Then it must have produced at most one supplier, and
            -- never a second one the caller never named.
            IF visible > 1 THEN
                RAISE EXCEPTION 'app.supplier_id = % widened the scope to % suppliers',
                    payload, visible;
            END IF;
            RAISE NOTICE 'ok: app.supplier_id = % yielded % supplier(s)', payload, visible;
        EXCEPTION
            WHEN invalid_text_representation THEN
                -- The ::INT cast rejected it. The strongest possible outcome.
                RAISE NOTICE 'ok: app.supplier_id = % was rejected by the cast', payload;
        END;
    END LOOP;

    -- And the scope still works afterwards, so the loop above cannot have passed by
    -- leaving the session in a permanently broken state.
    PERFORM set_config('app.supplier_id', '1', false);
    SELECT COUNT(DISTINCT supplier_id) INTO visible FROM fact_sales_line;
    IF visible <> 1 THEN
        RAISE EXCEPTION 'after the injection attempts a legitimate scope saw % suppliers',
            visible;
    END IF;
END $$;


-- 3 ------------------------------------------------ the barrier views cannot be pushed past
--
-- 04_rls.sql marks the views security_barrier, and names the reason: without it Postgres may
-- push a user-supplied function INTO the view, where it runs against rows the caller was
-- never meant to see and can leak them through an error message or a side effect. The barrier
-- is the mitigation. Not being able to create a function at all is the reason the mitigation
-- never has to hold — defence in depth, tested rather than assumed.
DO $$
BEGIN
    EXECUTE $fn$
        CREATE FUNCTION leak_probe(anyelement) RETURNS boolean AS
        $body$ SELECT true $body$ LANGUAGE sql COST 0.0000001
    $fn$;
    -- If we get here the function exists, which is the failure. Drop it before raising so a
    -- failing run does not leave an artefact behind for the next one.
    EXECUTE 'DROP FUNCTION IF EXISTS leak_probe(anyelement)';
    RAISE EXCEPTION 'app_readonly could CREATE FUNCTION — a cheap function can be pushed '
                    'into a barrier view and used to read rows the policy excludes';
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'ok: app_readonly cannot create functions';
END $$;


-- 4 ------------------------------------------------------------ the policies are still on
--
-- The cheapest way to silently undo all of the above is ALTER TABLE ... DISABLE ROW LEVEL
-- SECURITY. Nothing in the assertions above distinguishes "the policy allowed exactly the
-- caller's rows" from "the policy is off and the caller happens to be scoped anyway", because
-- the application always sets the GUC. Asserting relrowsecurity directly closes that.
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
