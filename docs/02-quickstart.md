# Quickstart

## Prerequisites

| Requirement | Minimum |
|-------------|---------|
| Docker | 24.0+ |
| Docker Compose | v2.20+ |
| Disk (free) | 20 GB |
| Memory (free) | 4 GB |

## Path A: I Have Production Data

```bash
git clone https://github.com/dataalgebra-engineering/pg-stress.git
cd pg-stress
cp .env.example .env     # Edit PG_USER, PG_PASSWORD if needed

# Start PostgreSQL
docker compose up -d postgres

# Restore your dump
docker compose exec -T postgres pg_restore \
  -U postgres -d testdb --jobs=4 --no-owner < /path/to/dump.sql
docker compose exec -T postgres psql -U postgres -d testdb -c "ANALYZE"

# Start everything
make up INTENSITY=medium
```

Open `http://localhost:3100` — pg-stress auto-discovers your schema and starts generating load.

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
open http://localhost:8000

# Control panel live?
open http://localhost:3100
```

## What's Running

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL 15 | 5434 | Database under test |
| Raw SQL Generator (Go) | 9090 | 25+ hand-written OLTP operations |
| ORM Generator (Python) | 9091 | 10 auto-discovered ORM patterns |
| Dashboard | 8000 | Real-time metrics + charts |
| Control Plane API | 8100 | Orchestration REST API |
| Control Panel UI | 3100 | Browser-based controls |

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
