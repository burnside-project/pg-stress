-- pgbench custom script: e-commerce checkout pattern
-- Simulates a checkout transaction (comparable to load-generator checkout ops)

\set customer_id random(1, 1000000)
\set address_id random(1, 2000000)
\set variant_id random(1, 300000)
\set qty random(1, 3)

BEGIN;

-- Lock inventory row.
SELECT qty_available FROM inventory WHERE variant_id = :variant_id FOR UPDATE;

-- Decrement inventory.
UPDATE inventory SET qty_available = qty_available - :qty,
                     qty_reserved = qty_reserved + :qty,
                     updated_at = now()
WHERE variant_id = :variant_id AND qty_available >= :qty;

-- Get variant price.
SELECT coalesce(pv.price_override, p.base_price) AS price
FROM product_variants pv
JOIN products p ON p.id = pv.product_id
WHERE pv.id = :variant_id;

-- Create order.
INSERT INTO orders (customer_id, address_id, status, subtotal, tax, shipping, total)
VALUES (:customer_id, :address_id, 'pending', 99.99, 8.00, 0, 107.99)
RETURNING id;

COMMIT;
