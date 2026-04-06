-- Checkout flow: load order with customer and items
SELECT o.id, o.status, o.total, o.placed_at,
       c.id AS customer_id,
       a.id AS address_id
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN addresses a ON o.address_id = a.id
WHERE o.id = (SELECT id FROM orders ORDER BY random() LIMIT 1)
