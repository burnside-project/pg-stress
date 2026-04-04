# Schema Introspection

pg-stress discovers your schema at startup. No configuration required.

## What Gets Discovered

```
introspect_schema(engine)
│
├── Tables
│   ├── Name, row count, size (from pg_stat_user_tables)
│   ├── Columns: name, type, nullable, default, serial
│   ├── Primary keys
│   ├── Foreign keys → target table.column
│   └── Indexes: name, columns, unique, type (btree/gin/gist)
│
├── Relationships (from FK constraints)
│   ├── Parent → child mappings
│   ├── FK chains: [customers, orders, order_items] (depth 2-4)
│   └── Self-references detected (hierarchical tables)
│
├── Column Classification
│   ├── Timestamps: created_at, updated_at, placed_at, ...
│   ├── Numeric: int, numeric, decimal, float
│   ├── Text: text, varchar, char
│   ├── JSONB: jsonb, json
│   └── Status: columns named status, state, type, kind, role
│
└── Table Classification
    ├── entity: has FK children + timestamps (customers, products)
    ├── transactional: has status + updated_at (orders, payments)
    ├── append_only: only created_at, no updates (logs, events)
    ├── lookup: small, no FK children (categories, config)
    └── hierarchical: self-referencing FK (categories with parent_id)
```

## How Classification Drives Load

| Classification | Operations Applied |
|---|---|
| **entity** | N+1, eager load, EXISTS filter, relationship JOIN |
| **transactional** | ORM update (status transitions), pagination, aggregation |
| **append_only** | Bulk INSERT (clone rows), time-range pagination |
| **lookup** | Read-only via eager load and JOIN |
| **hierarchical** | Tree traversal via self-referencing relationships |

## FK Chains

The introspector walks the FK graph to find chains of depth 2+:

```
customers → orders → order_items → product_variants
            │
            └── payments
            └── shipments

products → product_variants → inventory
```

These chains drive:
- **N+1 pattern:** Load parent, lazy-load each child (1 + N queries)
- **Eager joinedload:** Single SELECT with LEFT OUTER JOINs
- **Eager subqueryload:** Base SELECT + IN (subquery) for children
- **Eager selectinload:** Base SELECT + IN ($1, $2, ..., $N) literal list

## CLI Usage

You can run introspection standalone against the local container:

```bash
# Dump introspection profile to stdout (connects to the local container)
PG_CONN=postgresql://postgres:postgres@localhost:5434/my_production_db \
  python load-generator-orm/introspect.py

# Save to file
python load-generator-orm/introspect.py --output profile.json
```

Output:

```json
{
  "database": "production_db",
  "total_tables": 42,
  "total_rows": 18500000,
  "total_size": "12 GB",
  "classification": {
    "entity": ["customers", "products", "tenants"],
    "transactional": ["orders", "payments", "shipments"],
    "append_only": ["audit_log", "events", "search_log"],
    "lookup": ["categories", "regions", "currencies"],
    "hierarchical": ["categories"]
  },
  "relationships": [
    {"parent": "customers", "child": "orders", "via": "customer_id"},
    {"parent": "orders", "child": "order_items", "via": "order_id"}
  ],
  "fk_chains": [
    {"tables": ["customers", "orders", "order_items"], "depth": 3},
    {"tables": ["products", "variants", "inventory"], "depth": 3}
  ],
  "max_ids": {
    "customers": 1200000,
    "orders": 5400000
  }
}
```
