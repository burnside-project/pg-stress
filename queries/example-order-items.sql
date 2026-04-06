-- Order items with product details
SELECT oi.id, oi.quantity, oi.line_total,
       pv.sku, pv.name AS variant_name,
       p.name AS product_name
FROM order_items oi
JOIN product_variants pv ON oi.variant_id = pv.id
JOIN products p ON pv.product_id = p.id
WHERE oi.order_id = (SELECT id FROM orders ORDER BY random() LIMIT 1)
