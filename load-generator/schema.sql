-- E-Commerce OLTP Schema for pg-collector Soak Tests
-- ~18 tables, ~30M seeded rows, ~10 GB
-- Run as: psql -h 127.0.0.1 -U soak_load -d soak_test -f schema.sql

-- Pre-requisite extensions (must be outside transaction for some PG versions)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP TABLE IF EXISTS pgbench_accounts, pgbench_branches, pgbench_history, pgbench_tellers CASCADE;
DROP TABLE IF EXISTS soak_orders, soak_events, soak_metrics CASCADE;
DROP TABLE IF EXISTS coupon_redemptions, promotions, reviews CASCADE;
DROP TABLE IF EXISTS search_log, audit_log CASCADE;
DROP TABLE IF EXISTS cart_items, sessions CASCADE;
DROP TABLE IF EXISTS shipments, payments, order_items, orders CASCADE;
DROP TABLE IF EXISTS price_history, inventory, product_variants, products, categories CASCADE;
DROP TABLE IF EXISTS addresses, customers CASCADE;

BEGIN;

-- ════════════════════════════════════════════════════════════════
-- Customer Domain
-- ════════════════════════════════════════════════════════════════

CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    name        TEXT NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '$2a$10$placeholder',
    last_login  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_created ON customers(created_at);
CREATE INDEX idx_customers_last_login ON customers(last_login);

CREATE TABLE addresses (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    addr_type   TEXT NOT NULL DEFAULT 'shipping',
    line1       TEXT NOT NULL,
    line2       TEXT,
    city        TEXT NOT NULL,
    state       TEXT NOT NULL,
    zip         TEXT NOT NULL,
    country     TEXT NOT NULL DEFAULT 'US',
    is_default  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_addresses_customer ON addresses(customer_id);
CREATE INDEX idx_addresses_default ON addresses(customer_id, is_default) WHERE is_default = true;

-- ════════════════════════════════════════════════════════════════
-- Product Catalog
-- ════════════════════════════════════════════════════════════════

CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    parent_id   INT REFERENCES categories(id),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    position    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_categories_slug ON categories(slug);
CREATE INDEX idx_categories_parent ON categories(parent_id);

CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,
    category_id INT NOT NULL REFERENCES categories(id),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    description TEXT,
    base_price  NUMERIC(10,2) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_products_slug ON products(slug);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_price ON products(base_price);
CREATE INDEX idx_products_name_trgm ON products USING gin (name gin_trgm_ops);

CREATE TABLE product_variants (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT NOT NULL REFERENCES products(id),
    sku         TEXT NOT NULL,
    name        TEXT NOT NULL,
    price_override NUMERIC(10,2),
    weight_grams INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_variants_sku ON product_variants(sku);
CREATE INDEX idx_variants_product ON product_variants(product_id);

CREATE TABLE inventory (
    variant_id    BIGINT PRIMARY KEY REFERENCES product_variants(id),
    warehouse_id  INT NOT NULL DEFAULT 1,
    qty_available INT NOT NULL DEFAULT 0,
    qty_reserved  INT NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_inventory_low_stock ON inventory(qty_available) WHERE qty_available < 10;
CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id);

CREATE TABLE price_history (
    id          BIGSERIAL PRIMARY KEY,
    variant_id  BIGINT NOT NULL REFERENCES product_variants(id),
    old_price   NUMERIC(10,2) NOT NULL,
    new_price   NUMERIC(10,2) NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_price_history_variant ON price_history(variant_id);
CREATE INDEX idx_price_history_date ON price_history(changed_at);

-- ════════════════════════════════════════════════════════════════
-- Order Domain
-- ════════════════════════════════════════════════════════════════

CREATE TABLE orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    address_id  BIGINT REFERENCES addresses(id),
    status      TEXT NOT NULL DEFAULT 'pending',
    subtotal    NUMERIC(12,2) NOT NULL,
    tax         NUMERIC(10,2) NOT NULL DEFAULT 0,
    shipping    NUMERIC(10,2) NOT NULL DEFAULT 0,
    total       NUMERIC(12,2) NOT NULL,
    placed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_placed ON orders(placed_at);
CREATE INDEX idx_orders_customer_placed ON orders(customer_id, placed_at DESC);

CREATE TABLE order_items (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(id),
    variant_id  BIGINT NOT NULL REFERENCES product_variants(id),
    qty         INT NOT NULL,
    unit_price  NUMERIC(10,2) NOT NULL,
    line_total  NUMERIC(12,2) NOT NULL
);

CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_variant ON order_items(variant_id);

CREATE TABLE payments (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    method          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    amount          NUMERIC(12,2) NOT NULL,
    gateway_txn_id  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at      TIMESTAMPTZ
);

CREATE INDEX idx_payments_order ON payments(order_id);
CREATE INDEX idx_payments_status ON payments(status);
CREATE INDEX idx_payments_gateway ON payments(gateway_txn_id);

CREATE TABLE shipments (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    carrier         TEXT NOT NULL,
    tracking_number TEXT,
    status          TEXT NOT NULL DEFAULT 'label_created',
    shipped_at      TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ
);

CREATE INDEX idx_shipments_order ON shipments(order_id);
CREATE INDEX idx_shipments_status ON shipments(status);
CREATE INDEX idx_shipments_tracking ON shipments(tracking_number);

-- ════════════════════════════════════════════════════════════════
-- Shopping
-- ════════════════════════════════════════════════════════════════

CREATE TABLE sessions (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    token       TEXT NOT NULL,
    ip_addr     INET,
    user_agent  TEXT,
    last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours'
);

CREATE UNIQUE INDEX idx_sessions_token ON sessions(token);
CREATE INDEX idx_sessions_customer ON sessions(customer_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);
CREATE INDEX idx_sessions_active ON sessions(last_active);

CREATE TABLE cart_items (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES sessions(id),
    variant_id  BIGINT NOT NULL REFERENCES product_variants(id),
    qty         INT NOT NULL DEFAULT 1,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cart_items_session ON cart_items(session_id);
CREATE INDEX idx_cart_items_variant ON cart_items(variant_id);
CREATE INDEX idx_cart_items_updated ON cart_items(updated_at);

-- ════════════════════════════════════════════════════════════════
-- Engagement
-- ════════════════════════════════════════════════════════════════

CREATE TABLE reviews (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT NOT NULL REFERENCES products(id),
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title       TEXT,
    body        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_reviews_product ON reviews(product_id);
CREATE INDEX idx_reviews_customer ON reviews(customer_id);
CREATE INDEX idx_reviews_rating ON reviews(product_id, rating);

CREATE TABLE promotions (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL,
    promo_type  TEXT NOT NULL,
    value       NUMERIC(10,2) NOT NULL,
    min_order   NUMERIC(10,2) NOT NULL DEFAULT 0,
    max_uses    INT,
    uses        INT NOT NULL DEFAULT 0,
    starts_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ends_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_promotions_code ON promotions(code);

CREATE TABLE coupon_redemptions (
    id              BIGSERIAL PRIMARY KEY,
    promotion_id    INT NOT NULL REFERENCES promotions(id),
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    customer_id     BIGINT NOT NULL REFERENCES customers(id),
    discount_amount NUMERIC(10,2) NOT NULL,
    redeemed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_redemptions_promotion ON coupon_redemptions(promotion_id);
CREATE INDEX idx_redemptions_order ON coupon_redemptions(order_id);
CREATE INDEX idx_redemptions_customer ON coupon_redemptions(customer_id);

-- ════════════════════════════════════════════════════════════════
-- Operational (append-only, start empty)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE search_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT,
    query           TEXT NOT NULL,
    results_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_search_log_session ON search_log(session_id);
CREATE INDEX idx_search_log_created ON search_log(created_at);

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id   BIGINT NOT NULL,
    action      TEXT NOT NULL,
    actor_id    BIGINT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_actor ON audit_log(actor_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);

COMMIT;

-- (pg_trgm extension created at top of file)

-- ════════════════════════════════════════════════════════════════
-- SEED DATA — all pure SQL, no external files
-- ════════════════════════════════════════════════════════════════

-- Categories (500 rows — 25 top-level × 20 subcategories)
\echo 'Seeding categories...'
INSERT INTO categories (parent_id, name, slug, position)
SELECT NULL,
       'Category ' || g,
       'category-' || g,
       g
FROM generate_series(1, 25) g;

INSERT INTO categories (parent_id, name, slug, position)
SELECT c.id,
       c.name || ' Sub ' || s,
       c.slug || '-sub-' || s,
       s
FROM categories c, generate_series(1, 19) s
WHERE c.parent_id IS NULL;

-- Customers (1M rows)
\echo 'Seeding 1M customers...'
INSERT INTO customers (email, name, last_login, created_at)
SELECT
    'user' || g || '@example.com',
    'Customer ' || g,
    now() - (random() * interval '365 days'),
    now() - (random() * interval '730 days')
FROM generate_series(1, 1000000) g;

-- Addresses (2M rows — ~2 per customer)
\echo 'Seeding 2M addresses...'
INSERT INTO addresses (customer_id, addr_type, line1, city, state, zip, is_default)
SELECT
    (g % 1000000) + 1,
    CASE WHEN g % 3 = 0 THEN 'billing' ELSE 'shipping' END,
    (100 + (random() * 9900)::int) || ' ' ||
        (ARRAY['Main','Oak','Elm','Park','Cedar','Pine','Maple','Hill','Lake','River'])[1 + (random()*9)::int] || ' St',
    (ARRAY['Portland','Seattle','Austin','Denver','Chicago','Boston','Miami','Atlanta','Dallas','Phoenix'])[1 + (random()*9)::int],
    (ARRAY['OR','WA','TX','CO','IL','MA','FL','GA','TX','AZ'])[1 + (random()*9)::int],
    lpad((10000 + (random() * 89999)::int)::text, 5, '0'),
    g % 2 = 0
FROM generate_series(1, 2000000) g;

-- Products (100K rows)
\echo 'Seeding 100K products...'
INSERT INTO products (category_id, name, slug, description, base_price, status, created_at)
SELECT
    1 + (random() * 499)::int,
    'Product ' || g || ' ' || (ARRAY['Widget','Gadget','Tool','Device','Kit','Pack','Set','Bundle','Pro','Elite'])[1 + (random()*9)::int],
    'product-' || g,
    'Description for product ' || g || '. High quality item with great reviews.',
    (5 + random() * 495)::numeric(10,2),
    CASE WHEN random() < 0.9 THEN 'active' ELSE 'discontinued' END,
    now() - (random() * interval '1095 days')
FROM generate_series(1, 100000) g;

-- Product Variants (300K rows — ~3 per product)
\echo 'Seeding 300K product variants...'
INSERT INTO product_variants (product_id, sku, name, price_override, weight_grams)
SELECT
    ((g - 1) / 3) + 1,
    'SKU-' || lpad(g::text, 8, '0'),
    (ARRAY['Small','Medium','Large'])[1 + (g % 3)] || ' ' ||
        (ARRAY['Red','Blue','Black','White','Green'])[1 + (random()*4)::int],
    CASE WHEN random() < 0.3 THEN (5 + random() * 495)::numeric(10,2) ELSE NULL END,
    (100 + (random() * 5000)::int)
FROM generate_series(1, 300000) g;

-- Inventory (300K rows — 1 per variant)
\echo 'Seeding 300K inventory rows...'
INSERT INTO inventory (variant_id, warehouse_id, qty_available, qty_reserved, updated_at)
SELECT
    g,
    1 + (g % 3),
    (random() * 500)::int,
    (random() * 20)::int,
    now() - (random() * interval '30 days')
FROM generate_series(1, 300000) g;

-- Price History (700K rows)
\echo 'Seeding 700K price history rows...'
INSERT INTO price_history (variant_id, old_price, new_price, changed_at)
SELECT
    1 + (random() * 299999)::int,
    (5 + random() * 495)::numeric(10,2),
    (5 + random() * 495)::numeric(10,2),
    now() - (random() * interval '365 days')
FROM generate_series(1, 700000) g;

-- Orders (5M rows)
\echo 'Seeding 5M orders (this takes a minute)...'
INSERT INTO orders (customer_id, address_id, status, subtotal, tax, shipping, total, placed_at, updated_at)
SELECT
    1 + (random() * 999999)::int,
    1 + (random() * 1999999)::int,
    (ARRAY['pending','processing','shipped','delivered','cancelled'])[1 + (random()*4)::int],
    subtotal,
    (subtotal * 0.08)::numeric(10,2),
    CASE WHEN subtotal > 50 THEN 0 ELSE 7.99 END,
    (subtotal + subtotal * 0.08 + CASE WHEN subtotal > 50 THEN 0 ELSE 7.99 END)::numeric(12,2),
    now() - (random() * interval '365 days'),
    now() - (random() * interval '365 days')
FROM (
    SELECT g, (10 + random() * 490)::numeric(12,2) AS subtotal
    FROM generate_series(1, 5000000) g
) sub;

-- Order Items (15M rows — ~3 per order)
\echo 'Seeding 15M order items (this takes a few minutes)...'
INSERT INTO order_items (order_id, variant_id, qty, unit_price, line_total)
SELECT
    ((g - 1) / 3) + 1,
    1 + (random() * 299999)::int,
    1 + (random() * 4)::int,
    unit_price,
    (qty * unit_price)::numeric(12,2)
FROM (
    SELECT g,
           (1 + (random() * 4)::int) AS qty,
           (5 + random() * 195)::numeric(10,2) AS unit_price
    FROM generate_series(1, 15000000) g
) sub;

-- Payments (5M rows — 1 per order)
\echo 'Seeding 5M payments...'
INSERT INTO payments (order_id, method, status, amount, gateway_txn_id, created_at, settled_at)
SELECT
    g,
    (ARRAY['credit_card','debit_card','paypal','apple_pay','bank_transfer'])[1 + (random()*4)::int],
    (ARRAY['pending','captured','settled','refunded','failed'])[1 + (random()*4)::int],
    (10 + random() * 500)::numeric(12,2),
    'txn_' || encode(g::text || random()::text),
    now() - (random() * interval '365 days'),
    CASE WHEN random() < 0.7 THEN now() - (random() * interval '360 days') ELSE NULL END
FROM generate_series(1, 5000000) g;

-- Shipments (4M rows — ~80% of orders)
\echo 'Seeding 4M shipments...'
INSERT INTO shipments (order_id, carrier, tracking_number, status, shipped_at, delivered_at)
SELECT
    g,
    (ARRAY['ups','fedex','usps','dhl'])[1 + (random()*3)::int],
    upper(encode(g::text || random()::text)),
    (ARRAY['label_created','in_transit','out_for_delivery','delivered','returned'])[1 + (random()*4)::int],
    now() - (random() * interval '365 days'),
    CASE WHEN random() < 0.6 THEN now() - (random() * interval '360 days') ELSE NULL END
FROM generate_series(1, 4000000) g;

-- Sessions (100K active)
\echo 'Seeding 100K sessions...'
INSERT INTO sessions (customer_id, token, ip_addr, user_agent, last_active, expires_at)
SELECT
    CASE WHEN random() < 0.7 THEN 1 + (random() * 999999)::int ELSE NULL END,
    encode(g::text || random()::text) || md5(random()::text),
    ('10.' || (random()*255)::int || '.' || (random()*255)::int || '.' || (random()*255)::int)::inet,
    (ARRAY[
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)',
        'Mozilla/5.0 (Linux; Android 14)',
        'Mozilla/5.0 (X11; Linux x86_64)'
    ])[1 + (random()*4)::int],
    now() - (random() * interval '24 hours'),
    now() + (random() * interval '24 hours')
FROM generate_series(1, 100000) g;

-- Reviews (2M rows)
\echo 'Seeding 2M reviews...'
INSERT INTO reviews (product_id, customer_id, rating, title, body, created_at)
SELECT
    1 + (random() * 99999)::int,
    1 + (random() * 999999)::int,
    1 + (random() * 4)::int,
    'Review ' || g,
    'This product is ' || (ARRAY['excellent','great','good','okay','disappointing'])[1 + (random()*4)::int] || '. Would ' || (ARRAY['definitely','probably','maybe','not'])[1 + (random()*3)::int] || ' recommend.',
    now() - (random() * interval '730 days')
FROM generate_series(1, 2000000) g;

-- Promotions (1K rows)
\echo 'Seeding 1K promotions...'
INSERT INTO promotions (code, promo_type, value, min_order, max_uses, uses, starts_at, ends_at)
SELECT
    upper('PROMO' || lpad(g::text, 4, '0')),
    (ARRAY['percentage','fixed','free_shipping'])[1 + (random()*2)::int],
    CASE WHEN random() < 0.5 THEN (5 + random() * 30)::numeric(10,2) ELSE (5 + random() * 50)::numeric(10,2) END,
    (20 + random() * 80)::numeric(10,2),
    (100 + (random() * 9900)::int),
    (random() * 50)::int,
    now() - (random() * interval '180 days'),
    now() + (random() * interval '180 days')
FROM generate_series(1, 1000) g;

-- Coupon Redemptions (500K rows)
\echo 'Seeding 500K coupon redemptions...'
INSERT INTO coupon_redemptions (promotion_id, order_id, customer_id, discount_amount, redeemed_at)
SELECT
    1 + (random() * 999)::int,
    1 + (random() * 4999999)::int,
    1 + (random() * 999999)::int,
    (2 + random() * 48)::numeric(10,2),
    now() - (random() * interval '365 days')
FROM generate_series(1, 500000) g;

-- ════════════════════════════════════════════════════════════════
-- Update statistics
-- ════════════════════════════════════════════════════════════════
\echo 'Running ANALYZE...'
ANALYZE;

\echo 'Done! Schema seeded successfully.'
\echo 'Expected size: ~10 GB'
