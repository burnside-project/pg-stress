# Scenarios

Scenarios define hypothetical growth conditions. Each answers a "what if?" question.

## Built-In Profiles

| Scenario | Burst Conns | Chaos | Pause | ORM Threads | DB Limit |
|----------|-------------|-------|-------|-------------|----------|
| `gentle` | 3 / 8 / 15 | off | 30-120s | 2 | 15 GB |
| `default` | 5 / 20 / 50 | 25% | 20-90s | 5 | 20 GB |
| `heavy` | 15 / 40 / 80 | 50% | 5-20s | 15 | 30 GB |

```bash
SCENARIO=heavy make up-full     # Use heavy profile
```

## Traffic Multipliers

Scale load relative to a baseline. The growth ladder finds breaking points:

```yaml
# scenarios/growth-ladder.yaml
name: Growth Ladder
phases:
  - { name: baseline, traffic_multiplier: 1.0, duration: 5m }
  - { name: "10%",    traffic_multiplier: 1.1, duration: 5m }
  - { name: "50%",    traffic_multiplier: 1.5, duration: 5m }
  - { name: "2x",     traffic_multiplier: 2.0, duration: 5m }
  - { name: "5x",     traffic_multiplier: 5.0, duration: 5m }
```

The analyzer receives per-phase snapshots and identifies:

- At what multiplier does cache hit ratio drop below 0.95?
- At what multiplier do temp files appear?
- At what multiplier do deadlocks spike?

## Row Injection

Simulate table growth without waiting for it to happen organically:

```yaml
# scenarios/black-friday.yaml
name: Black Friday
traffic_multiplier: 3.0
duration: 30m
ramp_up: 5m
inject_rows:
  orders: 2000000          # +2M orders
  order_items: 6000000     # +6M items
  search_log: 5000000      # search traffic spike
```

## Schema Change Simulation

Test a migration before applying it to production:

```yaml
# scenarios/schema-migration.yaml
name: Pre-Migration Test
pre_test:
  - "ALTER TABLE orders ADD COLUMN metadata JSONB"
  - "CREATE INDEX idx_orders_metadata ON orders USING gin (metadata)"
traffic_multiplier: 1.0
duration: 15m
```

## Three Load Sources

Every scenario exercises all three query sources simultaneously:

| Source | Language | Fingerprints | Pattern |
|--------|----------|-------------|---------|
| Raw SQL | Go + pgx | ~30-40 `queryid` | Hand-written JOINs, explicit columns |
| ORM | Python + SQLAlchemy | ~50-100+ `queryid` | N+1, eager load, EXISTS, RETURNING |
| pgbench | PostgreSQL built-in | ~5-15 `queryid` | TPC-B + custom e-commerce scripts |

> **Why three?** Production databases serve multiple application tiers.
> pg-stress reproduces this to validate that monitoring tools correctly
> differentiate workloads by query fingerprint.
