-- Monthly revenue report
SELECT date_trunc('month', placed_at) AS month,
       count(*) AS order_count,
       sum(total) AS revenue,
       avg(total) AS avg_order_value
FROM orders
WHERE placed_at > now() - interval '12 months'
GROUP BY 1
ORDER BY 1
