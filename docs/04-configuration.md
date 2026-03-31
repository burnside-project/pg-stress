# Configuration

All settings are environment variables. Copy `.env.example` to `.env` and adjust.

## PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_PORT` | `5434` | Host port for PostgreSQL |
| `PG_SHARED_BUFFERS` | `256MB` | Shared buffer pool size |
| `PG_WORK_MEM` | `16MB` | Per-operation sort/hash memory |
| `PG_MAX_CONNECTIONS` | `200` | Maximum concurrent connections |
| `PG_EFFECTIVE_CACHE_SIZE` | `1GB` | Planner estimate of OS cache |

## Raw SQL Load Generator

| Variable | Default | Description |
|----------|---------|-------------|
| `LOADGEN_DURATION` | `0` (forever) | Test duration (e.g. `30m`, `2h`) |
| `LOADGEN_MIX_BROWSE` | `50` | Browse traffic weight % |
| `LOADGEN_MIX_CART` | `20` | Cart operations weight % |
| `LOADGEN_MIX_CHECKOUT` | `5` | Checkout transactions weight % |
| `LOADGEN_MIX_ORDER` | `10` | Order management weight % |
| `LOADGEN_MIX_BACKGROUND` | `10` | Background tasks weight % |
| `LOADGEN_MIX_REPORTING` | `5` | Reporting queries weight % |
| `LOADGEN_CHAOS_ENABLED` | `true` | Enable chaos patterns |
| `LOADGEN_CHAOS_PROBABILITY` | `25` | Chaos injection probability (0-100) |
| `LOADGEN_BURST_*_CONNS` | `5/20/50` | Connections per burst level |
| `LOADGEN_BURST_*_DURATION` | `10s/30s/60s` | Duration per burst level |
| `LOADGEN_PAUSE_MIN` / `MAX` | `20/90` | Seconds between bursts |
| `LOADGEN_MAX_POOL` | `60` | Connection pool size |

## ORM Load Generator

| Variable | Default | Description |
|----------|---------|-------------|
| `ORM_CONCURRENCY` | `5` | Worker threads |
| `ORM_DURATION` | `0` (forever) | Test duration |
| `ORM_PAUSE_MIN` / `MAX` | `10/50` | Milliseconds between operations |
| `ORM_MIX_N_PLUS_1` | `15` | N+1 lazy loading weight % |
| `ORM_MIX_EAGER_JOIN` | `15` | Joinedload weight % |
| `ORM_MIX_EAGER_SUBQUERY` | `10` | Subqueryload weight % |
| `ORM_MIX_EAGER_SELECTIN` | `10` | Selectinload weight % |
| `ORM_MIX_BULK_INSERT` | `5` | Bulk INSERT weight % |
| `ORM_MIX_ORM_UPDATE` | `10` | Load-modify-save weight % |
| `ORM_MIX_PAGINATION` | `10` | LIMIT/OFFSET weight % |
| `ORM_MIX_AGGREGATION` | `10` | func() aggregation weight % |
| `ORM_MIX_EXISTS_FILTER` | `10` | EXISTS subquery weight % |
| `ORM_MIX_RELATIONSHIP` | `5` | Relationship JOIN weight % |

## pgbench Runner

| Variable | Default | Description |
|----------|---------|-------------|
| `PGBENCH_CLIENTS` | `10` | Concurrent connections |
| `PGBENCH_THREADS` | `2` | Worker threads |
| `PGBENCH_DURATION` | `300` | Benchmark duration (seconds) |
| `PGBENCH_SCALE` | `100` | Scale factor |
| `PGBENCH_MODE` | `mixed` | `tpcb`, `readonly`, `mixed`, `custom`, `all` |

## Dashboard

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_PORT` | `8000` | Dashboard UI port |
| `STRESS_POLL_INTERVAL` | `10` | Metrics polling interval (seconds) |
| `STRESS_SAFETY_INTERVAL` | `30` | Safety check interval (seconds) |
| `STRESS_MAX_DB_SIZE` | `20000000000` | Max database size (bytes) |
| `STRESS_LIMIT_*` | varies | Row limits per append-only table |

## AI Analyzer

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | -- | **required** for `make analyze` |

## Deployment

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOY_HOST` | `4` | SSH alias or hostname |
| `DEPLOY_PATH` | `/opt/burnside-test-suite` | Remote install path |
