# Scenarios

## Use Case 1: BYOD (Bring Your Own Data)

Dump production, restore on test server, run your own queries under stress.

### 1. Dump and Restore

```bash
# On production server
pg_dump --format=custom --jobs=4 mydb > /tmp/mydb.dump

# On test server
make import DUMP=/tmp/mydb.dump
# → pg_restore + ANALYZE + baseline snapshot
```

### 2. Provide Your Queries

Place your application's SQL in `workloads/byod/queries/`:

```
workloads/byod/queries/
├── read-heavy.sql        # SELECT queries your app runs most
├── writes.sql            # INSERT/UPDATE patterns
├── reports.sql           # Aggregation / analytics queries
└── transactions.sql      # Multi-statement transactions (BEGIN/COMMIT)
```

Each file uses pgbench syntax (`\set`, `\sleep`, `$variables`):

```sql
-- workloads/byod/queries/read-heavy.sql
\set customer_id random(1, 1000000)
\set product_id random(1, 500000)

SELECT * FROM customers WHERE id = :customer_id;
SELECT * FROM orders WHERE customer_id = :customer_id ORDER BY created_at DESC LIMIT 20;
SELECT * FROM products WHERE id = :product_id;
```

### 3. Run

```bash
make stress                        # Default: 10 clients, 5 min
make stress CLIENTS=50 DURATION=600  # 50 clients, 10 min
```

### 4. Get Advisory

```bash
make analyze                       # Full Claude analysis
```

---

## Use Case 2: WHAT IF (Inject Stress on Real Data)

You have production data restored. Now test hypotheses.

### Row Injection

```bash
# "What happens when orders grows by 10M rows?"
make inject TABLE=orders ROWS=10000000

# "What if search_log hits 50M?"
make inject TABLE=search_log ROWS=50000000

# Custom INSERT template
make inject TABLE=orders ROWS=5000000 \
  TEMPLATE="INSERT INTO orders (customer_id, status, total, placed_at) \
            SELECT (random()*1000000)::int, 'pending', (random()*500)::numeric(10,2), now() - random()*interval '365 days' \
            FROM generate_series(1, {batch})"
```

### Bulk Updates

```bash
# "What if we update 20M records?"
make bulk-update TABLE=orders SET="status='archived'" \
  WHERE="placed_at < now() - interval '1 year'" BATCH=100000
```

### Connection Pressure

```bash
# "What happens at 100 concurrent connections?"
make connections N=100 DURATION=300

# "What about 200 with mixed read/write?"
make connections N=200 DURATION=600 MODE=mixed
```

### Growth Ladder (Find Breaking Point)

```bash
# Ramp connections: 10 → 25 → 50 → 100 → 200
# Each phase runs 3 minutes, captures snapshot between phases
make ladder STEPS="10,25,50,100,200" PHASE_DURATION=180
```

Output per phase:

```
Phase    Conns  TPS    Cache Ratio  p99 Latency  Deadlocks  Temp Files
─────    ─────  ───    ───────────  ───────────  ─────────  ──────────
1x       10     2340   0.998        45ms         0          0
2.5x     25     4200   0.994        67ms         0          0
5x       50     5100   0.971        189ms        2          0
10x      100    4800   0.923        487ms        14         847        ← BREAKING
20x      200    2100   0.841        2340ms       89         4200       ← DEGRADED
```

Claude receives this table and identifies:
- Cache cliff between 50-100 connections
- Deadlock onset at 100 connections
- Temp file spills at 100 connections → work_mem too low
- TPS peaks at 50 connections → diminishing returns after that

### Combine WHAT IFs

```bash
# Inject 10M rows THEN stress with 100 connections
make inject TABLE=orders ROWS=10000000
make stress CLIENTS=100 DURATION=600
make analyze
```

---

## Use Case 3: Seed + Stress (No Production Data)

You need synthetic data at target volume. Pick a workload profile.

### Built-In Profiles

| Profile | Tables | Seed Size | Description |
|---------|--------|-----------|-------------|
| `ecommerce` | 18 | ~30M rows / 10 GB | Orders, products, carts, reviews, payments |
| `crm` | 12 | ~20M rows / 6 GB | Contacts, accounts, deals, activities, notes |
| `saas-multi-tenant` | 15 | ~25M rows / 8 GB | Tenants, users, resources, audit, billing |
| `iot-timeseries` | 6 | ~50M rows / 12 GB | Devices, readings, alerts, aggregates |
| `content-platform` | 14 | ~35M rows / 9 GB | Users, posts, comments, feeds, notifications |

```bash
# Seed e-commerce (current default)
make seed PROFILE=ecommerce

# Seed CRM at 2x default volume
make seed PROFILE=crm SCALE=2

# Seed IoT timeseries
make seed PROFILE=iot-timeseries

# Then stress
make stress CLIENTS=50 DURATION=600
make analyze
```

### Custom Seed

Provide your own schema and seed SQL:

```bash
# Place files in workloads/custom/
workloads/custom/
├── schema.sql            # CREATE TABLE statements
├── seed.sql              # INSERT / generate_series data
└── queries/              # Query patterns for stress
    ├── reads.sql
    └── writes.sql

make seed PROFILE=custom
make stress
```

---

## Scenario YAML (Advanced)

For repeatable, documented test plans:

```yaml
# scenarios/pre-blackfriday.yaml
name: Pre-Black Friday Stress Test
description: Test production data under 3x holiday traffic

import:
  dump: /data/production-2026-03-28.dump

what_if:
  inject:
    - { table: orders, rows: 5000000 }
    - { table: search_log, rows: 10000000 }
  connections: 100
  duration: 30m

analyze:
  focus: [tuning, queries, capacity]
  questions:
    - "Can we handle 3x checkout traffic without deadlocks?"
    - "Should we partition search_log before the event?"
```

```bash
make run SCENARIO=pre-blackfriday
# → import, inject, stress, capture, analyze — all in one
```
