# Control Plane

REST API at `:8100` for running stress operations and monitoring. UI at `:3100`.
All operations target the local PostgreSQL container. Swagger docs at `:8100/docs`.

## Monitoring Endpoints

Use these to see what the stress test is doing:

```bash
# Full stack status — services, DB size, connections, per-table row counts + dead tuples
curl -s http://<host>:8100/status | python3 -m json.tool

# Database target + current intensity level
curl -s http://<host>:8100/config | python3 -m json.tool

# ORM generator — per-pattern operation counts + errors
curl -s http://<host>:9091/healthz | python3 -m json.tool
```

## All Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status` | GET | Stack status: services, DB size, connections, per-table stats |
| `/config` | GET | Database target + current intensity |
| `/config/intensity` | POST | Switch Low/Medium/High (restarts generators) |
| `/generators/{name}/start` | POST | Start ORM or pgbench generator |
| `/generators/{name}/stop` | POST | Stop a generator |
| `/inject` | POST | Inject N rows into any table |
| `/bulk-update` | POST | Batch UPDATE with SET/WHERE |
| `/connections` | POST | Connection pressure test |
| `/ladder` | POST | Growth ladder (find breaking point) |
| `/import` | POST | Restore a pg_dump (BYOD) |
| `/analyze` | POST | Claude AI analysis |
| `/analyze/latest` | GET | Latest analysis report |
| `/jobs` | GET | List background jobs |
| `/jobs/{id}` | GET | Job status |
| `/reports` | GET | Saved reports |

## Intensity Presets

| Level | Burst Conns | Chaos | Pause | ORM Threads |
|---|---|---|---|---|
| **Low** | 3 / 8 / 15 | Off | 30-120s | 2 |
| **Medium** | 5 / 20 / 50 | 25% | 20-90s | 5 |
| **High** | 15 / 40 / 80 | 50% | 5-20s | 15 |

Switching intensity restarts the load generators with new env vars.

## WHAT IF Operations

**Inject rows:** `POST /inject {"table": "orders", "rows": 5000000}`

**Bulk update:** `POST /bulk-update {"table": "orders", "set_clause": "status='archived'", "where_clause": "placed_at < now() - interval '1 year'"}`

**Connection pressure:** `POST /connections {"connections": 100, "duration": 300, "mode": "mixed"}`

**Growth ladder:** `POST /ladder {"steps": [10, 25, 50, 100, 200], "phase_duration": 180}`

All run as background jobs. Check status: `GET /jobs/{id}`

## AI Analysis

Requires `ANTHROPIC_API_KEY` in `.env`. Collects 11 diagnostic datasets from PostgreSQL
(pg_stat_statements, table stats, index usage, locks, settings) and sends them to Claude
for expert analysis.

### Setup

```bash
# Add to .env
ANTHROPIC_API_KEY=sk-ant-...

# Restart control plane
docker compose up -d control-plane
```

### API Endpoints

```bash
POST /analyze {"focus": null}          # Full — health score, queries, tuning, capacity
POST /analyze {"focus": "tuning"}      # PostgreSQL parameter tuning
POST /analyze {"focus": "queries"}     # Query optimization + N+1 detection
POST /analyze {"focus": "capacity"}    # Growth projections + breaking points

GET  /analyze/latest                   # Latest analysis report
GET  /reports                          # All saved reports
```

### CLI

```bash
make analyze                           # Full report (saved to out/)
make analyze-tuning                    # PG parameter recommendations
make analyze-queries                   # N+1 detection, missing indexes
make analyze-capacity                  # Growth projections
make analyze-collect                   # Collect data only (no AI, no API key needed)
```

### UI

Open `http://<host>:3100`, scroll to **AI Analyzer**, select focus, click **Run Analysis**.

### What Gets Collected

| Dataset | Source | What it reveals |
|---------|--------|-----------------|
| Top queries | `pg_stat_statements` | Slowest by total time |
| Cache misses | `pg_stat_statements` | Poor buffer hit ratio |
| Temp spills | `pg_stat_statements` | Queries needing more `work_mem` |
| N+1 candidates | `pg_stat_statements` | High-call, low-row ORM anti-patterns |
| Database stats | `pg_stat_database` | TPS, cache ratio, deadlocks |
| Table stats | `pg_stat_user_tables` | Dead tuples, seq scans |
| Index stats | `pg_stat_user_indexes` | Usage, unused indexes |
| Connections | `pg_stat_activity` | By state |
| Locks & waits | `pg_locks` | Contention |
| PG settings | `pg_settings` | Current configuration |
