-- pgbench custom script: e-commerce reporting pattern
-- Simulates analytics queries (comparable to load-generator reporting ops)

\set customer_id random(1, 1000000)

-- Hourly sales report (last 7 days).
SELECT date_trunc('hour', placed_at) AS hour,
       count(*) AS order_count,
       sum(total) AS revenue,
       avg(total) AS avg_order_value
FROM orders
WHERE placed_at > now() - interval '7 days'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 168;

-- Top products by revenue (last 30 days).
SELECT p.id, p.name, count(oi.id) AS units_sold, sum(oi.line_total) AS revenue
FROM order_items oi
JOIN product_variants pv ON pv.id = oi.variant_id
JOIN products p ON p.id = pv.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.placed_at > now() - interval '30 days'
GROUP BY p.id, p.name
ORDER BY revenue DESC
LIMIT 25;

-- Customer lifetime value.
SELECT c.id, c.name,
       count(o.id) AS total_orders,
       coalesce(sum(o.total), 0) AS lifetime_value,
       min(o.placed_at) AS first_order,
       max(o.placed_at) AS last_order
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE c.id = :customer_id
GROUP BY c.id;
