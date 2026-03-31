# Schema

18-table e-commerce OLTP schema. Seeded with ~30M rows (~10 GB) via pure SQL.

## Table Map

```
customers (1M)
├── addresses (2M)                 1:N, shipping/billing
├── orders (5M)                    1:N
│   ├── order_items (15M)          1:N → product_variants
│   ├── payments (5M)              1:N, credit_card/paypal/apple_pay
│   └── shipments (4M)             1:N, ups/fedex/usps/dhl
├── reviews (2M)                   1:N → products
└── sessions (100K)                N:1, token-based
    └── cart_items (dynamic)       1:N → product_variants

categories (500)                   Hierarchical (self-ref)
└── products (100K)                1:N
    └── product_variants (300K)    1:N, SKU-based
        ├── inventory (300K)       1:1, qty_available/reserved
        └── price_history (700K)   1:N, old/new price log

promotions (1K)
└── coupon_redemptions (500K)      1:N → orders, customers

search_log (append-only)           Session search queries
audit_log (append-only)            Entity changes, JSONB metadata
```

## Key Indexes

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| customers | `idx_customers_email` | unique | Login lookup |
| products | `idx_products_name_trgm` | GIN (pg_trgm) | Full-text search |
| products | `idx_products_slug` | unique | URL routing |
| product_variants | `idx_variants_sku` | unique | Cart/order resolution |
| inventory | `idx_inventory_low_stock` | partial (`< 10`) | Low stock alerts |
| orders | `idx_orders_customer_placed` | composite DESC | Order history pagination |
| sessions | `idx_sessions_token` | unique | Session lookup |
| search_log | `idx_search_log_created` | btree | Time-based cleanup |
| audit_log | `idx_audit_log_created` | btree | Time-based cleanup |

## Append-Only Tables

These grow unbounded during stress tests. The dashboard safety monitor prunes them:

| Table | Default Limit | Prune Target |
|-------|---------------|-------------|
| search_log | 5M rows | 70% of limit |
| audit_log | 5M rows | 70% of limit |
| price_history | 2M rows | 70% of limit |
| cart_items | 1M rows | 70% of limit |
| reviews | 5M rows | 70% of limit |
