# Configuration

All settings via environment variables in `.env`. Copy `.env.example` to `.env`.

## Database Target

These variables configure the **local PostgreSQL container** that pg-stress runs.
They do not connect to a remote or external database. To test production data,
export a dump and import it with `make import DUMP=...`
(see [Quickstart — Path A](02-quickstart.md#path-a-i-have-production-data)).

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_HOST` | `localhost` | Server hostname or IP — displayed in the Control Panel UI |
| `PG_USER` | `postgres` | Container Postgres user |
| `PG_PASSWORD` | `postgres` | Container Postgres password |
| `PG_DATABASE` | `testdb` | Database name — set to your dump's DB name for BYOD |
| `PG_PORT` | `5434` | Host-mapped port (access from your machine via `localhost:5434`) |

Example — import and test a production dump called `soak_test`:

```bash
# .env
PG_DATABASE=soak_test      # must match the DB name in the dump
SEED_SCHEMA=false           # skip built-in e-commerce schema
```

```bash
make import DUMP=soak_test.dump
make up INTENSITY=medium
```

## Schema Seeding

| Variable | Default | Description |
|----------|---------|-------------|
| `SEED_SCHEMA` | `true` | Set to `false` to skip the built-in 18-table e-commerce schema |

When `SEED_SCHEMA=true` (default), the built-in e-commerce schema (~30M rows) is loaded
on first startup. Set to `false` when:

- Using BYOD (`make import DUMP=...`) — your dump already has its own schema
- You only want an empty database to populate yourself

## PostgreSQL Configuration

These settings are applied when the container starts and **do not change during a test**.
They are intentionally modest so the AI Analyzer has room to recommend improvements.

| Setting | Default | `.env` Variable | What it controls |
|---------|---------|-----------------|-----------------|
| `shared_buffers` | 256 MB | `PG_SHARED_BUFFERS` | Shared memory for data page caching |
| `work_mem` | 16 MB | `PG_WORK_MEM` | Memory per sort/hash/join operation |
| `effective_cache_size` | 1 GB | `PG_EFFECTIVE_CACHE_SIZE` | Planner's cache size assumption |
| `max_connections` | 200 | `PG_MAX_CONNECTIONS` | Maximum concurrent connections |
| `maintenance_work_mem` | 128 MB | — | Memory for VACUUM, CREATE INDEX |
| `wal_buffers` | 16 MB | — | WAL write buffer size |
| `max_wal_size` | 2 GB | — | WAL size before checkpoint |
| `random_page_cost` | 1.1 | — | Random I/O cost estimate (SSD) |
| `effective_io_concurrency` | 200 | — | Async I/O requests (SSD) |
| `checkpoint_completion_target` | 0.9 | — | Spread checkpoint writes |
| `autovacuum_max_workers` | 4 | — | Parallel autovacuum workers |
| `autovacuum_naptime` | 30s | — | Time between autovacuum runs |
| `shared_preload_libraries` | `pg_stat_statements` | — | Query stats tracking |
| `log_min_duration_statement` | 1000 ms | — | Log queries slower than 1s |

To view the live configuration from a running container:

```bash
docker compose exec postgres psql -U postgres -d soak_test \
  -c "SELECT name, setting, unit FROM pg_settings WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_connections');"
```

## Intensity

| Variable | Default | Description |
|----------|---------|-------------|
| `INTENSITY` | `medium` | Preset: `low`, `medium`, `high` |

Or set individual variables (overrides preset):

### Raw SQL Generator

| Variable | Default | Description |
|----------|---------|-------------|
| `LOADGEN_DURATION` | `0` (forever) | Test duration |
| `LOADGEN_MIX_BROWSE` | `50` | Browse traffic % |
| `LOADGEN_MIX_CART` | `20` | Cart operations % |
| `LOADGEN_MIX_CHECKOUT` | `5` | Checkout transactions % |
| `LOADGEN_MIX_ORDER` | `10` | Order management % |
| `LOADGEN_MIX_BACKGROUND` | `10` | Background tasks % |
| `LOADGEN_MIX_REPORTING` | `5` | Reporting queries % |
| `LOADGEN_CHAOS_ENABLED` | `true` | Enable chaos patterns |
| `LOADGEN_CHAOS_PROBABILITY` | `25` | Chaos probability (0-100) |
| `LOADGEN_BURST_*_CONNS` | `5/20/50` | Connections per burst level |
| `LOADGEN_PAUSE_MIN/MAX` | `20/90` | Seconds between bursts |
| `LOADGEN_MAX_POOL` | `60` | Connection pool size |

### ORM Generator

| Variable | Default | Description |
|----------|---------|-------------|
| `ORM_CONCURRENCY` | `5` | Worker threads |
| `ORM_PAUSE_MIN/MAX` | `10/50` | Milliseconds between ops |
| `ORM_MIX_N_PLUS_1` | `15` | N+1 pattern weight |
| `ORM_MIX_EAGER_JOIN` | `15` | Joinedload weight |
| `ORM_MIX_EAGER_SUBQUERY` | `10` | Subqueryload weight |
| `ORM_MIX_EAGER_SELECTIN` | `10` | Selectinload weight |
| `ORM_MIX_BULK_INSERT` | `5` | Bulk INSERT weight |
| `ORM_MIX_ORM_UPDATE` | `10` | Load-modify-save weight |
| `ORM_MIX_PAGINATION` | `10` | Pagination weight |
| `ORM_MIX_AGGREGATION` | `10` | Aggregation weight |
| `ORM_MIX_EXISTS_FILTER` | `10` | EXISTS subquery weight |
| `ORM_MIX_RELATIONSHIP` | `5` | Relationship JOIN weight |

### Ports

| Variable | Default | Service |
|----------|---------|---------|
| `PG_PORT` | `5434` | PostgreSQL |
| `DASHBOARD_PORT` | `8200` | Dashboard |
| `CONTROL_PLANE_PORT` | `8100` | Control Plane API |
| `UI_PORT` | `3100` | Control Panel UI |
| `ORM_HEALTHZ_PORT` | `9091` | ORM Generator |
| `TRUTH_PORT` | `8001` | Truth Service |
| `COLLECTOR_PORT` | `8080` | Collector |

### AI Analyzer

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for AI analysis (CLI, UI, and API) |
| `ANALYZER_MODEL` | `claude-sonnet-4-20250514` | Claude model for analysis |

To enable, add to `.env` and restart the control plane:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

```bash
docker compose up -d control-plane
```

Three ways to run: `make analyze` (CLI), Control Panel UI at `:3100`, or `POST /analyze` (API).
See [Control Plane — AI Analysis](04-control-plane.md#ai-analysis) for details.

### Reports

| Variable | Default | Description |
|----------|---------|-------------|
| `REPORTS_DIR` | `/app/reports` | Where AI analysis and ladder reports are saved (inside container) |

Reports are stored as JSON + Markdown files in the `control-plane-reports` Docker volume.
Access via API (`GET /reports`), Control Panel UI (Reports section), or mount the volume locally.

### Data Storage

| Data | Storage | Volume | Persists? |
|------|---------|--------|-----------|
| Schema graph | SQLite (NetworkX cache) | `control-plane-data` (`/data/schema_cache.db`) | Yes |
| Imported queries | SQLite | `control-plane-data` (`/data/queries.db`) | Yes |
| Dashboard metrics + test runs | SQLite | `dashboard-data` (`/data/metrics.db`) | Yes |
| AI analysis reports | JSON + Markdown | `control-plane-reports` (`/app/reports/`) | Yes |
| PostgreSQL data | PostgreSQL files | `stress-pg-data` | Yes |
| pgbench results | Text files | `pgbench-results` | Yes |

All data survives container restarts. Schema graph is cached with a hash —
if the database schema changes, pg-stress re-introspects automatically.

Use `make stop` to stop services but keep all data.
Use `make down` to remove all volumes (full reset).
