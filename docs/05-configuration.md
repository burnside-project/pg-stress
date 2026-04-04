# Configuration

All settings via environment variables in `.env`. Copy `.env.example` to `.env`.

## Database Target

These variables configure the **local PostgreSQL container** that pg-stress runs.
They do not connect to a remote or external database. To test production data,
export a dump and import it with `make import DUMP=...`
(see [Quickstart — Path A](02-quickstart.md#path-a-i-have-production-data)).

| Variable | Default | Description |
|----------|---------|-------------|
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
| `DASHBOARD_PORT` | `8000` | Dashboard |
| `CONTROL_PLANE_PORT` | `8100` | Control Plane API |
| `UI_PORT` | `3100` | Control Panel UI |
| `ORM_HEALTHZ_PORT` | `9091` | ORM Generator |
| `TRUTH_PORT` | `8001` | Truth Service |
| `COLLECTOR_PORT` | `8080` | Collector |

### AI Analyzer

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for `make analyze` |
