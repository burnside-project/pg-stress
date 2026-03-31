# AI Analyzer

Claude-powered analysis of stress test results. Collects PostgreSQL diagnostics,
sends them as a structured context bundle, returns actionable recommendations.

## Usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...

make analyze                # Full report (health score, queries, tuning, capacity)
make analyze-tuning         # PostgreSQL parameter tuning only
make analyze-queries        # Query optimization + N+1 detection only
make analyze-capacity       # Growth projections + scaling only
make analyze-collect        # Dump raw diagnostics (no AI, no API key)
```

Reports saved to `out/analysis-YYYYMMDD-HHMMSS/`.

## What Gets Collected

| Dataset | Source | Why |
|---------|--------|-----|
| Top 50 queries | `pg_stat_statements` | Identify slowest, most resource-heavy queries |
| Cache miss queries | `pg_stat_statements` | Queries with hit ratio < 0.95 |
| Temp-spilling queries | `pg_stat_statements` | Queries that overflow work_mem to disk |
| N+1 candidates | `pg_stat_statements` | High calls, low rows/call, `WHERE id = $1` |
| Database stats | `pg_stat_database` | TPS, cache ratio, deadlocks, temp files |
| Table stats | `pg_stat_user_tables` | Live/dead rows, seq vs idx scans, vacuum state |
| Index stats | `pg_stat_user_indexes` | Usage counts, unused indexes, sizes |
| Connections | `pg_stat_activity` | State breakdown (active, idle, idle-in-txn) |
| Locks | `pg_locks` | Mode distribution, granted vs waiting |
| Wait events | `pg_stat_activity` | What queries are blocked on |
| PG settings | `pg_settings` | 30+ tuning-relevant parameters |

## Analysis Modes

### Full (`make analyze`)

Returns all of the below in a single report with a health score (1-10).

### Tuning (`make analyze-tuning`)

Parameter-by-parameter recommendations:

```
Parameter           Current   Recommended   Rationale
─────────           ───────   ───────────   ─────────
shared_buffers      256MB     1GB           Cache hit ratio 0.92 at 3x load
work_mem            16MB      64MB          847 temp files from reporting query
effective_cache_size 1GB      3GB           Planner underestimates index scans
```

Includes exact `ALTER SYSTEM` commands and restart/reload sequence.

### Queries (`make analyze-queries`)

- N+1 detection with confirmed patterns and fix recommendations
- ORM vs raw SQL attribution by query structure
- Missing index suggestions with `CREATE INDEX` statements
- Cache efficiency comparison across workload sources

### Capacity (`make analyze-capacity`)

- Per-table growth projections (rows/hour, time to limit)
- Resource headroom (connections, shared_buffers, work_mem)
- Scaling thresholds (at what TPS does config become bottleneck?)
- "Cost of doing nothing" timeline

## Context Bundle Format

The analyzer packages data as an LLM-optimized JSON bundle:

```
{
  test_metadata       scenario, duration, hardware profile
  before_snapshot     baseline stats (pre-stress)
  after_snapshot      post-stress stats
  deltas              what changed (degraded queries, new deadlocks)
  anomalies           timestamped events (cache cliff, temp spill)
  postgresql_config   current tuning settings
  questions_for_llm   auto-generated from anomaly detection
}
```

Every field is annotated -- not raw numbers, but curated signal.
