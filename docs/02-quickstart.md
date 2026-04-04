# Quickstart

## Prerequisites

| Requirement | Minimum |
|-------------|---------|
| Docker | 24.0+ |
| Docker Compose | v2.20+ |
| Disk (free) | 20 GB |
| Memory (free) | 4 GB |

## Docker Images

All services are published as multi-arch Docker images (`linux/amd64` + `linux/arm64`)
to GitHub Container Registry. New images are built automatically on every push to `main`.

```bash
# Pull latest release candidate
for svc in load-generator load-generator-orm pgbench-runner dashboard truth-service; do
  docker pull ghcr.io/dataalgebra-engineering/pg-stress/${svc}:rc-latest
done
```

See [Releases & CI/CD](06-releases.md) for version pinning and stable releases.

> **Important:** pg-stress runs its own PostgreSQL container. It does **not**
> connect to a remote or external database. To test production data, you export
> a dump from production and import it into the local container.

## Path A: I Have Production Data

### 1. Export a dump from your production database

Run this against your **production** PostgreSQL (not inside pg-stress):

```bash
# Custom format (-Fc) is recommended — supports parallel restore
pg_dump -Fc -h prod-host -U prod_user -d my_production_db > production.dump

# Plain SQL also works
pg_dump -h prod-host -U prod_user -d my_production_db > production.sql
```

### 2. Clone and configure

```bash
git clone https://github.com/dataalgebra-engineering/pg-stress.git
cd pg-stress
cp .env.example .env
```

Edit `.env`:

```bash
# .env
PG_DATABASE=my_production_db       # must match the DB name in your dump
SEED_SCHEMA=false                  # skip built-in e-commerce schema
```

The `PG_USER`, `PG_PASSWORD`, and `PG_DATABASE` variables configure the **local
Docker container** — they are not connection details for your production server.

### 3. Import and start

```bash
make import DUMP=production.dump   # restores into the local container
make up INTENSITY=medium           # introspects schema, starts load generators
```

### 4. Verify

Open `http://localhost:3100` — pg-stress auto-discovers your imported schema
and starts generating load automatically.

```bash
# Check that your tables were imported
docker compose exec postgres psql -U postgres -d my_production_db \
  -c "SELECT tablename FROM pg_tables WHERE schemaname='public';"
```

## Path B: No Production Data

```bash
git clone https://github.com/dataalgebra-engineering/pg-stress.git
cd pg-stress
make up                  # Seeds 18-table e-commerce schema (~30M rows)
```

Wait ~10 minutes for seeding on first run. Watch progress:

```bash
docker compose logs -f postgres | grep -E 'Seeding|Done'
```

## Verify

```bash
# All services running?
docker compose ps

# Load generator hitting the database?
curl -s http://localhost:9090/healthz | python3 -m json.tool

# ORM generator introspected the schema?
docker compose logs load-generator-orm | head -20

# Dashboard live?
open http://localhost:8200

# Control panel live?
open http://localhost:3100
```

## What's Running

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 15 | 5434 | Database under test |
| Raw SQL Generator (Go) | 9090 | 25+ hand-written OLTP operations |
| ORM Generator (Python) | 9091 | 10 auto-discovered ORM patterns |
| Dashboard | 8200 | Real-time metrics + charts |
| Control Plane API | 8100 | Orchestration REST API (`/docs` for Swagger) |
| Control Panel UI | 3100 | Browser-based controls (primary interface) |

## How to Monitor the Stress Test

Once the stack is running, use these tools to see what's happening:

### From the browser

| URL | What you see |
|-----|-------------|
| `http://<host>:3100` | **Control Panel** — intensity controls, BYOD import, inject rows, bulk update, growth ladders, AI analysis, service status |
| `http://<host>:8200` | **Dashboard** — real-time charts: TPS, cache hit ratio, active connections, table sizes, dead tuples |
| `http://<host>:8100/docs` | **API Docs** — Swagger UI for all control plane endpoints |

### From the command line

```bash
# ORM generator — per-pattern operation counts
curl -s http://<host>:9091/healthz | python3 -m json.tool

# Stack status — services, DB size (bytes), connections, per-table row counts
curl -s http://<host>:8100/status | python3 -m json.tool

# Current config — database target + intensity level
curl -s http://<host>:8100/config | python3 -m json.tool

# Top 20 queries by execution time (what's actually hitting the DB)
make pg-stat

# Database and table sizes
make db-size
```

### What to look for

| Metric | Where to find it | What it means |
|--------|-------------------|---------------|
| **Active connections** | Dashboard or `/status` | How many concurrent connections are hitting the DB |
| **ORM ops counts** | `/healthz` on `:9091` | How many of each pattern (N+1, eager join, etc.) have run |
| **Top queries** | `make pg-stat` | Which queries consume the most total time — these are tuning candidates |
| **Dead tuples** | Dashboard or `/status` | Tables with high dead tuples need autovacuum attention |
| **DB size growth** | Dashboard or `/status` | Track how fast the database is growing under load |
| **Cache hit ratio** | Dashboard | Below 99% means shared_buffers may be too small |
| **Errors** | `/healthz` on `:9091` | Non-zero errors means queries are failing |

## Next Steps

```bash
# Switch intensity
make up INTENSITY=high

# Run WHAT IF scenarios from the UI
open http://localhost:3100

# Get AI advisory
export ANTHROPIC_API_KEY=sk-ant-...
make analyze
```
