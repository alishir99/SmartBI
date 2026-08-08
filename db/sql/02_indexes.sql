-- Sized for the query shapes the semantic compiler emits: date range + supplier scope,
-- then some subset of product/category/region/channel.

-- Leading supplier_id matches the RLS predicate and every tenant-scoped scan.
CREATE INDEX idx_fact_supplier_date   ON fact_sales_line (supplier_id, date_id);
CREATE INDEX idx_fact_product_date    ON fact_sales_line (product_id, date_id);
CREATE INDEX idx_fact_store_date      ON fact_sales_line (store_id, date_id);
CREATE INDEX idx_fact_date            ON fact_sales_line (date_id);
CREATE INDEX idx_fact_order           ON fact_sales_line (order_id);

CREATE INDEX idx_product_brand        ON dim_product (brand_id);
CREATE INDEX idx_product_category     ON dim_product (category_id);
CREATE INDEX idx_brand_supplier       ON dim_brand (supplier_id);
CREATE INDEX idx_category_parent      ON dim_category (parent_id);
CREATE INDEX idx_store_region         ON dim_store (region);
CREATE INDEX idx_date_date            ON dim_date (date);

-- Entity resolution: trigram for lexical, IVFFlat for semantic (§5.4).
CREATE INDEX idx_entity_label_trgm    ON entity_search USING gin (label gin_trgm_ops);
CREATE INDEX idx_entity_synonyms_trgm ON entity_search USING gin (synonyms gin_trgm_ops);
CREATE INDEX idx_entity_kind          ON entity_search (kind);

-- IVFFlat index on embedding is built by scripts/embed_entities.py after embeddings exist -
-- one on an all-NULL column is useless.

CREATE INDEX idx_audit_supplier_time  ON audit_turn (supplier_id, occurred_at DESC);
CREATE INDEX idx_card_user            ON saved_card (user_id, created_at DESC);
