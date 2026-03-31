# Control Plane

REST API at port 8100 for running stress test operations from the browser or curl.
Swagger UI at `http://<server>:8100/docs`.

## Quick Reference

| What you want to do | Endpoint | Method |
|---------------------|----------|--------|
| See everything running | `/status` | GET |
| Start ORM generator | `/generators/orm/start` | POST |
| Stop ORM generator | `/generators/orm/stop` | POST |
| Start pgbench | `/generators/pgbench/start` | POST |
| Inject rows into a table | `/inject` | POST |
| Bulk update rows | `/bulk-update` | POST |
| Stress with N connections | `/connections` | POST |
| Find breaking point | `/ladder` | POST |
| Run AI analysis | `/analyze` | POST |
| See latest AI report | `/analyze/latest` | GET |
| Check a background job | `/jobs/{job_id}` | GET |
| List all reports | `/reports` | GET |

---

## Knob 1: Stack Status

See what's running, database size, table row counts, active jobs.

```bash
curl http://localhost:8100/status | python3 -m json.tool
```

Returns:

```json
{
  "services": {
    "postgres": { "status": "running", "health": "healthy" },
    "load-generator": { "status": "running" },
    "load-generator-orm": { "status": "not_found" },
    "pgbench-runner": { "status": "not_found" }
  },
  "database": { "db_size": "6250 MB", "connections": 12 },
  "tables": {
    "order_items": { "n_live_tup": 15000000, "n_dead_tup": 0, "size": "2 GB" },
    "orders": { "n_live_tup": 5000000, ... }
  },
  "jobs": {},
  "reports": 0
}
```

---

## Knob 2: Generators (Start / Stop)

Start or stop the ORM or pgbench load generators.

```bash
# Start ORM generator (SQLAlchemy N+1, eager load, etc.)
curl -X POST http://localhost:8100/generators/orm/start

# Stop it
curl -X POST http://localhost:8100/generators/orm/stop

# Start pgbench (TPC-B baseline)
curl -X POST http://localhost:8100/generators/pgbench/start
```

> The raw SQL load generator runs by default with `docker compose up`.
> It can't be started/stopped via control plane — it's always-on as the baseline.

---

## Knob 3: Inject Rows

**"What if this table grows by N rows?"**

Inserts rows by duplicating existing data with randomized ordering.
Runs ANALYZE after injection.

```bash
# Inject 5M rows into orders
curl -X POST http://localhost:8100/inject \
  -H "Content-Type: application/json" \
  -d '{"table": "orders", "rows": 5000000}'

# Inject 10M rows into search_log
curl -X POST http://localhost:8100/inject \
  -d '{"table": "search_log", "rows": 10000000}'
```

With custom INSERT template (for precise control):

```bash
curl -X POST http://localhost:8100/inject \
  -H "Content-Type: application/json" \
  -d '{
    "table": "orders",
    "rows": 5000000,
    "template": "INSERT INTO orders (customer_id, status, subtotal, tax, shipping, total, placed_at) SELECT (random()*999999+1)::int, '\''pending'\'', (random()*500)::numeric(10,2), (random()*40)::numeric(10,2), 0, (random()*540)::numeric(12,2), now()-random()*interval '\''365 days'\'' FROM generate_series(1, {batch})"
  }'
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table` | string | **required** | Target table name |
| `rows` | int | **required** | Number of rows to inject |
| `template` | string | auto | Custom INSERT SQL. Use `{batch}` for batch size placeholder |

Returns a `job_id` — injection runs in background. Check progress:

```bash
curl http://localhost:8100/jobs/{job_id}
```

---

## Knob 4: Bulk Update

**"What if we archive/update N rows?"**

Batched UPDATE to avoid locking the entire table.

```bash
# Archive old orders
curl -X POST http://localhost:8100/bulk-update \
  -H "Content-Type: application/json" \
  -d '{
    "table": "orders",
    "set_clause": "status='\''archived'\''",
    "where_clause": "placed_at < now() - interval '\''1 year'\''",
    "batch_size": 100000
  }'

# Mark all discontinued products
curl -X POST http://localhost:8100/bulk-update \
  -d '{
    "table": "products",
    "set_clause": "status='\''discontinued'\''",
    "where_clause": "created_at < now() - interval '\''2 years'\''",
    "batch_size": 50000
  }'
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table` | string | **required** | Target table |
| `set_clause` | string | **required** | SET expression (e.g. `"status='archived'"`) |
| `where_clause` | string | none | WHERE filter (omit to update all rows) |
| `batch_size` | int | 100000 | Rows per batch (prevents long locks) |

---

## Knob 5: Connection Pressure

**"What happens at 100 concurrent connections?"**

Opens N connections via pgbench and holds them for the specified duration.

```bash
# 50 connections for 5 minutes (mixed read/write)
curl -X POST http://localhost:8100/connections \
  -d '{"connections": 50, "duration": 300, "mode": "mixed"}'

# 200 connections read-only for 10 minutes
curl -X POST http://localhost:8100/connections \
  -d '{"connections": 200, "duration": 600, "mode": "readonly"}'

# 100 connections TPC-B (pure write pressure)
curl -X POST http://localhost:8100/connections \
  -d '{"connections": 100, "duration": 300, "mode": "tpcb"}'
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `connections` | int | 100 | Concurrent connections |
| `duration` | int | 300 | Seconds to run |
| `mode` | string | `mixed` | `mixed`, `readonly`, or `tpcb` |

Result (when job completes):

```json
{
  "connections": 100,
  "tps": 4800,
  "latency_avg_ms": 20.8,
  "deltas": {
    "xact_commit": 1440000,
    "deadlocks": 3,
    "temp_files": 47
  }
}
```

---

## Knob 6: Growth Ladder (Find Breaking Point)

**"At what load does the database break?"**

Runs multiple phases at increasing connection counts. Captures TPS, cache ratio,
deadlocks, and temp files per phase. This is the most powerful diagnostic tool.

```bash
# Default ladder: 10 → 25 → 50 → 100 → 200 connections
curl -X POST http://localhost:8100/ladder \
  -d '{"steps": [10, 25, 50, 100, 200], "phase_duration": 180}'

# Gentle ladder for smaller databases
curl -X POST http://localhost:8100/ladder \
  -d '{"steps": [5, 10, 20, 40], "phase_duration": 120}'

# Aggressive ladder
curl -X POST http://localhost:8100/ladder \
  -d '{"steps": [25, 50, 100, 150, 200, 250, 300], "phase_duration": 120}'
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `steps` | int[] | `[10,25,50,100,200]` | Connection counts per phase |
| `phase_duration` | int | 180 | Seconds per phase |
| `mode` | string | `mixed` | `mixed`, `readonly`, or `tpcb` |

> **Duration:** 5 phases × 180s = 15 minutes total. Plan accordingly.

Result (saved to `/reports`):

```json
{
  "phases": [
    {"connections": 10,  "tps": 2340, "cache_ratio": 0.998, "deadlocks": 0, "temp_files": 0},
    {"connections": 25,  "tps": 4200, "cache_ratio": 0.994, "deadlocks": 0, "temp_files": 0},
    {"connections": 50,  "tps": 5100, "cache_ratio": 0.971, "deadlocks": 2, "temp_files": 0},
    {"connections": 100, "tps": 4800, "cache_ratio": 0.923, "deadlocks": 14, "temp_files": 847},
    {"connections": 200, "tps": 2100, "cache_ratio": 0.841, "deadlocks": 89, "temp_files": 4200}
  ]
}
```

**How to read this:**
- TPS peaks at 50 connections then drops → diminishing returns
- Cache ratio drops below 0.95 at 100 → `shared_buffers` too small
- Deadlocks appear at 50 → checkout path contention
- Temp files appear at 100 → `work_mem` too small for aggregation queries

Feed this to the analyzer for specific tuning recommendations.

---

## Knob 7: AI Analyzer

**"Tell me what to fix."**

Collects 10 diagnostic datasets from PostgreSQL and sends them to Claude.

```bash
# Full analysis (health score + all recommendations)
curl -X POST http://localhost:8100/analyze \
  -d '{"focus": null}'

# Just PostgreSQL parameter tuning
curl -X POST http://localhost:8100/analyze \
  -d '{"focus": "tuning"}'

# Just query optimization + N+1 detection
curl -X POST http://localhost:8100/analyze \
  -d '{"focus": "queries"}'

# Just capacity predictions
curl -X POST http://localhost:8100/analyze \
  -d '{"focus": "capacity"}'
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `focus` | string | null (full) | `tuning`, `queries`, `capacity`, or null for everything |
| `model` | string | `claude-sonnet-4-20250514` | Claude model to use |

> **Requires** `ANTHROPIC_API_KEY` in `.env`.

Get the latest report:

```bash
curl http://localhost:8100/analyze/latest
```

---

## Knob 8: Jobs

All long-running operations (inject, bulk-update, connections, ladder, analyze)
run in the background and return a `job_id`.

```bash
# List all jobs
curl http://localhost:8100/jobs

# Check specific job
curl http://localhost:8100/jobs/{job_id}
```

Job states: `running` → `completed` or `failed`.

---

## Knob 9: Reports

All ladder and analyzer results are saved as reports.

```bash
# List all reports
curl http://localhost:8100/reports

# Get a specific report
curl http://localhost:8100/reports/ladder-20260331-193000.json
curl http://localhost:8100/reports/analysis-tuning-20260331-194500.md
```

---

## Common Recipes

### Recipe: "Can we handle Black Friday?"

```bash
# 1. Inject anticipated order volume
curl -X POST :8100/inject -d '{"table":"orders","rows":5000000}'
curl -X POST :8100/inject -d '{"table":"search_log","rows":10000000}'

# 2. Wait for injection (check jobs)
curl :8100/jobs

# 3. Run growth ladder to find breaking point
curl -X POST :8100/ladder -d '{"steps":[10,25,50,100,150,200],"phase_duration":180}'

# 4. Get AI recommendations
curl -X POST :8100/analyze -d '{"focus":"tuning"}'

# 5. Read the report
curl :8100/analyze/latest
```

### Recipe: "Is our ORM efficient?"

```bash
# 1. Start ORM generator
curl -X POST :8100/generators/orm/start

# 2. Let it run 10 minutes, then...
curl -X POST :8100/analyze -d '{"focus":"queries"}'

# 3. Check N+1 detection and ORM attribution
curl :8100/analyze/latest
```

### Recipe: "What connections can we handle?"

```bash
# Quick test
curl -X POST :8100/connections -d '{"connections":100,"duration":60}'

# Or find the exact breaking point
curl -X POST :8100/ladder -d '{"steps":[10,20,40,60,80,100,120,140,160,180,200],"phase_duration":60}'
```

### Recipe: "Should we partition this table?"

```bash
# Inject rows to simulate 6 months of growth
curl -X POST :8100/inject -d '{"table":"search_log","rows":50000000}'

# Run capacity analysis
curl -X POST :8100/analyze -d '{"focus":"capacity"}'
```
