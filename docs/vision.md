# pg-stress Vision: One-Off Local Stress Test → LLM Advisory

## The Idea

You have a production PostgreSQL database. You want answers to:

- "What happens if traffic grows 50%?"
- "Which queries break first at 2x load?"
- "What PostgreSQL knobs should we turn before Black Friday?"
- "Is our indexing strategy ready for 10M more rows?"
- "Where are the hidden N+1 patterns the ORM is generating?"

pg-stress answers these by running **one-off, local-only stress tests** against
a copy of your production data, then feeding the complete results to an LLM
for expert advisory.

## pg-stress vs pg-collector

| | pg-stress | pg-collector |
|---|---|---|
| **When** | One-off, before a change or event | Always running |
| **Where** | Test server (local, disposable) | Production |
| **Data** | Production dump + synthetic load | Live production queries |
| **Purpose** | "What if?" predictions | "What is?" observation |
| **Output** | LLM-optimized context → advisory report | Metric time-series → dashboards |
| **Lifecycle** | Run once, get report, tear down | Continuous telemetry |
| **Risk** | Zero (test server) | None (read-only observer) |

They're complementary:
- pg-collector tells you what IS happening
- pg-stress tells you what WILL happen

## The Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCTION SERVER                         │
│                                                             │
│  pg_dump --format=custom --jobs=4 production_db > dump.sql  │
│                                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                     dump file
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     TEST SERVER (ssh 4)                      │
│                                                             │
│  Phase 1: IMPORT                                            │
│  ├── pg_restore production dump                             │
│  ├── Snapshot baseline (pg_stat_*, sizes, indexes)          │
│  └── ANALYZE all tables                                     │
│                                                             │
│  Phase 2: STRESS                                            │
│  ├── Run scenario: "50% traffic increase"                   │
│  │   ├── Replay production query patterns at 1.5x rate      │
│  │   ├── OR: Run synthetic OLTP at calibrated intensity     │
│  │   ├── OR: Inject hypothetical growth (10M more rows)     │
│  │   └── Duration: 10-30 minutes                            │
│  ├── Capture snapshots every 30s during test                │
│  └── Record all anomalies (deadlocks, temp spills, waits)   │
│                                                             │
│  Phase 3: CAPTURE                                           │
│  ├── Final pg_stat_statements (full, not top-N)             │
│  ├── Table stats (dead tuples, vacuum state, bloat)         │
│  ├── Index usage (unused, missing, bloated)                 │
│  ├── Lock history and wait events                           │
│  ├── PG settings + hardware profile                         │
│  ├── Before/after deltas for everything                     │
│  └── Package as LLM-optimized context bundle                │
│                                                             │
│  Phase 4: ADVISE                                            │
│  ├── Send context bundle to Claude                          │
│  ├── Get: query fixes, knob tuning, index changes           │
│  ├── Get: capacity predictions + breaking points            │
│  └── Save report as Markdown                                │
│                                                             │
│  Phase 5: TEARDOWN                                          │
│  └── Drop test database, reclaim space                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Hypothetical Scenarios

The key differentiator: pg-stress doesn't just replay current traffic.
It answers **"what if?"** questions:

### Traffic Multipliers

```yaml
# scenario: black-friday.yaml
name: Black Friday Simulation
base: production           # Start from production data
growth:
  traffic_multiplier: 3.0  # 3x current query rate
  duration: 30m
  ramp_up: 5m              # Gradual ramp from 1x to 3x

  # Table-specific growth injection
  inject_rows:
    orders: 2000000        # Add 2M orders during test
    order_items: 6000000   # 3 items per order
    search_log: 5000000    # Search traffic spike
    cart_items: 500000     # Cart activity spike
```

### Graduated Stress Levels

```yaml
# scenario: growth-ladder.yaml
name: Growth Ladder (find breaking point)
phases:
  - name: baseline
    traffic_multiplier: 1.0
    duration: 5m

  - name: "10% growth"
    traffic_multiplier: 1.1
    duration: 5m

  - name: "25% growth"
    traffic_multiplier: 1.25
    duration: 5m

  - name: "50% growth"
    traffic_multiplier: 1.5
    duration: 5m

  - name: "100% growth (2x)"
    traffic_multiplier: 2.0
    duration: 5m

  - name: "stress limit (5x)"
    traffic_multiplier: 5.0
    duration: 5m

# LLM receives per-phase snapshots and identifies:
# - At what multiplier does cache hit ratio drop below 0.95?
# - At what multiplier do temp files appear?
# - At what multiplier do deadlocks spike?
# - What is the TPS ceiling before latency degrades?
```

### Schema Change Simulation

```yaml
# scenario: schema-migration.yaml
name: Pre-Migration Stress Test
pre_test:
  - "ALTER TABLE orders ADD COLUMN metadata JSONB"
  - "CREATE INDEX idx_orders_metadata ON orders USING gin (metadata)"
  - "UPDATE orders SET metadata = '{\"source\": \"web\"}' WHERE random() < 0.1"

traffic_multiplier: 1.0    # Same as production
duration: 15m

# LLM answers: "Does the new JSONB column + GIN index affect
# existing query performance? What's the storage impact?"
```

### Specific Table Stress

```yaml
# scenario: search-pressure.yaml
name: Search Log Growth Test
description: "What happens when search_log hits 50M rows?"

inject_rows:
  search_log: 45000000     # Inject 45M rows (on top of existing ~5M)

traffic_multiplier: 1.5
focus_tables:
  - search_log
  - sessions
  - products                # Search queries hit products table

# LLM answers: "At 50M rows, does the search_log index still work?
# What's the autovacuum impact? Should we partition?"
```

## LLM-Optimized Context Bundle

The output of the capture phase is structured specifically for LLM consumption.
Not a raw dump — a curated, annotated context that maximizes signal per token:

```json
{
  "test_metadata": {
    "scenario": "black-friday",
    "duration_minutes": 30,
    "traffic_multiplier": 3.0,
    "production_db_size": "47 GB",
    "test_server": { "cpu": 8, "memory_gb": 32, "storage": "NVMe SSD" }
  },

  "before_snapshot": {
    "timestamp": "2026-03-31T10:00:00Z",
    "database_size_bytes": 50331648000,
    "total_connections": 12,
    "cache_hit_ratio": 0.9987,
    "tables": { "...per-table stats..." },
    "top_queries": [ "...baseline query stats..." ]
  },

  "after_snapshot": {
    "timestamp": "2026-03-31T10:30:00Z",
    "database_size_bytes": 52428800000,
    "total_connections": 45,
    "cache_hit_ratio": 0.9234,
    "tables": { "...per-table stats..." },
    "top_queries": [ "...post-stress query stats..." ]
  },

  "deltas": {
    "database_size_growth_bytes": 2097152000,
    "cache_hit_ratio_drop": -0.0753,
    "new_deadlocks": 14,
    "new_temp_files": 2847,
    "queries_degraded": [
      {
        "queryid": "0x1a2b3c",
        "query_text": "SELECT ... FROM orders JOIN ...",
        "mean_ms_before": 12.3,
        "mean_ms_after": 487.2,
        "degradation_factor": 39.6,
        "likely_source": "ORM (SQLAlchemy joinedload)",
        "root_cause": "seq_scan on orders after cache pressure"
      }
    ]
  },

  "per_phase_snapshots": [
    { "phase": "baseline (1x)", "tps": 2340, "cache_ratio": 0.998, "p99_ms": 45 },
    { "phase": "1.5x", "tps": 3200, "cache_ratio": 0.991, "p99_ms": 78 },
    { "phase": "3x", "tps": 4100, "cache_ratio": 0.923, "p99_ms": 487 }
  ],

  "anomalies": [
    { "time": "+12m", "type": "cache_cliff", "detail": "cache_hit_ratio dropped from 0.99 to 0.92 in 30s" },
    { "time": "+18m", "type": "temp_spill", "detail": "reporting query started spilling 847 temp files" },
    { "time": "+23m", "type": "lock_storm", "detail": "14 deadlocks in checkout path within 2 minutes" }
  ],

  "postgresql_config": {
    "shared_buffers": "256MB",
    "work_mem": "16MB",
    "effective_cache_size": "1GB",
    "...": "..."
  },

  "questions_for_llm": [
    "At 3x traffic, cache hit ratio dropped to 0.92. What shared_buffers value prevents this?",
    "14 deadlocks in checkout path. Is this a query design issue or a tuning issue?",
    "search_log grew 2GB in 30 minutes. Should we partition by date?",
    "The ORM joinedload query degraded 40x. Should we switch to selectinload or raw SQL?"
  ]
}
```

## Key Design Principles

### 1. Production Data, Not Synthetic

The current schema.sql seeds synthetic data. For real advisory, you need
production data with real distributions, real skew, real index bloat.

```bash
# On production:
pg_dump --format=custom --jobs=4 production_db > /tmp/production.dump

# On test server:
pg_restore --jobs=4 --dbname=testdb /tmp/production.dump
ANALYZE;
```

### 2. Test Server Is Disposable

The test server is meant to be hammered and thrown away:
- No concern about data corruption
- Can run destructive experiments (DROP INDEX, ALTER TABLE)
- Can push past safe limits to find breaking points
- Clean slate for each test run

### 3. Output Is for LLMs, Not Dashboards

pg-collector outputs time-series for Grafana.
pg-stress outputs context bundles for Claude.

Every piece of data is annotated with:
- What it means (not just raw numbers)
- What changed (before/after deltas)
- What's anomalous (automatically flagged)
- What to ask about it (pre-formulated questions)

### 4. Scenarios Are Hypothetical, Not Replay

We're not replaying production traffic. We're answering:
- "What if traffic doubles?"
- "What if we add this index?"
- "What if we change this PG setting?"
- "What if this table grows to 100M rows?"

### 5. One-Off, Not Continuous

```
Monday:   Dump production → test server
          Run "50% growth" scenario → get report
          Apply recommended changes to production

Thursday: Dump production again (with changes applied)
          Run "Black Friday 3x" scenario → get report
          Fine-tune before the event

Friday:   Production handles Black Friday
          pg-collector observes (ongoing)
```

## CLI Workflow (Target)

```bash
# 1. Import production data
make import DUMP=/path/to/production.dump

# 2. Run a growth scenario
make stress SCENARIO=growth-ladder

# 3. Get AI advisory
make advise

# 4. Or all-in-one
make test DUMP=/path/to/production.dump SCENARIO=black-friday
# → imports, stresses, captures, advises, saves report

# 5. Teardown
make teardown
```

## What the LLM Report Looks Like

```markdown
# pg-stress Advisory Report
## Black Friday Simulation (3x Traffic)

### Breaking Points Identified

1. **Cache cliff at 2.5x traffic** — shared_buffers (256MB) insufficient for
   working set at this load. Hit ratio drops from 0.998 to 0.92.
   → Increase shared_buffers to 1GB. Estimated improvement: maintains 0.99+ at 3x.

2. **Checkout deadlocks at 2x traffic** — FOR UPDATE on inventory table creates
   lock chains when >30 concurrent checkouts.
   → Add SKIP LOCKED or advisory locks. Estimated: eliminates deadlocks entirely.

3. **Reporting queries collapse at 1.5x** — Aggregation on orders table spills
   to 847 temp files due to work_mem=16MB.
   → Increase work_mem to 64MB for reporting role. Or add partial index on
   orders(placed_at) WHERE placed_at > now() - interval '7 days'.

### PostgreSQL Tuning (apply before event)

| Parameter | Current | Recommended | Why |
|-----------|---------|-------------|-----|
| shared_buffers | 256MB | 1GB | Cache cliff at 2.5x |
| work_mem | 16MB | 64MB | Temp file elimination |
| effective_cache_size | 1GB | 3GB | Planner accuracy |
| max_connections | 200 | 300 | Headroom at 3x |

### Capacity Limits

At current growth rate:
- search_log hits 50M rows in ~6 weeks → partition by month
- orders table hits 10M rows in ~3 months → still fine with current indexes
- Database reaches 100GB in ~2 months → plan storage expansion

### Action Items (ordered by impact)

1. ⚡ ALTER SYSTEM SET shared_buffers = '1GB'; (requires restart)
2. ⚡ ALTER SYSTEM SET work_mem = '64MB';
3. 🔧 Add index: CREATE INDEX CONCURRENTLY idx_orders_placed_recent ...
4. 🔧 Refactor checkout to use SKIP LOCKED
5. 📋 Plan search_log partitioning for next quarter
```
