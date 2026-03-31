-- pgbench custom script: e-commerce browse pattern
-- Simulates product catalog browsing (comparable to load-generator browse ops)

\set cat_id random(1, 500)
\set product_id random(1, 100000)
\set offset random(0, 20) * 48

-- Category listing with review aggregation.
SELECT p.id, p.name, p.base_price,
       coalesce(avg(r.rating), 0) AS avg_rating,
       count(r.id) AS review_count
FROM products p
LEFT JOIN reviews r ON r.product_id = p.id
WHERE p.category_id = :cat_id AND p.status = 'active'
GROUP BY p.id
ORDER BY p.created_at DESC
LIMIT 48 OFFSET :offset;

-- Product detail with variants and inventory.
SELECT p.id, p.name, p.base_price, p.description,
       v.id AS variant_id, v.sku, v.name AS variant_name,
       coalesce(v.price_override, p.base_price) AS price,
       i.qty_available
FROM products p
JOIN product_variants v ON v.product_id = p.id
JOIN inventory i ON i.variant_id = v.id
WHERE p.id = :product_id;
