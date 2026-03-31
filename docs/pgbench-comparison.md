# pgbench Comparison Strategy

## Purpose

Compare pg-collector's ability to identify and differentiate three distinct SQL workload sources
hitting the same PostgreSQL instance simultaneously:

1. **pgbench TPC-B** — Standard synthetic benchmark (known baseline)
2. **Raw SQL Load Generator** — Hand-written e-commerce OLTP (Go + pgx)
3. **ORM Load Generator** — SQLAlchemy-generated queries (Python)

The goal is to validate that pg-collector correctly fingerprints, groups, and attributes
queries from each source — a key requirement for production monitoring where workloads
from multiple application services share a single database.

---

## Three Workload Comparison Matrix

### Workload A: pgbench TPC-B (Baseline)

| Property | Value |
|----------|-------|
| **Source** | `pgbench` CLI |
| **Schema** | `pgbench_accounts`, `pgbench_branches`, `pgbench_tellers`, `pgbench_history` |
| **Query patterns** | 5 fixed statements (SELECT + UPDATE + UPDATE + UPDATE + INSERT) per transaction |
| **Fingerprint count** | ~5 unique `queryid` values |
| **Concurrency** | Configurable clients × threads |
| **Value** | Known TPS baseline, universally comparable |

**What pg-collector should see:**
- Exactly 5 `queryid` entries in `pg_stat_statements`
- Linear growth in `calls` proportional to TPS
- Uniform `mean_exec_time` per statement
- All queries targeting `pgbench_*` tables (easy to isolate)

### Workload B: Raw SQL Load Generator (Custom OLTP)

| Property | Value |
|----------|-------|
| **Source** | Go service using pgx connection pool |
| **Schema** | 18-table e-commerce (customers, orders, products, etc.) |
| **Query patterns** | ~25-30 hand-written SQL templates across 6 operation categories |
| **Fingerprint count** | ~30-40 unique `queryid` values |
| **Concurrency** | Burst-based (5-80 connections per burst) |
| **Value** | Realistic OLTP with joins, aggregations, transactions |

**What pg-collector should see:**
- 30-40 distinct `queryid` entries
- Non-uniform call distribution (browse queries dominate)
- Transaction boundaries visible in commit/rollback counts
- Chaos patterns as occasional spikes (deadlocks, bulk updates)
- Lock contention from checkout `FOR UPDATE` patterns

### Workload C: ORM Load Generator (SQLAlchemy)

| Property | Value |
|----------|-------|
| **Source** | Python service using SQLAlchemy 2.0 ORM |
| **Schema** | Same 18-table e-commerce (via ORM models) |
| **Query patterns** | 10 ORM patterns generating 50-100+ unique fingerprints |
| **Fingerprint count** | 50-100+ unique `queryid` values (much higher than raw SQL!) |
| **Concurrency** | Thread pool (2-15 threads) |
| **Value** | ORM-specific patterns that differ from raw SQL |

**What pg-collector should see:**
- Many more `queryid` entries than raw SQL for the same tables
- N+1 pattern: clusters of identical `queryid` with different params
- Eager loading: complex JOINed selects not present in raw SQL
- `SELECT ... WHERE id = $1` patterns (ORM primary key lookups)
- `INSERT ... RETURNING id` (ORM object creation)
- Correlated subqueries from `.any()` / `.has()` filters

---

## Key Metrics to Compare

### 1. Throughput (TPS)

| Metric | pgbench | Raw SQL | ORM |
|--------|---------|---------|-----|
| Transactions/sec | pgbench reports directly | `stats.checkout` (full txns) | `stats.bulk_insert` + `stats.orm_update` |
| Queries/sec | TPS × 5 | Sum of all op counters | Sum of all op counters (but more queries per op) |
| Effective query rate | Known | Measurable from healthz | Measurable from healthz |

**Key insight:** ORM generates more queries per logical operation due to lazy loading,
separate SELECTs for relationship traversal, and SELECT-before-UPDATE patterns.

### 2. Query Fingerprint Distribution

| Metric | pgbench | Raw SQL | ORM |
|--------|---------|---------|-----|
| Unique `queryid` count | ~5 | ~30-40 | ~50-100+ |
| Top 5 queries % of total time | ~100% | ~60-70% | ~30-40% |
| Fingerprint stability | Fixed | Fixed | Variable (IN-list sizes change fingerprints) |

**Validation:** pg-collector should correctly count all three populations.
Sum of fingerprints from all three sources = total in `pg_stat_statements`.

### 3. Resource Consumption

| Metric | How to Compare |
|--------|----------------|
| `shared_blks_hit` / `shared_blks_read` | Cache efficiency per workload source |
| `temp_files` / `temp_bytes` | Which workload spills to disk |
| `blk_read_time` / `blk_write_time` | I/O cost per workload |
| Connection count | `pg_stat_activity` grouped by application_name |
| Lock contention | `pg_locks` during concurrent operation |

### 4. Latency Profile

| Metric | Measurement Method |
|--------|-------------------|
| pgbench latency | Built-in `--report-per-command` output |
| Raw SQL latency | `mean_exec_time` from `pg_stat_statements` per `queryid` |
| ORM latency | Same, but expect higher due to round-trip overhead |

---

## Experiment Design

### Experiment 1: Isolated Baseline

Run each workload in isolation for 5 minutes, capture `pg_stat_statements` snapshots.

```bash
# Phase 1: pgbench only
make up
PGBENCH_MODE=tpcb PGBENCH_DURATION=300 make up-bench
# wait, collect results
make pg-stat > out/phase1_pgbench_only.txt
make pg-stat-reset

# Phase 2: raw SQL only (pgbench stopped)
# already running from make up
sleep 300
make pg-stat > out/phase2_rawsql_only.txt
make pg-stat-reset

# Phase 3: ORM only
make up-orm
# disable raw SQL load gen temporarily
sleep 300
make pg-stat > out/phase3_orm_only.txt
```

**Goal:** Establish per-workload fingerprint baselines.

### Experiment 2: Mixed Workload

Run all three simultaneously for 10 minutes.

```bash
make up-full
PGBENCH_MODE=tpcb PGBENCH_DURATION=600
sleep 600
make pg-stat > out/mixed_all_three.txt
make report
```

**Goal:** Verify pg-collector can identify queries from each source when interleaved.

### Experiment 3: ORM Pattern Isolation

Run ORM generator with one pattern at a time (100% weight), capture fingerprints.

```bash
# N+1 only
ORM_MIX_N_PLUS_1=100 ORM_MIX_EAGER_JOIN=0 ... make up-orm
sleep 120
make pg-stat > out/orm_n_plus_1.txt

# Eager join only
ORM_MIX_N_PLUS_1=0 ORM_MIX_EAGER_JOIN=100 ... make up-orm
sleep 120
make pg-stat > out/orm_eager_join.txt

# ... repeat for each pattern
```

**Goal:** Build a catalog of exact fingerprints each ORM pattern produces.

### Experiment 4: Scale Comparison

| Parameter | Light | Medium | Heavy |
|-----------|-------|--------|-------|
| pgbench clients | 5 | 20 | 50 |
| Raw SQL burst conns | 5 | 20 | 50 |
| ORM concurrency | 2 | 5 | 15 |
| Duration | 5 min | 10 min | 30 min |

```bash
SCENARIO=gentle make up-full    # Light
SCENARIO=default make up-full   # Medium
SCENARIO=heavy make up-full     # Heavy
```

**Goal:** Verify pg-collector accuracy doesn't degrade under high load.

---

## What pg-collector Should Differentiate

### By Table Access Pattern

| Source | Primary Tables | Distinguishing Pattern |
|--------|---------------|----------------------|
| pgbench | `pgbench_*` | Only source hitting these tables |
| Raw SQL | `products`, `orders`, `cart_items` | Explicit JOINs, specific column lists |
| ORM | `products`, `orders`, `cart_items` | ORM-style: `SELECT *`, `LEFT OUTER JOIN`, `EXISTS` |

### By Query Structure

| Feature | Raw SQL | ORM (SQLAlchemy) |
|---------|---------|------------------|
| Column selection | Explicit named columns | Often `SELECT t.id, t.col1, t.col2, ...` (all mapped columns) |
| JOIN style | `JOIN ... ON` | `LEFT OUTER JOIN ... ON` (eager loading) |
| Subqueries | Rare, hand-optimized | Common (`EXISTS`, `IN (SELECT ...)`, correlated) |
| Parameter style | `$1, $2` | `$1, $2` (same, but more parameters per query) |
| UPDATE pattern | `WHERE id = (SELECT ...)` | `WHERE id = $1` (PK from prior SELECT) |
| INSERT | Explicit column list | `INSERT ... RETURNING id` (always returns PK) |

### By `queryid` Clustering

- **pgbench:** 5 tight clusters, very high calls per queryid
- **Raw SQL:** 30-40 medium clusters, moderate calls per queryid
- **ORM:** 50-100+ sparse clusters, many with lower call counts
  - N+1 shows as one `queryid` with very high call count (the repeated SELECT)
  - Eager load shows as fewer `queryid` values but with complex query text

---

## Success Criteria

1. **Fingerprint accuracy:** pg-collector reports the same `queryid` set as `pg_stat_statements`
2. **Source attribution:** Given the fingerprint catalog, all queries can be traced to their source
3. **Counter accuracy:** `calls`, `total_exec_time`, `rows` match within tolerance (±5%)
4. **Mixed workload:** No fingerprint collision between pgbench / raw SQL / ORM queries
5. **ORM pattern identification:** N+1 patterns detectable by high call count on simple SELECT
6. **Scale stability:** Accuracy maintained from gentle → heavy scenarios

---

## Running the Full Comparison

```bash
# 1. Start the full stack
make up-full

# 2. Wait for seeding (~5 min first time)
make logs-loadgen  # watch for "data ready"

# 3. Let it run under load (10-30 min)
sleep 600

# 4. Collect results
make report                         # local report
make pg-stat                        # quick pg_stat_statements view
./scripts/run-benchmark.sh          # pgbench comparison

# 5. Review
cat out/report-*/REPORT.md
cat out/benchmark-*/summary.md

# 6. Verify via truth-service
make verify
```
